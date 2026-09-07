"""TerminalDisplay lifecycle coordinator for the Code Squid console."""

from dataclasses import replace
from pathlib import Path
import re
from typing import TextIO

from prompt_toolkit.output.base import Output
from wcwidth import wcswidth

from squid_core.safety import ApprovalDecision, USER_DENIED_TOOL_ACTION
from squid_core.mods import discover_mods

from code_squid.app_paths import code_squid_home
from code_squid.console.ui.approval import (
    APPROVAL_PANEL_WIDTH,
    INPUT_PROMPT_PREFIX,
    INPUT_PROMPT_STYLE,
    approval_panel,
    can_compact_approval_prompt,
    clear_printed_lines,
    printed_prompt_line_count,
    rejected_approval_result,
)
from code_squid.console.ui.banner import (
    StartupInfo,
    startup_info_panel,
)
from code_squid.console.ui.binary_header import BinaryRainHeader
from code_squid.console.ui.formatting import (
    BOLD_STYLE,
    DIM_STYLE,
    FINAL_SUMMARY_INDENT,
    DEFAULT_MOD_ACCENT_HEX,
    RESET_STYLE,
    RUN_PANEL_WIDTH,
    SQUID_GLYPH,
    SOFT_CYAN_HEX,
    SOFT_CYAN_STYLE,
    SOFT_GREEN_HEX,
    SOFT_GREEN_STYLE,
    SOFT_RED_HEX,
    SOFT_RED_STYLE,
    SOFT_YELLOW_HEX,
    SOFT_YELLOW_STYLE,
    ansi_fg,
    file_link,
    format_final_summary,
    mod_accent_hex,
    short_path,
    structural_prefix,
    structural_text,
    styled_text,
    wrapped_display_lines,
)
from code_squid.console.ui.prompt_input import prompt_multiline_input
from code_squid.console.ui.spinner import TerminalSpinner
from code_squid.console.ui.streaming_narration import StreamingNarration
from code_squid.console.ui.startup_application import (
    finish_startup_application,
    startup_application_active,
)
from code_squid.console.ui.tool_display import (
    FILE_TOOLS,
    action_label,
    debug_action_lines,
    debug_tool_result_lines,
    tool_result_line,
)


RUN_EVENT_INDENT = "  "
RUN_DETAIL_INDENT = "    "
INPUT_IDENTITY_LINE = "@code-squid"
PANEL_LEFT_PADDING = "  "
PANEL_CONTENT_WIDTH = RUN_PANEL_WIDTH - 2 - len(PANEL_LEFT_PADDING) - 1
ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x1b]*(?:\x1b\\|\x07))"
)


def _accent_for_mod(mod_name: str | None) -> str:
    """Resolve the current Mod accent without retaining stale selection state."""
    if mod_name is None:
        return DEFAULT_MOD_ACCENT_HEX
    mod = discover_mods(code_squid_home()).get(mod_name)
    if mod is None:
        return DEFAULT_MOD_ACCENT_HEX
    return mod_accent_hex(getattr(mod, "accent", None))


class TerminalDisplay:
    """Coordinate terminal lifecycle presentation for the agent loop."""

    def __init__(
        self,
        debug: bool = False,
        show_transcript: bool = False,
        startup_info: StartupInfo | None = None,
        _spinner: TerminalSpinner | None = None,
        _header: BinaryRainHeader | None = None,
        _output_stream: TextIO | None = None,
        _narration_output: Output | None = None,
    ) -> None:
        self.debug = debug
        self.show_transcript = show_transcript
        self.startup_info = startup_info
        self.header = _header if _header is not None else BinaryRainHeader()
        self._interrupted = False
        self._spinner = (
            _spinner
            if _spinner is not None
            else TerminalSpinner(
                enabled=not debug,
                prefix=RUN_EVENT_INDENT,
            )
        )
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False
        self._compacted_denied_action: dict | None = None
        self._session_scene_active = False
        self._pending_final_content = ""
        self._has_run_output = False
        # The action lifecycle counts read-only and custom tools too; written
        # files are deliberately not a proxy for whether this is a report.
        self._tool_used_in_run = False
        self._streaming_narration = StreamingNarration(
            self._assistant_narration_panel_lines,
            stream=_output_stream,
            # Debug mode is a static diagnostic transcript; live rewrites
            # would interleave with its reply details.
            enabled=not debug,
            output=_narration_output,
        )

    def start(self) -> None:
        self._streaming_narration.discard()
        self._stop_spinner()
        self.start_session_scene()
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False

    def run_started(self) -> None:
        self._streaming_narration.discard()
        self.retire_session_scene()
        self._stop_spinner()
        # Construction and the model request can proceed during the fade. The
        # traditional separating blank is deferred until visible output needs
        # the terminal, at which point ownership is transferred synchronously.
        if startup_application_active(self.header):
            self._needs_leading_blank = True
        else:
            print()
            self._needs_leading_blank = False
        self._pending_final_content = ""
        self._has_run_output = False
        self._tool_used_in_run = False
        self._needs_detail_blank_after_assistant = False

    def thinking(self) -> None:
        self._finish_startup_before_output()
        if self.debug:
            print("Thinking...")
            print()
            return
        self._print_leading_blank_if_needed()
        self._spinner.start()

    def assistant_message(self, content: str) -> None:
        content = content.strip()
        if self._streaming_narration.retained:
            self._commit_streamed_narration(content)
            return
        self._stop_spinner()
        if self._commit_streamed_narration(content):
            return
        if self.debug:
            if content:
                self._print_assistant_narration(content)
            return
        if not content:
            return

        self._finish_startup_before_output()
        self._print_leading_blank_if_needed()
        if self._needs_detail_blank_after_assistant:
            print()
            self._needs_detail_blank_after_assistant = False
        self._print_assistant_narration(content, trailing_blank=False)
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = True

    def final_message(self, content: str) -> None:
        self._streaming_narration.discard()
        self._stop_spinner()
        # Written paths arrive in loop_finished, so retain the report briefly to
        # print both completion sections inside one static panel when needed.
        self._pending_final_content = content.strip()

    def action_started(self, action: dict) -> None:
        self._tool_used_in_run = True
        self._stop_spinner()
        if self.debug and action.get("tool") not in FILE_TOOLS:
            self._finish_startup_before_output()
            print(self._action_text(action))
            self._has_run_output = True

    def approve_action(self, action: dict) -> ApprovalDecision:
        self._finish_startup_before_output()
        self._stop_spinner()
        self._print_leading_blank_if_needed()
        if self._needs_detail_blank_after_assistant:
            print()
        self._needs_detail_blank_after_assistant = False
        panel_lines, prompt = approval_panel(
            action,
            debug=self.debug,
            display_root=self._display_root(),
            detail_indent=RUN_DETAIL_INDENT,
        )
        for line in panel_lines:
            print(line)
        self._has_run_output = True
        self._needs_leading_blank = True
        response = prompt_multiline_input(prompt)
        approved = response.strip() == ""
        instruction = "" if approved else response
        can_compact = (
            can_compact_approval_prompt(
                debug=self.debug,
                show_transcript=self.show_transcript,
            )
            and "\n" not in response
        )
        if can_compact:
            clear_printed_lines(len(panel_lines) + printed_prompt_line_count(prompt))
            self._print_compact_approval_result(action, approved, instruction)
        elif not approved:
            self._print_rejected_approval_result(instruction)
            self._compacted_denied_action = action
        return ApprovalDecision(approved=approved, instruction=instruction)

    def _action_text(self, action: dict) -> str:
        return action_label(action, "start", self._display_root())

    def _print_compact_approval_result(
        self, action: dict, approved: bool, instruction: str
    ) -> None:
        if approved:
            self._needs_leading_blank = False
            self._compacted_denied_action = None
            return
        self._print_rejected_approval_result(instruction)
        self._needs_leading_blank = True
        self._compacted_denied_action = action

    def _print_rejected_approval_result(self, instruction: str) -> None:
        print(rejected_approval_result(instruction, RUN_DETAIL_INDENT))

    def tool_result(self, action: dict, result: dict) -> None:
        self._finish_startup_before_output()
        self._stop_spinner()
        if result.get("error") == USER_DENIED_TOOL_ACTION:
            if self._compacted_denied_action == action:
                self._compacted_denied_action = None
                return
            self._print_visible_line("🚫 Action denied", style=SOFT_RED_STYLE)
            self._print_debug_tool_result(action, result)
            return

        presentation = tool_result_line(action, result, self._display_root())
        if presentation is not None:
            label, style, dim = presentation
            self._print_visible_line(label, style=style, dim=dim)
        self._print_debug_tool_result(action, result)

    def reply_rejected(self, reason: str) -> None:
        self._finish_startup_before_output()
        self._streaming_narration.discard()
        self._stop_spinner()
        self._print_visible_line(self._reply_rejected_line(reason), style=SOFT_YELLOW_STYLE)

    def repeated_invalid_replies(self, reason: str, count: int) -> None:
        self._finish_startup_before_output()
        self._stop_spinner()
        self._print_visible_line(
            f"⚠️ Stopping after {count} invalid replies: {reason}",
            style=SOFT_YELLOW_STYLE,
        )

    def step_limit_reached(self, max_tool_steps: int) -> None:
        self._finish_startup_before_output()
        self._stop_spinner()
        self._print_visible_line(
            f"⚠️ Stopping after reaching tool step limit: {max_tool_steps}",
            style=SOFT_YELLOW_STYLE,
        )

    def interrupted(self) -> None:
        self._finish_startup_before_output()
        self._streaming_narration.discard()
        self._stop_spinner()
        self._interrupted = True
        self._print_visible_line("⏹️ Interrupted", style=SOFT_YELLOW_STYLE)

    def model_request_failed(self, log_path: Path) -> None:
        self._finish_startup_before_output()
        self._streaming_narration.discard()
        self._stop_spinner()
        # Provider details belong in the saved log; normal CLI output stays stable.
        self._print_leading_blank_if_needed()
        print(styled_text("🚫 Model request failed", SOFT_RED_STYLE))
        print()
        print("Code Squid could not get a response from the configured model provider.")
        print(f"Details saved to: {log_path.as_posix()}")
        self._has_run_output = True

    def loop_finished(self, session, run_result=None) -> None:
        self._finish_startup_before_output()
        self._streaming_narration.discard()
        self._stop_spinner()
        if self._needs_leading_blank:
            self._print_leading_blank_if_needed()
        elif self._has_run_output:
            print()
        self._print_completion_panel(session)
        status = getattr(run_result, "status", None)
        if status is None:
            status = "interrupted" if self._interrupted else "complete"

        print()
        if status == "failed":
            print(styled_text("❌ Session failed", SOFT_RED_STYLE))
        elif status == "interrupted":
            print(styled_text("⚠️ Session interrupted", SOFT_YELLOW_STYLE))
        if not self.show_transcript:
            return

        print()
        print("Full transcript:")
        for message in session.messages:
            print(f"\n[{message['role']}]")
            print(message["content"])

    def debug_reply(self, reply: dict) -> None:
        if not self.debug:
            return
        self._finish_startup_before_output()
        self._stop_spinner()
        actions = reply.get("actions", [])
        if not actions:
            self._debug_block("model action", ["none"])
        for action in actions:
            self._debug_block(
                "model action", debug_action_lines(action, self._display_root())
            )
        if reply.get("format_error"):
            print(f"format_error: {reply['format_error']}")

    def handle_event(self, event: dict) -> None:
        """Translate Core's streamed-assistant events into CLI presentation."""
        event_type = event.get("type")
        if event_type == "assistant_message_started":
            self._streaming_narration.begin()
            return
        if event_type == "assistant_delta":
            delta = event.get("delta", "")
            if not isinstance(delta, str) or not delta:
                return
            if (
                not self._streaming_narration.visible
                and self._streaming_narration.can_render
            ):
                self._prepare_assistant_narration()
            self._streaming_narration.append(delta)
            return
        if event_type == "tool_preparing":
            if (
                self._streaming_narration.can_render
                and self._streaming_narration.retain_live_frame()
            ):
                # retain_live_frame joins the Application thread first, so the
                # ordinary spinner cannot compete with prompt_toolkit output.
                self.thinking()
            return
        if event_type == "assistant_message" and self._streaming_narration.active:
            content = str(event.get("message", "")).strip()
            self._commit_streamed_narration(content)
            return
        if event_type in {
            "tool_started",
            "tool_finished",
            "run_cancelled",
            "run_failed",
            "run_finished",
        }:
            self._stop_spinner()
            return
        if event_type in {"reply_rejected", "final_message"}:
            self._streaming_narration.discard()
            self._stop_spinner()

    @property
    def streaming_narration_active(self) -> bool:
        """Return whether temporary narration currently owns lifecycle state."""
        return self._streaming_narration.active

    def _stop_spinner(self) -> None:
        # Clear animation before ordinary prints so logs contain complete lines.
        self._spinner.stop()

    def _print_startup_banner(self) -> None:
        # Scene state is prepared here, but the temporary StartupApplication
        # performs every terminal write when the prompt begins.
        self.header.set_startup_info(self.startup_info)

    def stop_header(self) -> None:
        """Synchronously stop any submitted fade and mark startup inactive."""
        finish_startup_application(self.header)
        self._session_scene_active = False

    def finish_startup_fade(self) -> None:
        """Release startup ownership before a direct CLI print operation."""
        self._finish_startup_before_output()

    def _finish_startup_before_output(self) -> None:
        """Give ordinary output exclusive ownership of the terminal."""
        finish_startup_application(self.header)

    @property
    def session_scene_active(self) -> bool:
        """Return whether prompts may still interact with the startup scene."""
        return self._session_scene_active

    def start_session_scene(self) -> None:
        """Render one fresh interactive scene for a new session boundary."""
        if self._session_scene_active:
            return
        self._print_startup_banner()
        self._session_scene_active = True

    def retire_session_scene(self) -> None:
        """End startup ownership before ordinary print output resumes."""
        if not self._session_scene_active:
            return
        self._session_scene_active = False

    def set_specialization(
        self,
        *,
        mod_name: str | None,
        skill_name: str | None,
    ) -> None:
        """Keep the presentation copy of active specialization state current."""
        if self.startup_info is None:
            return
        self.startup_info = replace(
            self.startup_info,
            mod_name=mod_name,
            skill_name=skill_name,
        )
        self.header.set_startup_info(self.startup_info)

    def set_startup_menu(self, startup_menu) -> None:
        """Connect keyboard menu state to the existing header renderer."""
        self.header.set_startup_menu(startup_menu)

    def _startup_info_panel(self, startup_info: StartupInfo) -> str:
        """Return startup details through the existing display test seam."""
        return startup_info_panel(startup_info)

    def _print_leading_blank_if_needed(self) -> None:
        # Tool results are one-line event blocks; separate the next visible block here.
        if self._needs_leading_blank:
            self._finish_startup_before_output()
            print()
            self._needs_leading_blank = False

    def _print_visible_line(self, line: str, dim: bool = False, style: str = "") -> None:
        self._print_leading_blank_if_needed()
        if self._needs_detail_blank_after_assistant:
            print()
            self._needs_detail_blank_after_assistant = False
        if not self.debug:
            line = self._run_detail_line(line)
        print(styled_text(line, *(style, DIM_STYLE if dim else "")))
        self._needs_leading_blank = True
        self._has_run_output = True

    def _run_event_line(self, line: str) -> str:
        return self._indented_run_line(line, RUN_EVENT_INDENT)

    def _run_detail_line(self, line: str) -> str:
        return self._indented_run_line(line, RUN_DETAIL_INDENT)

    def _indented_run_line(self, line: str, indent: str) -> str:
        return f"{indent}{line}" if line else line

    def _reply_rejected_line(self, reason: str) -> str:
        if self.debug:
            return f"⚠️ Reply rejected: {reason}"
        messages = {
            "empty_final_reply": "↪ Asking model to continue or finalize…",
            "non_final_too_many_tool_calls": "⚠️ Reply rejected: expected exactly one tool call.",
            "malformed_tool_call": "⚠️ Reply rejected: could not read the requested tool call.",
        }
        return messages.get(reason, "⚠️ Reply rejected: invalid assistant reply.")

    def _print_assistant_narration(self, content: str, trailing_blank: bool = True) -> None:
        self._print_rendered_lines(self._assistant_narration_panel_lines(content))
        self._has_run_output = True
        if trailing_blank:
            print()

    def _assistant_narration_panel_lines(
        self,
        content: str,
        viewport_width: int = RUN_PANEL_WIDTH,
    ) -> list[str]:
        """Return physical panel rows shared by static and live narration."""
        # Below nine cells the squid marker and structural padding cannot form
        # a valid panel. Keep valid internal geometry and let prompt_toolkit
        # clip it to the truthful (smaller) physical viewport.
        panel_width = max(min(RUN_PANEL_WIDTH, viewport_width), 9)
        content_width = panel_width - 2 - len(PANEL_LEFT_PADDING) - 1
        source_lines = content.splitlines() or [""]
        panel_lines: list[str] = []
        narration_indent = " " * (_display_width(SQUID_GLYPH) + 1)
        for index, source_line in enumerate(source_lines):
            if not source_line:
                panel_lines.append("")
                continue
            prefix = f"{SQUID_GLYPH} " if index == 0 else narration_indent
            panel_lines.extend(
                wrapped_display_lines(
                    source_line,
                    initial_indent=prefix,
                    subsequent_indent=narration_indent,
                    width=content_width,
                )
            )
        if panel_lines:
            panel_lines[0] = self._accent_first_squid(panel_lines[0])
        return self._render_panel_lines(panel_lines, panel_width=panel_width)

    def _prepare_assistant_narration(self) -> None:
        """Transfer terminal ownership from the spinner to the live panel."""
        self._finish_startup_before_output()
        self._stop_spinner()
        self._print_leading_blank_if_needed()
        if self._needs_detail_blank_after_assistant:
            print()
            self._needs_detail_blank_after_assistant = False

    def _commit_streamed_narration(self, content: str) -> bool:
        settled = self._streaming_narration.commit(content)
        if not settled:
            return False
        self._has_run_output = True
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = True
        return True

    def _debug_block(self, title: str, lines: list[str]) -> None:
        self._finish_startup_before_output()
        width = 47
        top_label = f"─ {title} "
        print(structural_text(f"┌{top_label}{'─' * max(width - len(top_label), 0)}"))
        for line in lines:
            print(structural_prefix("│", f" {line}"))
        print(structural_text(f"└{'─' * width}"))

    def _print_debug_tool_result(self, action: dict, result: dict) -> None:
        if not self.debug:
            return
        print()
        self._debug_block(
            "tool result",
            debug_tool_result_lines(action, result, self._display_root()),
        )

    def _print_completion_panel(self, session) -> None:
        """Print the final response and any files changed as one panel."""
        heading = " Report:" if self._tool_used_in_run else ""
        lines = [self._squid_line(heading), ""]
        formatted = format_final_summary(
            self._pending_final_content,
            width=PANEL_CONTENT_WIDTH,
        )
        if formatted:
            lines.extend(formatted.splitlines())
        if session.files_written:
            lines.extend(["", "Changed files", ""])
            lines.extend(self._file_lines(session.files_written))
        self._print_panel(lines)
        self._pending_final_content = ""
        self._needs_leading_blank = False

    def _active_mod_name(self) -> str | None:
        """Read menu state first so a just-selected Mod affects the next line."""
        menu = getattr(self.header, "startup_menu", None)
        if menu is not None:
            return menu.mod_name
        return self.startup_info.mod_name if self.startup_info is not None else None

    def _accent_hex(self) -> str:
        return _accent_for_mod(self._active_mod_name())

    def _squid_line(self, suffix: str) -> str:
        """Accent only the squid glyph and immediately restore terminal color."""
        return f"{styled_text(SQUID_GLYPH, ansi_fg(self._accent_hex()))}{suffix}"

    def _accent_first_squid(self, line: str) -> str:
        """Accent an existing leading narration marker without adding one."""
        squid_index = line.find(SQUID_GLYPH)
        if squid_index < 0:
            return line
        return (
            f"{line[:squid_index]}"
            f"{styled_text(SQUID_GLYPH, ansi_fg(self._accent_hex()))}"
            f"{line[squid_index + len(SQUID_GLYPH):]}"
        )

    def _print_panel(self, lines: list[str]) -> None:
        """Print fixed-width run content with quiet, terminal-neutral borders."""
        self._print_rendered_lines(self._render_panel_lines(lines))

    def _print_rendered_lines(self, lines: list[str]) -> None:
        """Print already-built physical rows through ordinary terminal output."""
        self._finish_startup_before_output()
        for line in lines:
            print(line)

    def _render_panel_lines(
        self,
        lines: list[str],
        *,
        panel_width: int = RUN_PANEL_WIDTH,
    ) -> list[str]:
        """Build fixed-width physical rows without taking terminal ownership."""
        content_width = panel_width - 2 - len(PANEL_LEFT_PADDING) - 1
        horizontal = "─" * (panel_width - 2)
        rendered = [styled_text(f"╭{horizontal}╮", DIM_STYLE)]
        for line in lines:
            visible_width = _display_width(line)
            # All variable content is cell-wrapped before reaching this fixed
            # geometry seam; fail close to the violating caller if that changes.
            if visible_width > content_width:
                raise ValueError("run panel content exceeds its fixed width")
            padding = " " * (content_width - visible_width + 1)
            left = styled_text("│", DIM_STYLE)
            right = styled_text("│", DIM_STYLE)
            rendered.append(f"{left}{PANEL_LEFT_PADDING}{line}{padding}{right}")
        rendered.append(styled_text(f"╰{horizontal}╯", DIM_STYLE))
        return rendered

    def _format_final_summary(self, content: str) -> str:
        """Return final report text through the existing display test seam."""
        return format_final_summary(content)

    def _file_lines(self, paths: set[str]) -> list[str]:
        """Return wrapped file rows for a non-empty changed-path set."""
        lines = []
        for path in sorted(paths):
            label = path if self.debug else self._short_path(path)
            chunks = wrapped_display_lines(
                label,
                initial_indent="",
                subsequent_indent="",
                width=PANEL_CONTENT_WIDTH - 6,
            ) or [""]
            for chunk in chunks:
                display_path = chunk if self.debug else file_link(path, chunk)
                lines.append(f"      {display_path}")
        return lines

    def _short_path(self, path: str) -> str:
        """Return a display path through the existing display test seam."""
        return short_path(path, self._display_root())

    def _display_root(self) -> Path:
        if self.startup_info is not None:
            return self.startup_info.directory.resolve()
        return Path.cwd().resolve()


def _display_width(value: str) -> int:
    """Return terminal cell width after removing local ANSI/OSC styling."""
    plain = ANSI_ESCAPE_PATTERN.sub("", value)
    width = wcswidth(plain)
    return len(plain) if width < 0 else width

"""TerminalDisplay lifecycle coordinator for the Code Squid console."""

from dataclasses import replace
from pathlib import Path

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
from code_squid.console.ui.tool_display import (
    FILE_TOOLS,
    action_label,
    debug_action_lines,
    debug_tool_result_lines,
    tool_result_line,
)


RAIL_WIDTH = 61
FINAL_REPORT_DIVIDER = "─" * RAIL_WIDTH
RUN_EVENT_INDENT = "  "
RUN_DETAIL_INDENT = "    "
INPUT_IDENTITY_LINE = "@code-squid"


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
                style=ansi_fg(DEFAULT_MOD_ACCENT_HEX),
            )
        )
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False
        self._compacted_denied_action: dict | None = None
        self._session_scene_active = False

    def start(self) -> None:
        self._stop_spinner()
        self.start_session_scene()
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False

    def run_started(self) -> None:
        self.retire_session_scene()
        self._stop_spinner()
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False

    def thinking(self) -> None:
        if self.debug:
            print(self._squid_line(" Thinking..."))
            print()
            return
        self._print_leading_blank_if_needed()
        self._spinner.style = ansi_fg(self._accent_hex())
        self._spinner.start()

    def assistant_message(self, content: str) -> None:
        self._stop_spinner()
        content = content.strip()
        if self.debug:
            if content:
                self._print_assistant_narration(content)
            return
        if not content:
            return

        self._print_leading_blank_if_needed()
        self._print_assistant_narration(content, trailing_blank=False)
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = True

    def final_message(self, content: str) -> None:
        self._stop_spinner()
        content = content.strip()
        if content:
            self._print_final_summary(content)

    def action_started(self, action: dict) -> None:
        self._stop_spinner()
        if self.debug and action.get("tool") not in FILE_TOOLS:
            print(self._action_text(action))

    def approve_action(self, action: dict) -> ApprovalDecision:
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
        self._stop_spinner()
        self._print_visible_line(self._reply_rejected_line(reason), style=SOFT_YELLOW_STYLE)

    def repeated_invalid_replies(self, reason: str, count: int) -> None:
        self._stop_spinner()
        self._print_visible_line(
            f"⚠️ Stopping after {count} invalid replies: {reason}",
            style=SOFT_YELLOW_STYLE,
        )

    def step_limit_reached(self, max_tool_steps: int) -> None:
        self._stop_spinner()
        self._print_visible_line(
            f"⚠️ Stopping after reaching tool step limit: {max_tool_steps}",
            style=SOFT_YELLOW_STYLE,
        )

    def interrupted(self) -> None:
        self._stop_spinner()
        self._interrupted = True
        self._print_visible_line("⏹️ Interrupted", style=SOFT_YELLOW_STYLE)

    def model_request_failed(self, log_path: Path) -> None:
        self._stop_spinner()
        # Provider details belong in the saved log; normal CLI output stays stable.
        self._print_leading_blank_if_needed()
        print(styled_text("🚫 Model request failed", SOFT_RED_STYLE))
        print()
        print("Code Squid could not get a response from the configured model provider.")
        print(f"Details saved to: {log_path.as_posix()}")

    def loop_finished(self, session, run_result=None) -> None:
        self._stop_spinner()
        if self._needs_leading_blank:
            self._print_leading_blank_if_needed()
        else:
            print()
        print(styled_text(FINAL_REPORT_DIVIDER, DIM_STYLE))
        print("🗂️  Session files")
        print()
        self._print_file_list("Read", session.files_read)
        print()
        self._print_file_list("Written", session.files_written)
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

    def _stop_spinner(self) -> None:
        # Clear animation before ordinary prints so logs contain complete lines.
        self._spinner.stop()

    def _print_startup_banner(self) -> None:
        # The header owns the complete scene so rain and fixed UI share one
        # geometry and one redraw lifecycle.
        self.header.set_startup_info(self.startup_info)
        self.header.set_live_content_below_header("", extra_rows=2)
        self.header.start()
        print()

    def pause_header(self) -> None:
        """Freeze header redraws before ordinary console output begins."""
        self.header.pause()

    def stop_header(self) -> None:
        """Stop the header worker and restore terminal cursor state."""
        self.header.stop()
        self._session_scene_active = False

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
        """Freeze the rendered scene in scrollback and stop its worker."""
        if not self._session_scene_active:
            return
        self.header.stop()
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
        lines = content.splitlines() or [""]
        if self.debug:
            print(self._squid_line(f" {lines[0]}"))
            for line in lines[1:]:
                print(f"   {line}" if line else "")
            if trailing_blank:
                print()
            return
        for output_line in wrapped_display_lines(
            lines[0],
            initial_indent=f"{RUN_EVENT_INDENT}🦑 ",
            subsequent_indent=f"{RUN_EVENT_INDENT}   ",
        ):
            print(self._accent_first_squid(output_line))
        for line in lines[1:]:
            if not line:
                print()
                continue
            for output_line in wrapped_display_lines(
                line,
                initial_indent=f"{RUN_EVENT_INDENT}   ",
                subsequent_indent=f"{RUN_EVENT_INDENT}   ",
            ):
                print(output_line)
        if trailing_blank:
            print()

    def _debug_block(self, title: str, lines: list[str]) -> None:
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

    def _print_final_summary(self, content: str) -> None:
        formatted = format_final_summary(content)
        if not formatted:
            return
        self._print_leading_blank_if_needed()
        print(styled_text(FINAL_REPORT_DIVIDER, DIM_STYLE))
        print(self._squid_line(" Report:"))
        print()
        print(formatted)
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
        return f"{styled_text('🦑', ansi_fg(self._accent_hex()))}{suffix}"

    def _accent_first_squid(self, line: str) -> str:
        """Accent an existing leading narration marker without adding one."""
        squid_index = line.find("🦑")
        if squid_index < 0:
            return line
        return (
            f"{line[:squid_index]}"
            f"{styled_text('🦑', ansi_fg(self._accent_hex()))}"
            f"{line[squid_index + 1:]}"
        )

    def _format_final_summary(self, content: str) -> str:
        """Return final report text through the existing display test seam."""
        return format_final_summary(content)

    def _print_file_list(self, title: str, paths: set[str]) -> None:
        print(f"  {title}")
        if not paths:
            print("    none")
            return
        for path in sorted(paths):
            display_path = path if self.debug else file_link(path, self._short_path(path))
            print(f"    {display_path}")

    def _short_path(self, path: str) -> str:
        """Return a display path through the existing display test seam."""
        return short_path(path, self._display_root())

    def _display_root(self) -> Path:
        if self.startup_info is not None:
            return self.startup_info.directory.resolve()
        return Path.cwd().resolve()

"""TerminalDisplay lifecycle coordinator for the Code Squid console."""

from dataclasses import replace
from pathlib import Path

from squid_core.safety import ApprovalDecision, USER_DENIED_TOOL_ACTION

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
    RESET_STYLE,
    SOFT_CYAN_HEX,
    SOFT_CYAN_STYLE,
    SOFT_GREEN_HEX,
    SOFT_GREEN_STYLE,
    SOFT_RED_HEX,
    SOFT_RED_STYLE,
    SOFT_YELLOW_HEX,
    SOFT_YELLOW_STYLE,
    file_link,
    format_final_summary,
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
RUN_STARTED_LABEL = "╰─ starting run "
RUN_STARTED_DIVIDER = f"{RUN_STARTED_LABEL}{'─' * (RAIL_WIDTH - len(RUN_STARTED_LABEL))}"
FINAL_REPORT_DIVIDER = "─" * RAIL_WIDTH
RUN_EVENT_INDENT = "  "
RUN_DETAIL_INDENT = "    "
INPUT_IDENTITY_LINE = "@code-squid"


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
                style=SOFT_CYAN_STYLE,
            )
        )
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False
        self._compacted_denied_action: dict | None = None
        self._prompt_has_started = False

    def start(self) -> None:
        self._stop_spinner()
        self._print_startup_banner()
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False

    def run_started(self) -> None:
        self.pause_header()
        self._stop_spinner()
        print()
        print(structural_text(RUN_STARTED_DIVIDER))
        print()
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False

    def thinking(self) -> None:
        if self.debug:
            print("🦑 Thinking...")
            print()
            return
        self._print_leading_blank_if_needed()
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
        print(structural_text(FINAL_REPORT_DIVIDER))
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
        else:
            print(styled_text("✅ Done!", SOFT_GREEN_STYLE))
        if not self.show_transcript:
            if status == "complete":
                print()
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

    def prepare_header_for_prompt(self) -> None:
        """Give each later prompt a fresh anchor below intervening output."""
        if not self._prompt_has_started:
            self._prompt_has_started = True
            return
        if not self.header.reanchor():
            return
        print()

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
            print(f"🦑 {lines[0]}")
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
            print(output_line)
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
        print(structural_text(FINAL_REPORT_DIVIDER))
        print("🦑 Report:")
        print()
        print(formatted)
        self._needs_leading_blank = False

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

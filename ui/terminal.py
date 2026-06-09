# ui/terminal.py

"""Small terminal display layer for Code Squid."""

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import shutil
import sys
import textwrap

from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText

from core.approval import ApprovalDecision, USER_DENIED_TOOL_ACTION
from ui.prompt_input import prompt_multiline_input
from ui.spinner import TerminalSpinner


PATH_LABEL_MAX = 56
COMMAND_LABEL_MAX = 64
APPROVAL_COMMAND_LABEL_MAX = 120
DISPLAY_WRAP_WIDTH = 64
CODE_SQUID_BANNER = """\

 ██████╗ ██████╗ ██████╗ ███████╗    ███████╗ ██████╗ ██╗   ██╗██╗██████╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝    ██╔════╝██╔═══██╗██║   ██║██║██╔══██╗
██║     ██║   ██║██║  ██║█████╗      ███████╗██║   ██║██║   ██║██║██║  ██║
██║     ██║   ██║██║  ██║██╔══╝      ╚════██║██║▄▄ ██║██║   ██║██║██║  ██║
╚██████╗╚██████╔╝██████╔╝███████╗    ███████║╚██████╔╝╚██████╔╝██║██████╔╝
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝    ╚══════╝ ╚══▀▀═╝  ╚═════╝ ╚═╝╚═════╝

                 🦑 A small coding agent with tentacles."""
RAIL_WIDTH = 61
RUN_STARTED_LABEL = "╰─ starting run "
RUN_STARTED_DIVIDER = f"{RUN_STARTED_LABEL}{'─' * (RAIL_WIDTH - len(RUN_STARTED_LABEL))}"
FINAL_REPORT_DIVIDER = "─" * RAIL_WIDTH
FINAL_SUMMARY_INDENT = "  "
RUN_EVENT_INDENT = "  "
RUN_DETAIL_INDENT = "    "
STARTUP_PANEL_WIDTH = 76
APPROVAL_PANEL_WIDTH = RAIL_WIDTH
STARTUP_CONTROLS = "Enter send • Alt+Enter newline • Ctrl+C stop"
INPUT_IDENTITY_LINE = "@code-squid 🦑"
INPUT_PROMPT_PREFIX = "› "
DIM_STYLE = "\033[2m"
BOLD_STYLE = "\033[1m"
RESET_STYLE = "\033[0m"
SOFT_CYAN_HEX = "#7dd3fc"
INPUT_PROMPT_STYLE = f"{SOFT_CYAN_HEX} bold"
SOFT_GREEN_HEX = "#86efac"
SOFT_YELLOW_HEX = "#ffea80"
SOFT_RED_HEX = "#f77998"


def _ansi_fg(hex_color: str) -> str:
    value = hex_color.removeprefix("#")
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


SOFT_CYAN_STYLE = _ansi_fg(SOFT_CYAN_HEX)
SOFT_GREEN_STYLE = _ansi_fg(SOFT_GREEN_HEX)
SOFT_YELLOW_STYLE = _ansi_fg(SOFT_YELLOW_HEX)
SOFT_RED_STYLE = _ansi_fg(SOFT_RED_HEX)


def _terminal_link(label: str, uri: str) -> str:
    return f"\033]8;;{uri}\033\\{label}\033]8;;\033\\"


def _file_link(path: str) -> str:
    if not sys.stdout.isatty():
        return path

    try:
        uri = Path(path).expanduser().resolve().as_uri()
    except (OSError, RuntimeError, ValueError):
        return path

    return _terminal_link(path, uri)


@dataclass(frozen=True)
class StartupInfo:
    directory: Path
    provider: str
    model: str
    approval_mode: str


def _styled_text(text: str, *styles: str) -> str:
    styles = tuple(style for style in styles if style)
    if not styles or not sys.stdout.isatty():
        return text
    return f"{''.join(styles)}{text}{RESET_STYLE}"


def _structural_text(text: str) -> str:
    return _styled_text(text, SOFT_CYAN_STYLE)


def _structural_prefix(prefix: str, text: str) -> str:
    if not sys.stdout.isatty():
        return f"{prefix}{text}"
    return f"{SOFT_CYAN_STYLE}{prefix}{RESET_STYLE}{text}"


def _structural_bordered_line(left: str, content: str, right: str) -> str:
    if not sys.stdout.isatty():
        return f"{left}{content}{right}"
    return (
        f"{SOFT_CYAN_STYLE}{left}{RESET_STYLE}"
        f"{content}"
        f"{SOFT_CYAN_STYLE}{right}{RESET_STYLE}"
    )


class TerminalDisplay:
    """Owns terminal formatting for the agent loop."""

    def __init__(
        self,
        debug: bool = False,
        show_transcript: bool = False,
        startup_info: StartupInfo | None = None,
        _spinner: TerminalSpinner | None = None,
    ) -> None:
        self.debug = debug
        self.show_transcript = show_transcript
        self.startup_info = startup_info
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

    def start(self) -> None:
        self._stop_spinner()
        self._print_startup_banner()
        self._needs_leading_blank = False
        self._needs_detail_blank_after_assistant = False

    def run_started(self) -> None:
        self._stop_spinner()
        print()
        print(_structural_text(RUN_STARTED_DIVIDER))
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
        if not content:
            return

        self._print_final_summary(content)

    def action_started(self, action: dict) -> None:
        self._stop_spinner()
        if not self.debug:
            return

        if action.get("tool") in {"read_file", "write_file", "apply_patch"}:
            return

        print(self._action_text(action))

    def approve_action(self, action: dict) -> ApprovalDecision:
        self._stop_spinner()
        self._print_leading_blank_if_needed()
        if self._needs_detail_blank_after_assistant:
            print()
        self._needs_detail_blank_after_assistant = False
        panel_lines, prompt = self._approval_panel(action)
        for line in panel_lines:
            print(line)
        self._needs_leading_blank = True
        response = prompt_multiline_input(prompt)
        approved = response.strip() == ""
        instruction = "" if approved else response
        can_compact = self._can_compact_approval_prompt() and "\n" not in response
        if can_compact:
            self._clear_printed_lines(
                len(panel_lines) + self._printed_prompt_line_count(prompt)
            )
            self._print_compact_approval_result(action, approved, instruction)
        elif not approved:
            self._print_rejected_approval_result(instruction)
            self._compacted_denied_action = action
        return ApprovalDecision(approved=approved, instruction=instruction)

    def _action_text(self, action: dict) -> str:
        return self._action_label(action, "start")

    def _approval_line(self, line: str) -> str:
        if self.debug:
            return line
        return self._run_detail_line(line)

    def _approval_panel(self, action: dict) -> tuple[list[str], AnyFormattedText]:
        inner_width = APPROVAL_PANEL_WIDTH - 2
        title = " approval required "
        top = f"╭─{title}{'─' * max(inner_width - len(title) - 1, 0)}╮"
        bottom = f"╰{'─' * inner_width}╯"
        lines = [
            self._approval_line(_structural_text(top)),
            self._approval_panel_line("Tool", str(action.get("tool", "")), inner_width),
            self._approval_panel_action_line(action, inner_width),
        ]
        if action.get("approval_reason"):
            lines.append(
                self._approval_panel_line(
                    "Reason",
                    self._approval_reason_label(action),
                    inner_width,
                )
            )
        lines.append(self._approval_line(_structural_text(bottom)))
        prompt = self._approval_prompt()
        return lines, prompt

    def _approval_reason_label(self, action: dict) -> str:
        reason = self._single_line(str(action.get("approval_reason", "")))
        if self._is_outside_workspace_approval(action):
            return "Outside workspace"
        return reason

    def _is_outside_workspace_approval(self, action: dict) -> bool:
        reason = self._single_line(str(action.get("approval_reason", "")))
        return reason.startswith("Requested path is outside the workspace root:")

    def _approval_panel_action_line(self, action: dict, inner_width: int) -> str:
        tool_name = action.get("tool", "")
        args = action.get("args", {})

        if tool_name in {"read_file", "write_file", "apply_patch"}:
            return self._approval_panel_line(
                "Path",
                self._short_path(self._single_line(args.get("path", ""))),
                inner_width,
            )

        if tool_name == "run_command":
            return self._approval_panel_line(
                "Action",
                self._single_line(args.get("command", "")),
                inner_width,
            )

        return self._approval_panel_line("Action", self._action_text(action), inner_width)

    def _approval_panel_line(self, label: str, value: str, inner_width: int) -> str:
        label_text = f"{label}:"
        label_width = 7
        available = inner_width - 2 - label_width - 1
        value = self._truncate_middle(str(value), max(available, 1))
        content = f" {label_text:<{label_width}} {value}"
        return self._approval_line(
            _structural_bordered_line("│", f"{content:<{inner_width}}", "│")
        )

    def _approval_prompt(self) -> AnyFormattedText:
        prompt_text = "Enter to approve, or type guidance instead:\n"
        if self.debug:
            return FormattedText(
                [
                    ("", prompt_text),
                    (INPUT_PROMPT_STYLE, INPUT_PROMPT_PREFIX),
                ]
            )
        return FormattedText(
            [
                ("", self._run_detail_line(prompt_text)),
                (INPUT_PROMPT_STYLE, INPUT_PROMPT_PREFIX),
            ]
        )

    def _printed_prompt_line_count(self, prompt: AnyFormattedText) -> int:
        if isinstance(prompt, str):
            text = prompt
        else:
            text = "".join(fragment[1] for fragment in prompt)
        return text.count("\n") + 1

    def _can_compact_approval_prompt(self) -> bool:
        return (
            not self.debug
            and not self.show_transcript
            and sys.stdout.isatty()
        )

    def _clear_printed_lines(self, line_count: int) -> None:
        for _ in range(line_count):
            sys.stdout.write("\033[1A\r\033[2K")
        sys.stdout.flush()

    def _print_compact_approval_result(
        self,
        action: dict,
        approved: bool,
        instruction: str,
    ) -> None:
        if approved:
            self._needs_leading_blank = False
            self._compacted_denied_action = None
            return

        self._print_rejected_approval_result(instruction)
        self._needs_leading_blank = True
        self._compacted_denied_action = action

    def _print_rejected_approval_result(self, instruction: str) -> None:
        if instruction:
            comment = self._truncate_middle(
                self._single_line(instruction),
                DISPLAY_WRAP_WIDTH,
            )
            label = f"💬 User note: {comment}"
            style = SOFT_CYAN_STYLE
        else:
            label = "🚫 Action denied"
            style = SOFT_RED_STYLE
        line = _styled_text(self._run_detail_line(label), style)
        print(line)

    def _single_line(self, value: object) -> str:
        return " ".join(str(value).splitlines())

    # These helpers are display-only. They must never mutate action args,
    # result payloads, session storage, or any values sent back to the agent.
    def _action_label(self, action: dict, phase: str) -> str:
        tool_name = action.get("tool", "")
        args = action.get("args", {})

        if tool_name == "read_file":
            path = self._short_path(args.get("path", ""))
            if phase == "failure":
                return f"❌ Read failed: {path}"
            return f"📖 Read: {path}"

        if tool_name == "write_file":
            path = self._short_path(args.get("path", ""))
            if phase == "success":
                return f"📝 Wrote: {path}"
            if phase == "failure":
                return f"❌ Write failed: {path}"
            return f"📝 Write: {path}"

        if tool_name == "apply_patch":
            path = self._short_path(args.get("path", ""))
            if phase == "success":
                return f"🩹 Patched: {path}"
            if phase == "failure":
                return f"❌ Patch failed: {path}"
            return f"🩹 Patch: {path}"

        if tool_name == "run_command":
            return self._command_label(
                args.get("command", ""),
                phase,
                max_length=APPROVAL_COMMAND_LABEL_MAX if phase == "start" else COMMAND_LABEL_MAX,
            )

        return f"🔧 Run: {tool_name}"

    def tool_result(self, action: dict, result: dict) -> None:
        self._stop_spinner()

        if result.get("error") == USER_DENIED_TOOL_ACTION:
            if self._compacted_denied_action == action:
                self._compacted_denied_action = None
                return
            self._print_visible_line("🚫 Action denied", style=SOFT_RED_STYLE)
            self._print_debug_tool_result(action, result)
            return

        tool_name = action.get("tool")
        if tool_name == "run_command":
            self._run_command_result(action, result)
            self._print_debug_tool_result(action, result)
            return

        if result.get("ok", False):
            if tool_name in {"read_file", "write_file", "apply_patch"}:
                self._print_visible_line(self._action_label(action, "success"), dim=True)
            self._print_debug_tool_result(action, result)
            return

        error = result.get("error", "unknown error")
        if tool_name in {"read_file", "write_file", "apply_patch"}:
            self._print_visible_line(
                f"{self._action_label(action, 'failure')} - {error}",
                style=SOFT_RED_STYLE,
            )
            self._print_debug_tool_result(action, result)
            return

        self._print_visible_line(f"❌ {tool_name} failed: {error}", style=SOFT_RED_STYLE)
        self._print_debug_tool_result(action, result)

    def reply_rejected(self, reason: str) -> None:
        self._stop_spinner()
        self._print_visible_line(
            self._reply_rejected_line(reason),
            style=SOFT_YELLOW_STYLE,
        )

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
        # Normal CLI users need a clear failure and the saved details path,
        # not a raw traceback from whichever provider happened to fail.
        self._print_leading_blank_if_needed()
        print(_styled_text("🚫 Model request failed", SOFT_RED_STYLE))
        print()
        print("Code Squid could not get a response from the configured model provider.")
        print(f"Details saved to: {log_path}")

    def loop_finished(self, session, run_result=None) -> None:
        self._stop_spinner()
        if self._needs_leading_blank:
            self._print_leading_blank_if_needed()
        else:
            print()

        print(_structural_text(FINAL_REPORT_DIVIDER))
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
            print(_styled_text("❌ Session failed", SOFT_RED_STYLE))
        elif status == "interrupted":
            print(_styled_text("⚠️ Session interrupted", SOFT_YELLOW_STYLE))
        else:
            print(_styled_text("✅ Done!", SOFT_GREEN_STYLE))

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
            self._debug_block("model action", self._debug_action_lines(action))
        if reply.get("format_error"):
            print(f"format_error: {reply['format_error']}")

    def _stop_spinner(self) -> None:
        # The spinner is UI-only. Clear it before ordinary prints so redirected
        # logs and terminal output contain complete lines instead of animation.
        self._spinner.stop()

    def _print_startup_banner(self) -> None:
        print(CODE_SQUID_BANNER)
        if self.startup_info is not None:
            print()
            print(self._startup_info_panel(self.startup_info))
        print()

    def _startup_info_panel(self, startup_info: StartupInfo) -> str:
        inner_width = STARTUP_PANEL_WIDTH - 2
        title = " startup "
        top = f"╭─{title}{'─' * max(inner_width - len(title) - 1, 0)}╮"
        bottom = f"╰{'─' * inner_width}╯"
        lines = [
            ("Directory", str(startup_info.directory)),
            ("Provider", startup_info.provider),
            ("Model", startup_info.model),
            ("Approval mode", startup_info.approval_mode),
            ("Controls", STARTUP_CONTROLS),
        ]
        return "\n".join(
            [
                _structural_text(top),
                *(self._startup_info_line(label, value, inner_width) for label, value in lines),
                _structural_text(bottom),
            ]
        )

    def _startup_info_line(self, label: str, value: str, inner_width: int) -> str:
        label_text = f"{label}:"
        available = inner_width - 2 - 15
        value = self._truncate_middle(str(value), max(available, 1))
        content = f" {label_text:<14} {value}"
        return _structural_bordered_line("│", f"{content:<{inner_width}}", "│")

    def _print_leading_blank_if_needed(self) -> None:
        # Tool results are one-line event blocks; separate the next visible
        # block here instead of teaching the spinner about layout.
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
        line = _styled_text(line, *(style, DIM_STYLE if dim else ""))
        print(line)
        self._needs_leading_blank = True

    def _run_event_line(self, line: str) -> str:
        return self._indented_run_line(line, RUN_EVENT_INDENT)

    def _run_detail_line(self, line: str) -> str:
        return self._indented_run_line(line, RUN_DETAIL_INDENT)

    def _indented_run_line(self, line: str, indent: str) -> str:
        if not line:
            return line
        return f"{indent}{line}"

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
            first_line = f"🦑 {lines[0]}"
            print(first_line)
            for line in lines[1:]:
                continuation = f"   {line}" if line else ""
                print(continuation)
            if trailing_blank:
                print()
            return

        for output_line in self._wrapped_display_lines(
            lines[0],
            initial_indent=f"{RUN_EVENT_INDENT}🦑 ",
            subsequent_indent=f"{RUN_EVENT_INDENT}   ",
        ):
            print(output_line)
        for line in lines[1:]:
            if not line:
                print()
                continue
            for output_line in self._wrapped_display_lines(
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
        print(_structural_text(f"┌{top_label}{'─' * max(width - len(top_label), 0)}"))
        for line in lines:
            print(_structural_prefix("│", f" {line}"))
        print(_structural_text(f"└{'─' * width}"))

    def _debug_action_lines(self, action: dict) -> list[str]:
        tool_name = action.get("tool", "")
        args = action.get("args", {})
        lines = [f"tool: {tool_name}"]

        if tool_name in {"read_file", "write_file", "apply_patch"} and args.get("path"):
            lines.append(f"path: {self._short_path(str(args['path']))}")
        if tool_name == "run_command" and args.get("command"):
            lines.append(f"command: {self._truncate_middle(str(args['command']), COMMAND_LABEL_MAX)}")
        if action.get("tool_call_id"):
            lines.append(f"tool_call_id: {action['tool_call_id']}")

        return lines

    def _print_debug_tool_result(self, action: dict, result: dict) -> None:
        if not self.debug:
            return

        print()
        self._debug_block("tool result", self._debug_tool_result_lines(action, result))

    def _debug_tool_result_lines(self, action: dict, result: dict) -> list[str]:
        tool_name = action.get("tool", "")
        lines = [
            f"ok: {self._debug_value(result.get('ok', False))}",
            f"tool: {tool_name}",
        ]
        args = action.get("args", {})

        if tool_name == "read_file":
            if args.get("path"):
                lines.append(f"path: {self._short_path(str(args['path']))}")
            if not result.get("ok", False) and result.get("error"):
                lines.append(f"error: {result['error']}")
                return lines
            lines.extend(
                [
                    "chars: "
                    f"{result.get('content_returned_chars', 0)} / "
                    f"{result.get('content_original_chars', 0)}",
                    "lines: "
                    f"{result.get('start_line', '')}-{result.get('end_line', '')} / "
                    f"{result.get('total_lines', '')}",
                    f"truncated: {self._debug_value(result.get('content_truncated', False))}",
                ]
            )
            return lines

        if tool_name == "write_file":
            if args.get("path"):
                lines.append(f"path: {self._short_path(str(args['path']))}")
            if not result.get("ok", False) and result.get("error"):
                lines.append(f"error: {result['error']}")
                return lines
            lines.extend(
                [
                    f"characters_written: {result.get('characters_written', 0)}",
                    f"summary: {result.get('summary', '')}",
                ]
            )
            return lines

        if tool_name == "apply_patch":
            if args.get("path"):
                lines.append(f"path: {self._short_path(str(args['path']))}")
            if not result.get("ok", False) and result.get("error"):
                lines.append(f"error: {result['error']}")
                return lines
            lines.extend(
                [
                    f"replacements: {result.get('replacements', 0)}",
                    f"chars: {result.get('chars_before', 0)} -> {result.get('chars_after', 0)}",
                ]
            )
            return lines

        if tool_name == "run_command":
            lines.extend(
                [
                    f"returncode: {result.get('returncode', '')}",
                    f"timed_out: {self._debug_value(result.get('timed_out', False))}",
                    "chars: "
                    f"{result.get('output_returned_chars', 0)} / "
                    f"{result.get('output_original_chars', 0)}",
                    f"truncated: {self._debug_value(result.get('output_truncated', False))}",
                ]
            )
            summary = self._pytest_summary(result.get("output", ""))
            if summary:
                lines.append(f"pytest: {summary}")
            return lines

        if result.get("error"):
            lines.append(f"error: {result['error']}")
        return lines

    def _debug_value(self, value: object) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    def _print_final_summary(self, content: str) -> None:
        formatted = self._format_final_summary(content)
        if not formatted:
            return

        self._print_leading_blank_if_needed()
        print(_structural_text(FINAL_REPORT_DIVIDER))
        print("🦑 Report:")
        print()
        print(formatted)
        self._needs_leading_blank = False

    def _run_command_result(self, action: dict, result: dict) -> None:
        if result.get("timed_out"):
            self._print_visible_line("⌛️ Command timed out", style=SOFT_YELLOW_STYLE)
            return

        summary = self._pytest_summary(result.get("output", ""))
        if summary:
            if "failed" in summary:
                self._print_visible_line(
                    f"🔎 Tests need review: {summary}",
                    style=SOFT_YELLOW_STYLE,
                )
            else:
                self._print_visible_line(
                    f"🧪 Tests passed: {summary}",
                    style=SOFT_GREEN_STYLE,
                )
            return

        if not result.get("ok", False):
            self._print_visible_line(
                self._action_label(action, "failure"),
                style=SOFT_RED_STYLE,
            )
            return

        self._print_visible_line(self._action_label(action, "success"), dim=True)

    def _format_final_summary(self, content: str) -> str:
        formatted_lines: list[str] = []
        previous_rendered_bullet = False
        for line in content.splitlines():
            rendered_lines = self._markdown_display_lines(line)
            is_rendered_bullet = self._is_rendered_unordered_bullet_block(rendered_lines)
            if is_rendered_bullet and previous_rendered_bullet:
                formatted_lines.append("")
            formatted_lines.extend(rendered_lines)
            previous_rendered_bullet = is_rendered_bullet

        return "\n".join(formatted_lines).strip("\n")

    def _is_rendered_unordered_bullet_block(self, lines: list[str]) -> bool:
        return bool(lines) and lines[0].startswith(f"{FINAL_SUMMARY_INDENT}• ")

    def _markdown_display_lines(self, line: str) -> list[str]:
        heading_match = re.match(r"^\s{0,3}(#{2,3})\s+(.+?)\s*#*\s*$", line)
        if heading_match:
            level, heading = heading_match.groups()
            indent = FINAL_SUMMARY_INDENT if level == "##" else f"{FINAL_SUMMARY_INDENT}  "
            return [f"{indent}{_styled_text(heading, BOLD_STYLE)}"]

        rendered = self._render_inline_markdown(line)
        stripped = rendered.lstrip()
        unordered_bullet_match = re.match(r"^([-*+])\s+(.+)$", stripped)
        if unordered_bullet_match:
            rendered = f"• {unordered_bullet_match.group(2)}"
            return self._wrapped_display_lines(
                rendered,
                initial_indent=FINAL_SUMMARY_INDENT,
                subsequent_indent=f"{FINAL_SUMMARY_INDENT}  ",
            )

        numbered_bullet_match = re.match(r"^(\d+\.\s+)(.+)$", stripped)
        if numbered_bullet_match:
            marker = numbered_bullet_match.group(1)
            rendered = f"{marker}{numbered_bullet_match.group(2)}"
            return self._wrapped_display_lines(
                rendered,
                initial_indent=FINAL_SUMMARY_INDENT,
                subsequent_indent=f"{FINAL_SUMMARY_INDENT}{' ' * len(marker)}",
            )

        return self._wrapped_display_lines(
            stripped,
            initial_indent=FINAL_SUMMARY_INDENT,
            subsequent_indent=FINAL_SUMMARY_INDENT,
        )

    def _render_inline_markdown(self, text: str) -> str:
        if "**" not in text or not sys.stdout.isatty():
            return text

        parts = re.split(r"(\*\*[^*\n]+\*\*)", text)
        rendered_parts: list[str] = []
        for part in parts:
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                rendered_parts.append(_styled_text(part[2:-2], BOLD_STYLE))
                continue
            rendered_parts.append(part)
        return "".join(rendered_parts)

    def _wrapped_display_lines(
        self,
        text: str,
        initial_indent: str,
        subsequent_indent: str,
    ) -> list[str]:
        if not text:
            return [""]

        wrap_width = min(
            DISPLAY_WRAP_WIDTH,
            shutil.get_terminal_size(fallback=(DISPLAY_WRAP_WIDTH, 24)).columns,
        )
        return textwrap.wrap(
            text,
            width=max(wrap_width, 1),
            initial_indent=initial_indent,
            subsequent_indent=subsequent_indent,
            break_long_words=False,
            break_on_hyphens=False,
        )

    def _pytest_summary(self, output: str) -> str:
        matches = re.findall(
            r"\d+\s+failed,\s+\d+\s+passed|\d+\s+passed|\d+\s+failed",
            output,
        )
        return matches[-1] if matches else ""

    def _print_file_list(self, title: str, paths: set[str]) -> None:
        print(f"  {title}")
        if not paths:
            print("    none")
            return

        for path in sorted(paths):
            display_path = path if self.debug else _file_link(path)
            print(f"    {display_path}")

    def _short_path(self, path: str) -> str:
        if not path:
            return ""

        raw_path = str(path)
        try:
            path_obj = Path(raw_path).expanduser()
            if path_obj.is_absolute():
                display_path = str(path_obj.resolve().relative_to(self._display_root()))
            else:
                display_path = raw_path
        except (OSError, ValueError):
            display_path = raw_path

        if len(display_path) <= PATH_LABEL_MAX:
            return display_path

        parts = Path(display_path).parts
        if Path(display_path).is_absolute() and len(parts) >= 3:
            return self._truncate_middle("/".join(("…", *parts[-2:])), PATH_LABEL_MAX)

        return self._truncate_middle(display_path, PATH_LABEL_MAX)

    def _display_root(self) -> Path:
        if self.startup_info is not None:
            return self.startup_info.directory.resolve()
        return Path.cwd().resolve()

    def _truncate_middle(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value

        if max_length <= 1:
            return "…"[:max_length]

        keep = max_length - 1
        left = keep // 2
        right = keep - left
        return f"{value[:left]}…{value[-right:]}"

    def _command_label(
        self,
        command: str,
        phase: str,
        max_length: int = COMMAND_LABEL_MAX,
    ) -> str:
        command = str(command).strip()
        tokens = self._command_tokens(command)
        first = Path(tokens[0]).name if tokens else ""

        if self._is_pytest_command(tokens):
            pytest_command = (
                "python -m pytest" if Path(tokens[0]).name.startswith("python") else "pytest"
            )
            verb = "Ran" if phase == "success" else "Run"
            if phase == "failure":
                return f"❌ Command failed: {pytest_command}"
            return f"💿 {verb}: {pytest_command}"

        if first in {"find", "rg", "grep"}:
            return "🔎 Searched files" if phase == "success" else "🔎 Search files"

        if first == "ls":
            return "🔎 Listed files" if phase == "success" else "🔎 List files"

        node_check = self._node_check_label(tokens)
        if node_check:
            verb = "Ran" if phase == "success" else "Run"
            if phase == "failure":
                return f"❌ Command failed: {node_check}"
            return f"💿 {verb}: {node_check}"

        command = self._truncate_middle(command, max_length)
        if phase == "success":
            return f"💿 Ran: {command}"
        if phase == "failure":
            return f"❌ Command failed: {command}"
        return f"💿 Run: {command}"

    def _command_tokens(self, command: str) -> list[str]:
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()

    def _is_pytest_command(self, tokens: list[str]) -> bool:
        if not tokens:
            return False

        first = Path(tokens[0]).name
        return first == "pytest" or tokens[:3] in (
            ["python", "-m", "pytest"],
            ["python3", "-m", "pytest"],
        )

    def _node_check_label(self, tokens: list[str]) -> str:
        if len(tokens) < 3:
            return ""

        if Path(tokens[0]).name != "node" or tokens[1] != "--check":
            return ""

        return f"node --check {self._short_path(tokens[2])}"

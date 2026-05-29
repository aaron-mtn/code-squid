"""Small terminal display layer for Code Squid."""

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import sys

from core.approval import USER_DENIED_TOOL_ACTION
from ui.spinner import TerminalSpinner


PATH_LABEL_MAX = 56
COMMAND_LABEL_MAX = 80
APPROVAL_COMMAND_LABEL_MAX = 120
CODE_SQUID_BANNER = """\

 ██████╗ ██████╗ ██████╗ ███████╗    ███████╗ ██████╗ ██╗   ██╗██╗██████╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝    ██╔════╝██╔═══██╗██║   ██║██║██╔══██╗
██║     ██║   ██║██║  ██║█████╗      ███████╗██║   ██║██║   ██║██║██║  ██║
██║     ██║   ██║██║  ██║██╔══╝      ╚════██║██║▄▄ ██║██║   ██║██║██║  ██║
╚██████╗╚██████╔╝██████╔╝███████╗    ███████║╚██████╔╝╚██████╔╝██║██████╔╝
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝    ╚══════╝ ╚══▀▀═╝  ╚═════╝ ╚═╝╚═════╝

                 🦑 A small coding agent with tentacles."""
RUN_STARTED_DIVIDER = "╰─ starting run ─────────────────────────────────────────────"
FINAL_REPORT_DIVIDER = "────────────────────────────────────────"
RUN_EVENT_INDENT = "  "
STARTUP_PANEL_WIDTH = 76
STARTUP_CONTROLS = "Enter send • Alt+Enter newline • Ctrl+C stop"
INPUT_IDENTITY_LINE = "@code-squid 🦑"
INPUT_PROMPT_PREFIX = "› "
DIM_STYLE = "\033[2m"
RESET_STYLE = "\033[0m"


@dataclass(frozen=True)
class StartupInfo:
    directory: Path
    provider: str
    model: str
    approval_mode: str


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
        self._spinner = _spinner if _spinner is not None else TerminalSpinner(enabled=not debug)
        self._needs_leading_blank = False

    def start(self) -> None:
        self._stop_spinner()
        self._print_startup_banner()
        self._needs_leading_blank = False

    def run_started(self) -> None:
        self._stop_spinner()
        print()
        print(RUN_STARTED_DIVIDER)
        print()
        self._needs_leading_blank = False

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

        if "TASK COMPLETE" in content:
            self._print_final_summary(content)
            return

        self._print_leading_blank_if_needed()
        self._print_assistant_narration(content, trailing_blank=False)
        self._needs_leading_blank = False

    def action_started(self, action: dict) -> None:
        self._stop_spinner()
        if not self.debug:
            return

        if action.get("tool") in {"read_file", "write_file"}:
            return

        print(self._action_text(action))

    def approve_action(self, action: dict) -> bool:
        self._stop_spinner()
        self._print_leading_blank_if_needed()
        print("Approve tool action?")
        print(self._action_text(action))
        self._needs_leading_blank = True
        response = input("[y/N] ")
        return response.strip().lower() in {"y", "yes"}

    def _action_text(self, action: dict) -> str:
        return self._action_label(action, "start")

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
            self._print_visible_line("🚫 Action denied")
            self._print_debug_tool_result(action, result)
            return

        tool_name = action.get("tool")
        if tool_name == "run_command":
            self._run_command_result(action, result)
            self._print_debug_tool_result(action, result)
            return

        if result.get("ok", False):
            if tool_name in {"read_file", "write_file"}:
                self._print_visible_line(self._action_label(action, "success"), dim=True)
            self._print_debug_tool_result(action, result)
            return

        error = result.get("error", "unknown error")
        if tool_name in {"read_file", "write_file"}:
            self._print_visible_line(f"{self._action_label(action, 'failure')} - {error}")
            self._print_debug_tool_result(action, result)
            return

        self._print_visible_line(f"❌ {tool_name} failed: {error}")
        self._print_debug_tool_result(action, result)

    def reply_rejected(self, reason: str) -> None:
        self._stop_spinner()
        self._print_visible_line(
            self._reply_rejected_line(reason),
            dim=not self.debug and reason == "non_final_no_tool_reply",
        )

    def repeated_invalid_replies(self, reason: str, count: int) -> None:
        self._stop_spinner()
        self._print_visible_line(f"⚠️ Stopping after {count} invalid replies: {reason}")

    def step_limit_reached(self, max_tool_steps: int) -> None:
        self._stop_spinner()
        self._print_visible_line(f"⚠️ Stopping after reaching tool step limit: {max_tool_steps}")

    def interrupted(self) -> None:
        self._stop_spinner()
        self._interrupted = True
        self._print_visible_line("⏹️ Interrupted")

    def model_request_failed(self, log_path: Path) -> None:
        self._stop_spinner()
        # Normal CLI users need a clear failure and the saved details path,
        # not a raw traceback from whichever provider happened to fail.
        self._print_leading_blank_if_needed()
        print("🚫 Model request failed")
        print()
        print("Code Squid could not get a response from the configured model provider.")
        print(f"Details saved to: {log_path}")

    def loop_finished(self, session, run_result=None) -> None:
        self._stop_spinner()
        if self._needs_leading_blank:
            self._print_leading_blank_if_needed()
        else:
            print()

        print(FINAL_REPORT_DIVIDER)
        self._print_file_list("📖 Files read", session.files_read)
        print()
        self._print_file_list("📝 Files written", session.files_written)
        status = getattr(run_result, "status", None)
        if status is None:
            status = "interrupted" if self._interrupted else "complete"

        print()
        if status == "failed":
            print("❌ Session failed")
        elif status == "interrupted":
            print("⚠️ Session interrupted")
        else:
            print("✅ Session complete")

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
                top,
                *(self._startup_info_line(label, value, inner_width) for label, value in lines),
                bottom,
            ]
        )

    def _startup_info_line(self, label: str, value: str, inner_width: int) -> str:
        label_text = f"{label}:"
        available = inner_width - 2 - 15
        value = self._truncate_middle(str(value), max(available, 1))
        content = f" {label_text:<14} {value}"
        return f"│{content:<{inner_width}}│"

    def _print_leading_blank_if_needed(self) -> None:
        # Tool results are one-line event blocks; separate the next visible
        # block here instead of teaching the spinner about layout.
        if self._needs_leading_blank:
            print()
            self._needs_leading_blank = False

    def _print_visible_line(self, line: str, dim: bool = False) -> None:
        self._print_leading_blank_if_needed()
        if not self.debug:
            line = self._run_event_line(line)
        if dim and sys.stdout.isatty():
            line = f"{DIM_STYLE}{line}{RESET_STYLE}"
        print(line)
        self._needs_leading_blank = True

    def _run_event_line(self, line: str) -> str:
        if not line:
            return line
        return f"{RUN_EVENT_INDENT}{line}"

    def _reply_rejected_line(self, reason: str) -> str:
        if self.debug:
            return f"⚠️ Reply rejected: {reason}"

        messages = {
            "non_final_no_tool_reply": "↪ Nudging model to choose an action…",
            "non_final_wrong_tool_count": "⚠️ Reply rejected: expected exactly one tool call.",
            "malformed_tool_call": "⚠️ Reply rejected: could not read the requested tool call.",
            "final_with_tool_call": "⚠️ Reply rejected: final reply cannot include a tool call.",
            "final_missing_required_sections": "⚠️ Reply rejected: final reply is missing required sections.",
        }
        return messages.get(reason, "⚠️ Reply rejected: invalid assistant reply.")

    def _print_assistant_narration(self, content: str, trailing_blank: bool = True) -> None:
        lines = content.splitlines() or [""]
        first_line = f"🦑 {lines[0]}"
        print(self._run_event_line(first_line) if not self.debug else first_line)
        for line in lines[1:]:
            continuation = f"   {line}" if line else ""
            print(self._run_event_line(continuation) if not self.debug else continuation)
        if trailing_blank:
            print()

    def _debug_block(self, title: str, lines: list[str]) -> None:
        width = 47
        top_label = f"─ {title} "
        print(f"┌{top_label}{'─' * max(width - len(top_label), 0)}")
        for line in lines:
            print(f"│ {line}")
        print(f"└{'─' * width}")

    def _debug_action_lines(self, action: dict) -> list[str]:
        tool_name = action.get("tool", "")
        args = action.get("args", {})
        lines = [f"tool: {tool_name}"]

        if tool_name in {"read_file", "write_file"} and args.get("path"):
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
        print(FINAL_REPORT_DIVIDER)
        print("📋 Final summary")
        print()
        print(formatted)
        self._needs_leading_blank = False

    def _run_command_result(self, action: dict, result: dict) -> None:
        if result.get("timed_out"):
            self._print_visible_line("⌛️ Command timed out")
            return

        summary = self._pytest_summary(result.get("output", ""))
        if summary:
            if "failed" in summary:
                self._print_visible_line(f"🔎 Tests need review: {summary}")
            else:
                self._print_visible_line(f"🧪 Tests passed: {summary}")
            return

        if not result.get("ok", False):
            self._print_visible_line(self._action_label(action, "failure"))
            return

        self._print_visible_line(self._action_label(action, "success"), dim=True)

    def _format_final_summary(self, content: str) -> str:
        summary_prefixes = (
            "Files changed:",
            "What changed:",
            "Verification:",
            "Remaining risks / notes:",
        )
        formatted_lines: list[str] = []
        found_summary = False

        for line in content.splitlines():
            # TASK COMPLETE is a runtime marker used for final validation. Hide
            # it only from normal display; debug mode still prints raw content.
            if "TASK COMPLETE" in line:
                line = line.replace("TASK COMPLETE", "")
                if not line.strip():
                    continue
            stripped = line.strip()

            should_space = stripped.startswith(summary_prefixes)
            if not found_summary:
                if not should_space:
                    continue
                found_summary = True

            if should_space and formatted_lines and formatted_lines[-1] != "":
                formatted_lines.append("")

            formatted_lines.append(line)

        return "\n".join(formatted_lines).strip()

    def _pytest_summary(self, output: str) -> str:
        matches = re.findall(
            r"\d+\s+failed,\s+\d+\s+passed|\d+\s+passed|\d+\s+failed",
            output,
        )
        return matches[-1] if matches else ""

    def _print_file_list(self, title: str, paths: set[str]) -> None:
        print(f"{title}:")
        if not paths:
            print("  - none")
            return

        for path in sorted(paths):
            print(f"  - {path}")

    def _short_path(self, path: str) -> str:
        if not path:
            return ""

        raw_path = str(path)
        try:
            path_obj = Path(raw_path).expanduser()
            if path_obj.is_absolute():
                display_path = str(path_obj.resolve().relative_to(Path.cwd().resolve()))
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

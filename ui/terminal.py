"""Small terminal display layer for Code Squid."""

from pathlib import Path
import re
import shlex

from core.approval import USER_DENIED_TOOL_ACTION
from ui.spinner import TerminalSpinner


PATH_LABEL_MAX = 56
COMMAND_LABEL_MAX = 80
APPROVAL_COMMAND_LABEL_MAX = 120


class TerminalDisplay:
    """Owns terminal formatting for the agent loop."""

    def __init__(self, debug: bool = False, _spinner: TerminalSpinner | None = None) -> None:
        self.debug = debug
        self._interrupted = False
        self._spinner = _spinner if _spinner is not None else TerminalSpinner(enabled=not debug)
        self._needs_leading_blank = False

    def start(self) -> None:
        self._stop_spinner()
        print("🦑 Code Squid")
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
            print("-> model replied")
            print(f"assistant: {content}")
            return

        if not content or self._is_boring_tool_narration(content):
            return

        formatted = self._format_assistant_content(content)
        if not formatted:
            return

        self._print_leading_blank_if_needed()
        print(formatted)
        print()
        self._needs_leading_blank = False

    def action_started(self, action: dict) -> None:
        self._stop_spinner()
        if not self.debug:
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
        if self.debug:
            print(f"tool result: {result}")

        if result.get("error") == USER_DENIED_TOOL_ACTION:
            self._print_visible_line("🚫 Action denied")
            return

        tool_name = action.get("tool")
        if tool_name == "run_command":
            self._run_command_result(action, result)
            return

        if result.get("ok", False):
            if tool_name in {"read_file", "write_file"}:
                self._print_visible_line(self._action_label(action, "success"))
            return

        error = result.get("error", "unknown error")
        if tool_name in {"read_file", "write_file"}:
            self._print_visible_line(f"{self._action_label(action, 'failure')} - {error}")
            return

        self._print_visible_line(f"❌ {tool_name} failed: {error}")

    def reply_rejected(self, reason: str) -> None:
        self._stop_spinner()
        self._print_visible_line(f"⚠️ Reply rejected: {reason}")

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

    def loop_finished(self, session) -> None:
        self._stop_spinner()
        if self._needs_leading_blank:
            self._print_leading_blank_if_needed()
        else:
            print()

        self._print_file_list("📖 Files read", session.files_read)
        print()
        self._print_file_list("📝 Files written", session.files_written)
        if not self._interrupted:
            print()
            print("✅ Session complete")

        if not self.debug:
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
        print(f"actions: {reply.get('actions', [])}")
        if reply.get("format_error"):
            print(f"format_error: {reply['format_error']}")

    def _stop_spinner(self) -> None:
        # The spinner is UI-only. Clear it before ordinary prints so redirected
        # logs and terminal output contain complete lines instead of animation.
        self._spinner.stop()

    def _print_leading_blank_if_needed(self) -> None:
        # Tool results are one-line event blocks; separate the next visible
        # block here instead of teaching the spinner about layout.
        if self._needs_leading_blank:
            print()
            self._needs_leading_blank = False

    def _print_visible_line(self, line: str) -> None:
        self._print_leading_blank_if_needed()
        print(line)
        self._needs_leading_blank = True

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

        self._print_visible_line(self._action_label(action, "success"))

    def _format_assistant_content(self, content: str) -> str:
        if "TASK COMPLETE" not in content:
            return content

        return self._format_final_summary(content)

    def _format_final_summary(self, content: str) -> str:
        summary_prefixes = (
            "Files changed:",
            "What changed:",
            "Verification run:",
            "Remaining risks:",
        )
        formatted_lines: list[str] = []

        for line in content.splitlines():
            stripped = line.strip()
            # TASK COMPLETE is a runtime marker used for final validation. Hide
            # it only from normal display; debug mode still prints raw content.
            if stripped == "TASK COMPLETE":
                continue

            should_space = stripped.startswith(summary_prefixes)

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
            display_path = path if self.debug else self._short_path(path)
            print(f"  - {display_path}")

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

    def _is_boring_tool_narration(self, content: str) -> bool:
        if content in {"Using read_file.", "Using write_file.", "Using run_command."}:
            return True

        return content.startswith("Using tools: ")

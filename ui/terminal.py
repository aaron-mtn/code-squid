"""Small terminal display layer for Code Squid."""

from pathlib import Path
import re

from core.approval import USER_DENIED_TOOL_ACTION


class TerminalDisplay:
    """Owns terminal formatting for the agent loop."""

    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        self._printed_working = False

    def start(self) -> None:
        print("🦑 Code Squid")
        print()

    def thinking(self) -> None:
        if not self.debug and self._printed_working:
            print()

        print("🦑 Working...")
        self._printed_working = True

    def assistant_message(self, content: str) -> None:
        content = content.strip()
        if self.debug:
            print("-> model replied")
            print(f"assistant: {content}")
            return

        if not content or self._is_boring_tool_narration(content):
            return

        print(self._format_assistant_content(content))
        print()

    def action_started(self, action: dict) -> None:
        print(self._action_text(action))

    def approve_action(self, action: dict) -> bool:
        print("Approve tool action?")
        print(self._action_text(action))
        response = input("[y/N] ")
        return response.strip().lower() in {"y", "yes"}

    def _action_text(self, action: dict) -> str:
        tool_name = action.get("tool", "")
        args = action.get("args", {})

        if tool_name == "read_file":
            return f"📖 Reading: {self._basename(args.get('path', ''))}"

        if tool_name == "write_file":
            return f"📝 Writing: {self._basename(args.get('path', ''))}"

        if tool_name == "run_command":
            return f"💿 Running: {args.get('command', '')}"

        return f"🔧 Running: {tool_name}"

    def tool_result(self, action: dict, result: dict) -> None:
        if self.debug:
            print(f"tool result: {result}")

        if result.get("error") == USER_DENIED_TOOL_ACTION:
            print("🚫 Action denied")
            return

        tool_name = action.get("tool")
        if tool_name == "run_command":
            self._run_command_result(result)
            return

        if result.get("ok", False):
            return

        error = result.get("error", "unknown error")
        print(f"❌ {tool_name} failed: {error}")

    def reply_rejected(self, reason: str) -> None:
        print(f"⚠️ Reply rejected: {reason}")

    def repeated_invalid_replies(self, reason: str, count: int) -> None:
        print(f"⚠️ Stopping after {count} invalid replies: {reason}")

    def step_limit_reached(self, max_tool_steps: int) -> None:
        print(f"⚠️ Stopping after reaching tool step limit: {max_tool_steps}")

    def loop_finished(self, session) -> None:
        print()

        self._print_file_list("📖 Files read", session.files_read)
        print()
        self._print_file_list("📝 Files written", session.files_written)

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

        print(f"actions: {reply.get('actions', [])}")
        if reply.get("format_error"):
            print(f"format_error: {reply['format_error']}")

    def _run_command_result(self, result: dict) -> None:
        if result.get("timed_out"):
            print("⌛️ Command timed out")
            return

        summary = self._pytest_summary(result.get("output", ""))
        if summary:
            if "failed" in summary:
                print(f"🔎 Tests need review: {summary}")
            else:
                print(f"🧪 Tests passed: {summary}")
            return

        if not result.get("ok", False):
            print("🕵️ Review output")
            return

        print("🟢 Success")

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
            "TASK COMPLETE",
        )
        formatted_lines: list[str] = []

        for line in content.splitlines():
            stripped = line.strip()
            should_space = stripped.startswith(summary_prefixes)

            if should_space and formatted_lines and formatted_lines[-1] != "":
                formatted_lines.append("")

            formatted_lines.append(line)

        return "\n".join(formatted_lines)

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
            display_path = path if self.debug else self._basename(path)
            print(f"  - {display_path}")

    def _basename(self, path: str) -> str:
        return Path(path).name if path else ""

    def _is_boring_tool_narration(self, content: str) -> bool:
        if content in {"Using read_file.", "Using write_file.", "Using run_command."}:
            return True

        return content.startswith("Using tools: ")

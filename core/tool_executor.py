# core/tool_executor.py

from pathlib import Path

from tools import TOOLS


class ToolExecutor:
    """Owns dispatching tool actions, normalizing raw tool outputs, and recording simple tool side effects; must not own prompts, policy, or provider logic."""

    # Store the repo root and session used during tool execution.
    # The executor uses repo_root to run tools in the correct place,
    # and uses session only for simple factual tracking like files read/written.
    def __init__(self, repo_root: Path, session) -> None:
        self.repo_root = repo_root
        self.session = session

    # Execute one tool action by looking up the tool and calling its execute function.
    # If the tool runs successfully, record any simple side effects in the session.
    def execute(self, action: dict) -> dict:
        tool_name = action["tool"]
        args = action.get("args", {})

        tool = TOOLS.get(tool_name)
        if tool is None:
            return {
                "ok": False,
                "tool": tool_name,
                "error": f"Unknown tool: {tool_name}",
            }

        try:
            result = tool["execute"](self.repo_root, **args)
            self._record_tool_effects(tool_name, result)
            return result
        except Exception as e:
            return {
                "ok": False,
                "tool": tool_name,
                "error": str(e),
            }

    # Record simple factual side effects of successful tool execution.
    # This is only for lightweight session tracking, not higher-level policy.
    def _record_tool_effects(self, tool_name: str, result: dict) -> None:
        if not result.get("ok"):
            return

        if tool_name == "read_file":
            path = result.get("path")
            if path:
                self.session.mark_file_read(path)

        if tool_name == "write_file":
            path = result.get("path")
            if path:
                self.session.mark_file_written(path)
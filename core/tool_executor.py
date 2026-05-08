# core/tool_executor.py

from pathlib import Path

from tools import TOOLS


class ToolExecutor:
    """Owns dispatching tool actions and normalizing raw tool outputs; must not own prompts, policy, or provider logic."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    # Execute one tool action by looking up the tool and calling its execute function.
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
            return tool["execute"](self.repo_root, **args)
        except Exception as e:
            return {
                "ok": False,
                "tool": tool_name,
                "error": str(e),
            }
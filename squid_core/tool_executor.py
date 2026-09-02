from pathlib import Path

from squid_core.platform_context import PlatformContext
from squid_core.workspace_boundary import workspace_boundary_reason
from tools import TOOLS


BUILTIN_RUN_COMMAND = TOOLS["run_command"]["execute"]


class ToolExecutor:
    """Owns tool dispatch, execution-time guards, normalized outputs, and simple tool side effects; must not own prompts, approval decisions, or provider logic."""

    # repo_root is the default working directory for run_command and the workspace
    # boundary for structured file-tool execution guards.
    # File tools still use absolute paths directly.
    def __init__(
        self,
        repo_root: Path,
        session,
        undo_store=None,
        allow_outside_workspace: bool = False,
        tools: dict | None = None,
        platform_context: PlatformContext | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.session = session
        self.undo_store = undo_store
        self.allow_outside_workspace = allow_outside_workspace
        self.tools = TOOLS if tools is None else tools
        self.platform_context = platform_context

    # Execute one tool action by looking up the tool and calling its execute function.
    # If the tool runs successfully, record any simple side effects in the session.
    def execute(self, action: dict) -> dict:
        tool_name = action["tool"]
        args = action.get("args", {})

        tool = self.tools.get(tool_name)
        if tool is None:
            return {
                "ok": False,
                "tool": tool_name,
                "error": f"Unknown tool: {tool_name}",
            }

        outside_workspace_approved = bool(action.get("outside_workspace_approved"))
        if not self.allow_outside_workspace and not outside_workspace_approved:
            constraint_reason = workspace_boundary_reason(action, self.repo_root)
            if constraint_reason is not None:
                return {
                    "ok": False,
                    "tool": tool_name,
                    "error": constraint_reason,
                }

        provisional_snapshot_path = None
        try:
            if self.undo_store is not None and tool_name in {"write_file", "apply_patch"}:
                path = args.get("path")
                if isinstance(path, str):
                    snapshot_already_existed = self.undo_store.has_snapshot(path)
                    self.undo_store.snapshot_file(path)
                    if not snapshot_already_existed:
                        provisional_snapshot_path = path

            execute_args = args
            if tool["execute"] is BUILTIN_RUN_COMMAND:
                execute_args = {**args, "platform_context": self.platform_context}

            result = tool["execute"](self.repo_root, **execute_args)
            if not result.get("ok") and provisional_snapshot_path is not None:
                self.undo_store.discard_snapshot_if_unchanged(provisional_snapshot_path)
            self._record_tool_effects(tool_name, result)
            return result
        except Exception as e:
            if provisional_snapshot_path is not None:
                try:
                    self.undo_store.discard_snapshot_if_unchanged(provisional_snapshot_path)
                except Exception:
                    pass
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

        if tool_name in {"write_file", "apply_patch"}:
            path = result.get("path")
            if path:
                self.session.mark_file_written(path)

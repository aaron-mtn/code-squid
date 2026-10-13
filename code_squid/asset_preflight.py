"""Allow built-in reads of the active session's private assets, never its writes."""

from pathlib import Path

from squid_core.safety.preflight import ActionPreflight, ActionPreflightDecision
from squid_core.tools.builtins import TOOLS


class SessionAssetPreflight(ActionPreflight):
    """Keep session images usable without trusting the entire application home."""

    def __init__(self, workspace_root: Path, session_dir: Path, tools: dict) -> None:
        super().__init__(workspace_root)
        self.session_dir = session_dir.resolve()
        self.tools = tools

    def check(
        self, action: dict, *, additional_approval_reason: str = "",
    ) -> ActionPreflightDecision:
        """Apply the normal policy except for reads of this session's asset tree."""
        args = action.get("args", {})
        path = args.get("path") if isinstance(args, dict) else None
        reader = self.tools.get("read_file", {})
        if (
            action.get("tool") == "read_file"
            and reader.get("execute") is TOOLS["read_file"]["execute"]
            and isinstance(path, str)
            and Path(path).is_absolute()
        ):
            assets = self.session_dir / "assets"
            target = Path(path).resolve()
            # Resolve the root as well as the target: a linked assets directory
            # must not turn this narrow exception into arbitrary external access.
            if assets.resolve() == assets and target.is_relative_to(assets):
                approval = (
                    {**action, "approval_reason": additional_approval_reason}
                    if additional_approval_reason else action
                )
                # Core's executor still guards external reads. This flag is
                # consumed only after the normal approval policy has accepted.
                return ActionPreflightDecision(
                    approval_action=approval,
                    execution_action={**action, "outside_workspace_approved": True},
                )
        return super().check(action, additional_approval_reason=additional_approval_reason)

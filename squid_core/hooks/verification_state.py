"""Track explicit successful verification independently of other Hook state."""

from __future__ import annotations

from typing import Any


_MUTATION_TOOLS = {"apply_patch", "write_file"}


class VerificationState:
    """Own whether explicit verification has passed since the last mutation."""

    def __init__(self, *, source: str = "runtime") -> None:
        # Hosts inspect Hook sources as configuration metadata.
        self.source = source
        self._verified_since_last_mutation = False

    @property
    def verified_since_last_mutation(self) -> bool:
        """Return the current run-local verification fact."""
        return self._verified_since_last_mutation

    def before_run(self, _ctx: Any) -> None:
        """Start each run without carrying verification from an earlier run."""
        self._verified_since_last_mutation = False

    def tool_result(self, ctx: Any) -> None:
        """Observe successful verification and structured file mutations."""
        tool_name = ctx.action.get("tool")
        result = ctx.result

        if result.get("ok") is not True:
            return

        if tool_name in _MUTATION_TOOLS:
            # Verification describes the current file state only until the next
            # successful structured mutation, regardless of which file changed.
            self._verified_since_last_mutation = False
        elif tool_name == "run_command" and result.get("verification") is True:
            self._verified_since_last_mutation = True

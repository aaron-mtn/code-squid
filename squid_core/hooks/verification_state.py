"""Track run-local implementation and explicit verification progress."""

from __future__ import annotations

from typing import Any


_MUTATION_TOOLS = {"apply_patch", "write_file"}


class VerificationState:
    """Own verification facts for the current in-memory implementation state."""

    def __init__(self, *, source: str = "runtime") -> None:
        # Hosts inspect Hook sources as configuration metadata.
        self.source = source
        self._verification_current = False
        self._verification_signatures: set[str] = set()
        self._post_verify_no_progress_count = 0
        # This one-result signal lets a separate policy Hook decide whether to
        # emit guidance without duplicating verification classification.
        self._last_result_was_duplicate_verification = False

    @property
    def verified_since_last_mutation(self) -> bool:
        """Return the current run-local verification fact."""
        return self._verification_current

    @property
    def verification_current(self) -> bool:
        """Return whether the latest implementation has successful verification."""
        return self._verification_current

    @property
    def verification_signatures(self) -> frozenset[str]:
        """Return successful verification commands for the current implementation."""
        return frozenset(self._verification_signatures)

    @property
    def post_verify_no_progress_count(self) -> int:
        """Return the current post-verification observation streak."""
        return self._post_verify_no_progress_count

    @property
    def last_result_was_duplicate_verification(self) -> bool:
        """Return whether the most recently observed result repeated verification."""
        return self._last_result_was_duplicate_verification

    def before_run(self, _ctx: Any) -> None:
        """Start each run without carrying verification from an earlier run."""
        self._reset_for_implementation_change()

    def record_post_verify_no_progress(self) -> int:
        """Record one observational action after current verification."""
        if self._verification_current:
            self._post_verify_no_progress_count += 1
        return self._post_verify_no_progress_count

    def reset_post_verify_no_progress(self) -> None:
        """Start a fresh post-verification observation streak."""
        self._post_verify_no_progress_count = 0

    def tool_result(self, ctx: Any) -> None:
        """Observe successful verification and structured file mutations."""
        tool_name = ctx.action.get("tool")
        result = ctx.result
        self._last_result_was_duplicate_verification = False

        if tool_name == "run_command" and result.get("verification") is True:
            self._observe_verification(ctx.action, result)
            return

        if tool_name in _MUTATION_TOOLS and result.get("ok") is True:
            # Verification describes the current file state only until the next
            # successful structured mutation, regardless of which file changed.
            self._reset_for_implementation_change()

    def _observe_verification(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Classify one explicit verification result without inferring breadth."""
        if result.get("ok") is not True:
            # A failing check is actionable information, but it means the
            # implementation is not currently in a successfully verified state.
            self._verification_current = False
            self.reset_post_verify_no_progress()
            return

        signature = _verification_signature(action, result)
        self._verification_current = True
        if signature in self._verification_signatures:
            self._last_result_was_duplicate_verification = True
            self.record_post_verify_no_progress()
            return

        self._verification_signatures.add(signature)
        self.reset_post_verify_no_progress()

    def _reset_for_implementation_change(self) -> None:
        """Invalidate every fact tied to the prior implementation contents."""
        self._verification_current = False
        self._verification_signatures.clear()
        self.reset_post_verify_no_progress()
        self._last_result_was_duplicate_verification = False


def _verification_signature(
    action: dict[str, Any],
    result: dict[str, Any],
) -> str:
    """Return a conservative normalized identity for one verification command."""
    command = result.get("command")
    if not isinstance(command, str):
        args = action.get("args")
        command = args.get("command") if isinstance(args, dict) else None
    if not isinstance(command, str):
        # Actual run_command results always include the command. Keeping a
        # stable fallback makes synthetic Hook contexts deterministic too.
        return ""
    return command.replace("\r\n", "\n").replace("\r", "\n").strip()

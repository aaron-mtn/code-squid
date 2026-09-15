"""Nudge continued observation after successful current verification."""

from __future__ import annotations

from typing import Any

from .runner import HookResponse


DEFAULT_POST_VERIFICATION_THRESHOLD = 3
POST_VERIFICATION_GUIDANCE = (
    "Verification has already succeeded for the current implementation, and the "
    "implementation has not changed since. You are continuing to inspect or repeat "
    "checks without making implementation or verification progress. Either identify "
    "a concrete unresolved requirement or problem that needs action, or finalize now. "
    "Do not continue checking solely for additional confidence."
)
_MUTATION_TOOLS = {"apply_patch", "write_file"}


class PostVerificationNudge:
    """Offer advisory guidance after a bounded post-verification idle streak."""

    def __init__(
        self,
        *,
        threshold: int = DEFAULT_POST_VERIFICATION_THRESHOLD,
        source: str = "runtime",
    ) -> None:
        if threshold < 1:
            raise ValueError("post-verification threshold must be at least 1")
        self.threshold = threshold
        self.source = source
        self._verification_current = False
        self._verification_signatures: set[str] = set()
        self._no_progress_count = 0

    def before_run(self, _ctx: Any) -> None:
        """Start each run without observations from an earlier run."""
        self._reset_for_implementation_change()

    def tool_result(self, ctx: Any) -> HookResponse | None:
        """Count supported no-progress actions and nudge at the threshold."""
        result = ctx.result
        tool_name = ctx.action.get("tool")

        if tool_name in _MUTATION_TOOLS and result.get("ok") is True:
            # Verification applies only to the implementation that was checked.
            self._reset_for_implementation_change()
            return None

        if tool_name == "run_command" and result.get("verification") is True:
            return self._observe_verification(ctx.action, result)

        if not self._verification_current:
            return None

        if tool_name == "read_file" and result.get("ok") is True:
            self._record_no_progress()
            # RepeatedReadNudge runs first and already provides more specific
            # guidance when it masks an unchanged range. Count that action but
            # do not stack post-verification guidance on the same result.
            if result.get("already_covered") is True:
                return None
            return self._nudge_if_ready()

        # Non-verification commands remain conservative until the Tool result
        # exposes a reliable generic workspace-mutation signal.
        return None

    def _observe_verification(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
    ) -> HookResponse | None:
        """Classify one explicitly marked verification result."""
        if result.get("ok") is not True:
            self._verification_current = False
            self._reset_no_progress()
            return None

        signature = _verification_signature(action, result)
        self._verification_current = True
        if signature not in self._verification_signatures:
            self._verification_signatures.add(signature)
            self._reset_no_progress()
            return None

        self._record_no_progress()
        return self._nudge_if_ready()

    def _nudge_if_ready(self) -> HookResponse | None:
        if self._no_progress_count < self.threshold:
            return None

        # Match the existing escalation style: guidance is transient and a
        # later nudge requires a complete fresh streak.
        self._reset_no_progress()
        return HookResponse(additional_context=POST_VERIFICATION_GUIDANCE)

    def _record_no_progress(self) -> None:
        """Record one action that did not advance implementation or verification."""
        self._no_progress_count += 1

    def _reset_no_progress(self) -> None:
        """Start a fresh post-verification no-progress streak."""
        self._no_progress_count = 0

    def _reset_for_implementation_change(self) -> None:
        """Invalidate every observation tied to the prior implementation."""
        self._verification_current = False
        self._verification_signatures.clear()
        self._reset_no_progress()


def _verification_signature(
    action: dict[str, Any],
    result: dict[str, Any],
) -> str:
    """Return the existing conservative identity for a verification command."""
    command = result.get("command")
    if not isinstance(command, str):
        args = action.get("args")
        command = args.get("command") if isinstance(args, dict) else None
    if not isinstance(command, str):
        # Real run_command results contain the command; this keeps synthetic
        # Hook contexts deterministic without inferring anything from text.
        return ""
    return command.replace("\r\n", "\n").replace("\r", "\n").strip()

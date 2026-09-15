"""Nudge continued observation after successful current verification."""

from __future__ import annotations

from typing import Any

from .runner import HookResponse
from .verification_state import VerificationState


DEFAULT_POST_VERIFICATION_THRESHOLD = 3
POST_VERIFICATION_GUIDANCE = (
    "Verification has already succeeded for the current implementation, and the "
    "implementation has not changed since. You are continuing to inspect or repeat "
    "checks without making implementation or verification progress. Either identify "
    "a concrete unresolved requirement or problem that needs action, or finalize now. "
    "Do not continue checking solely for additional confidence."
)


class PostVerificationNudge:
    """Offer advisory guidance after a bounded post-verification idle streak."""

    def __init__(
        self,
        verification_state: VerificationState,
        *,
        threshold: int = DEFAULT_POST_VERIFICATION_THRESHOLD,
        source: str = "runtime",
    ) -> None:
        if threshold < 1:
            raise ValueError("post-verification threshold must be at least 1")
        self.verification_state = verification_state
        self.threshold = threshold
        self.source = source

    def tool_result(self, ctx: Any) -> HookResponse | None:
        """Count supported no-progress actions and nudge at the threshold."""
        result = ctx.result
        tool_name = ctx.action.get("tool")

        if self.verification_state.last_result_was_duplicate_verification:
            return self._nudge_if_ready()

        if (
            tool_name == "read_file"
            and result.get("ok") is True
            and self.verification_state.verification_current
        ):
            # RepeatedReadNudge runs first and already provides more specific
            # guidance when it masks an unchanged range. Do not stack policies.
            if result.get("already_covered") is True:
                return None
            self.verification_state.record_post_verify_no_progress()
            return self._nudge_if_ready()

        # Non-verification commands remain conservative until the Tool result
        # exposes a reliable generic workspace-mutation signal.
        return None

    def _nudge_if_ready(self) -> HookResponse | None:
        if self.verification_state.post_verify_no_progress_count < self.threshold:
            return None

        # Match the existing escalation style: guidance is transient and a
        # later nudge requires a complete fresh streak.
        self.verification_state.reset_post_verify_no_progress()
        return HookResponse(additional_context=POST_VERIFICATION_GUIDANCE)

"""Nudge continued observation after successful current verification."""

from __future__ import annotations

from typing import Any

from .runner import HookResponse


DEFAULT_POST_VERIFICATION_THRESHOLD = 2
POST_VERIFICATION_GUIDANCE = (
    "Verification has already succeeded for the current implementation, and the "
    "implementation has not changed since. You are continuing to use tools after "
    "verification. If you found a concrete remaining problem, act on it now. Otherwise "
    "finalize. Do not continue inspecting or rerunning checks only for additional "
    "confidence."
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
        self._post_verification_action_count = 0

    def before_run(self, _ctx: Any) -> None:
        """Start each run without observations from an earlier run."""
        self._reset_for_implementation_change()

    def tool_result(self, ctx: Any) -> HookResponse | None:
        """Count successful actions after current verification and nudge."""
        result = ctx.result
        tool_name = ctx.action.get("tool")

        if tool_name in _MUTATION_TOOLS and result.get("ok") is True:
            # Verification applies only to the implementation that was checked.
            self._reset_for_implementation_change()
            return None

        if result.get("verification") is True:
            return self._observe_verification(result)

        if not self._verification_current or result.get("ok") is not True:
            return None

        self._record_post_verification_action()
        # RepeatedReadNudge runs first and already provides more specific
        # guidance when it masks an unchanged range. Count that action but
        # do not stack post-verification guidance on the same result.
        if result.get("already_covered") is True:
            return None
        return self._nudge_if_ready()

    def _observe_verification(
        self,
        result: dict[str, Any],
    ) -> HookResponse | None:
        """Classify one explicitly marked verification result."""
        if result.get("ok") is not True:
            self._verification_current = False
            self._reset_action_count()
            return None

        if self._verification_current:
            # Rechecking an unchanged implementation is continued activity,
            # regardless of the verification command text.
            self._record_post_verification_action()
            return self._nudge_if_ready()

        self._verification_current = True
        self._reset_action_count()
        return None

    def _nudge_if_ready(self) -> HookResponse | None:
        if self._post_verification_action_count < self.threshold:
            return None

        # Match the existing escalation style: guidance is transient and a
        # later nudge requires a complete fresh streak.
        self._reset_action_count()
        return HookResponse(additional_context=POST_VERIFICATION_GUIDANCE)

    def _record_post_verification_action(self) -> None:
        """Record one successful action after current verification."""
        self._post_verification_action_count += 1

    def _reset_action_count(self) -> None:
        """Start a fresh post-verification action window."""
        self._post_verification_action_count = 0

    def _reset_for_implementation_change(self) -> None:
        """Invalidate observations tied to the prior implementation."""
        self._verification_current = False
        self._reset_action_count()

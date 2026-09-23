"""Nudge continued observation after successful current verification."""

from __future__ import annotations

from typing import Any

from .runner import HookResponse, PromptContextBlock


DEFAULT_POST_VERIFICATION_THRESHOLD = 2
POST_VERIFICATION_GUIDANCE = (
    "HIGH PRIORITY: Identify concrete remaining work before using more tools.\n\n"
    "An explicitly marked verification succeeded, and no successful built-in "
    "file edit or failed explicit verification has been observed since. This "
    "does not establish that every task requirement or validation is complete.\n\n"
    "Continue only for an unfinished task requirement (including required "
    "documentation), a concrete issue, or another required validation step. "
    "If none remains, finalize the task now. Do not perform another read, search, "
    "or verification command merely for reassurance."
)
_MUTATION_TOOLS = {"apply_patch", "write_file"}
_CONTEXT_TITLE = "Post-Verification Guidance"


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
        self._guidance_ready = False

    def before_run(self, _ctx: Any) -> None:
        """Start each run without observations from an earlier run."""
        self._reset_for_implementation_change()

    def before_model_turn(self, _ctx: Any) -> HookResponse | None:
        """Render guidance from the state left by the complete Tool batch."""
        if not self._verification_current or not self._guidance_ready:
            return None

        # Preserve the existing one-turn cadence: another warning requires a
        # complete fresh threshold of post-verification activity.
        self._reset_action_count()
        return HookResponse(
            context_blocks=(
                PromptContextBlock(
                    _CONTEXT_TITLE,
                    POST_VERIFICATION_GUIDANCE,
                    self.source,
                ),
            )
        )

    def tool_result(self, ctx: Any) -> None:
        """Observe every result while deferring current-state guidance."""
        result = ctx.result
        tool_name = ctx.action.get("tool")

        if tool_name in _MUTATION_TOOLS and result.get("ok") is True:
            # Verification applies only to the implementation that was checked.
            self._reset_for_implementation_change()
            return None

        if result.get("verification") is True:
            self._observe_verification(result)
            return None

        if not self._verification_current or result.get("ok") is not True:
            return None

        self._record_post_verification_action()
        # RepeatedReadNudge runs first and already provides more specific
        # guidance when it masks an unchanged range. Count that action but
        # do not stack post-verification guidance on the same result.
        if result.get("already_covered") is True:
            return None
        self._mark_guidance_if_ready()
        return None

    def _observe_verification(
        self,
        result: dict[str, Any],
    ) -> None:
        """Classify one explicitly marked verification result."""
        if result.get("ok") is not True:
            self._verification_current = False
            self._reset_action_count()
            return None

        if self._verification_current:
            # Rechecking an unchanged implementation is continued activity,
            # regardless of the verification command text.
            self._record_post_verification_action()
            self._mark_guidance_if_ready()
            return None

        self._verification_current = True
        self._reset_action_count()
        return None

    def _mark_guidance_if_ready(self) -> None:
        """Remember that current state warrants guidance at the next boundary."""
        if self._post_verification_action_count >= self.threshold:
            self._guidance_ready = True

    def _record_post_verification_action(self) -> None:
        """Record one successful action after current verification."""
        self._post_verification_action_count += 1

    def _reset_action_count(self) -> None:
        """Start a fresh post-verification action window."""
        self._post_verification_action_count = 0
        self._guidance_ready = False

    def _reset_for_implementation_change(self) -> None:
        """Invalidate observations tied to the prior implementation."""
        self._verification_current = False
        self._reset_action_count()

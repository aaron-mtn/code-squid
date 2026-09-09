"""Conservative repeated-failure detection for transient model guidance."""

from __future__ import annotations

import json
from typing import Any

from .runner import HookResponse


DEFAULT_REPEATED_FAILURE_THRESHOLD = 3


class RepeatedFailureNudge:
    """Offer soft guidance after consecutive identical failed tool actions.

    The hook deliberately compares normalized actions exactly. It does not try
    to infer intent or semantic similarity: a changed action, a successful
    result, or a failure without a stable error category breaks the streak.
    """

    def __init__(
        self,
        guidance: str,
        *,
        threshold: int = DEFAULT_REPEATED_FAILURE_THRESHOLD,
        source: str = "runtime",
    ) -> None:
        if threshold < 2:
            raise ValueError("repeated-failure threshold must be at least 2")

        self.guidance = guidance
        self.threshold = threshold
        # Hosts inspect Hook sources as configuration metadata. It no longer
        # participates in prompt rendering now that nudges are plain guidance.
        self.source = source
        self._fingerprint: tuple[str, str, str] | None = None
        self._repeat_count = 0

    def before_run(self, _ctx) -> None:
        """Start each run with an empty, run-local repetition history."""
        self._reset()

    def tool_result(self, ctx) -> HookResponse | None:
        """Observe the final result that will be exposed to the model."""
        fingerprint = _failed_action_fingerprint(ctx.action, ctx.result)
        if fingerprint is None:
            self._reset()
            return

        if fingerprint == self._fingerprint:
            self._repeat_count += 1
        else:
            self._fingerprint = fingerprint
            self._repeat_count = 1

        if self._repeat_count >= self.threshold:
            # A nudge is an opportunity to recover, not a latched warning.
            # Another nudge requires a complete new threshold of failures.
            self._reset()
            return HookResponse(additional_context=self.guidance)

        return None

    def _reset(self) -> None:
        self._fingerprint = None
        self._repeat_count = 0


def _failed_action_fingerprint(
    action: dict[str, Any],
    result: dict[str, Any],
) -> tuple[str, str, str] | None:
    """Return an exact, compact fingerprint only for categorized failures."""
    if result.get("ok") is not False:
        return None

    tool_name = action.get("tool")
    error = result.get("error")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    if not isinstance(error, (str, int, float, bool)) or str(error) == "":
        return None

    args = action.get("args", {})
    try:
        args_fingerprint = json.dumps(
            args,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        # Tool actions are normally JSON data. An unusual non-JSON action is
        # skipped because an unstable representation could create false nudges.
        return None

    return tool_name, args_fingerprint, str(error)

"""Advisory guidance for excessive reading without a substantive mutation."""

from __future__ import annotations

from typing import Any

from .runner import HookResponse


DEFAULT_FIRST_NUDGE_READS = 3
DEFAULT_STRONG_NUDGE_READS = 5
TOO_MANY_READS_GUIDANCE = (
    "You have made several read actions without a substantive change in task state.\n\n"
    "Before inspecting more context, identify what specific new information is "
    "still required. If the information needed to continue is already available, "
    "continue the task instead of gathering more context."
)
TOO_MANY_READS_STRONG_GUIDANCE = (
    "HIGH PRIORITY: Stop inspecting source.\n\n"
    "You have already spent too many actions gathering context without making a "
    "substantive change. Do not perform another read or source-search unless a "
    "specific missing fact is required to make the next edit.\n\n"
    "Do not read for reassurance, completeness, reconfirmation, or to build a "
    "better mental model of the repository. Use the context already available and "
    "make the next safe change now."
)
_MUTATION_TOOLS = {"apply_patch", "write_file"}


class TooManyReadsNudge:
    """Advise after successful reads accumulate without a successful mutation.

    Command execution and all failed Tool results are deliberately neutral. The
    count is run-local but otherwise survives lifecycle events such as transcript
    compaction because it describes behavior, not model-visible source coverage.
    """

    def __init__(
        self,
        *,
        first_nudge_reads: int = DEFAULT_FIRST_NUDGE_READS,
        strong_nudge_reads: int = DEFAULT_STRONG_NUDGE_READS,
        source: str = "runtime",
    ) -> None:
        if first_nudge_reads < 1:
            raise ValueError("first read-nudge threshold must be at least 1")
        if strong_nudge_reads <= first_nudge_reads:
            raise ValueError(
                "strong read-nudge threshold must exceed the first threshold"
            )

        self.first_nudge_reads = first_nudge_reads
        self.strong_nudge_reads = strong_nudge_reads
        self.source = source
        self._read_count = 0

    def before_run(self, _ctx: Any) -> None:
        """Start each run with no behavioral history from an earlier run."""
        self._read_count = 0

    def tool_result(self, ctx: Any) -> HookResponse | None:
        """Observe successful built-in reads and substantive mutations."""
        tool_name = ctx.action.get("tool")
        if ctx.result.get("ok") is not True:
            return None

        if tool_name in _MUTATION_TOOLS:
            self._read_count = 0
            return None
        if tool_name != "read_file":
            return None

        self._read_count += 1
        if self._read_count >= self.strong_nudge_reads:
            return HookResponse(additional_context=TOO_MANY_READS_STRONG_GUIDANCE)
        if self._read_count == self.first_nudge_reads:
            return HookResponse(additional_context=TOO_MANY_READS_GUIDANCE)
        return None

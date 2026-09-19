"""Advisory guidance for excessive reading without a substantive mutation."""

from __future__ import annotations

from typing import Any

from .runner import HookResponse


DEFAULT_FIRST_NUDGE_READS = 3
DEFAULT_STRONG_NUDGE_READS = 5
DEFAULT_FIRST_NUDGE_LINES = 1_500
DEFAULT_STRONG_NUDGE_LINES = 3_000
TOO_MANY_READS_GUIDANCE = (
    "You have already spent several read actions or gathered substantial source "
    "without a substantive change in task state.\n\n"
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
    """Advise after successful read actions or source volume accumulates.

    Command execution and all failed Tool results are deliberately neutral. The
    counters are run-local but otherwise survive lifecycle events such as
    transcript compaction because they describe behavior, not model-visible
    source coverage.
    """

    def __init__(
        self,
        *,
        first_nudge_reads: int = DEFAULT_FIRST_NUDGE_READS,
        strong_nudge_reads: int = DEFAULT_STRONG_NUDGE_READS,
        first_nudge_lines: int = DEFAULT_FIRST_NUDGE_LINES,
        strong_nudge_lines: int = DEFAULT_STRONG_NUDGE_LINES,
        source: str = "runtime",
    ) -> None:
        if first_nudge_reads < 1:
            raise ValueError("first read-nudge threshold must be at least 1")
        if strong_nudge_reads <= first_nudge_reads:
            raise ValueError(
                "strong read-nudge threshold must exceed the first threshold"
            )
        if first_nudge_lines < 1:
            raise ValueError("first read-volume threshold must be at least 1")
        if strong_nudge_lines <= first_nudge_lines:
            raise ValueError(
                "strong read-volume threshold must exceed the first threshold"
            )

        self.first_nudge_reads = first_nudge_reads
        self.strong_nudge_reads = strong_nudge_reads
        self.first_nudge_lines = first_nudge_lines
        self.strong_nudge_lines = strong_nudge_lines
        self.source = source
        self._read_count = 0
        self._returned_lines = 0
        self._first_nudge_emitted = False

    def before_run(self, _ctx: Any) -> None:
        """Start each run with no behavioral history from an earlier run."""
        self._read_count = 0
        self._returned_lines = 0
        self._first_nudge_emitted = False

    def tool_result(self, ctx: Any) -> HookResponse | None:
        """Observe successful built-in reads and substantive mutations."""
        tool_name = ctx.action.get("tool")
        if ctx.result.get("ok") is not True:
            return None

        if tool_name in _MUTATION_TOOLS:
            self._read_count = 0
            self._returned_lines = 0
            self._first_nudge_emitted = False
            return None
        if tool_name != "read_file":
            return None

        self._read_count += 1
        self._returned_lines += _returned_source_lines(ctx.result)
        if (
            self._read_count >= self.strong_nudge_reads
            or self._returned_lines >= self.strong_nudge_lines
        ):
            self._first_nudge_emitted = True
            return HookResponse(additional_context=TOO_MANY_READS_STRONG_GUIDANCE)
        if not self._first_nudge_emitted and (
            self._read_count >= self.first_nudge_reads
            or self._returned_lines >= self.first_nudge_lines
        ):
            self._first_nudge_emitted = True
            return HookResponse(additional_context=TOO_MANY_READS_GUIDANCE)
        return None


def _returned_source_lines(result: dict[str, Any]) -> int:
    """Measure source left visible by earlier Hooks without tracking coverage here."""
    if result.get("already_covered") is True:
        return 0

    ranges = result.get("returned_line_ranges")
    if isinstance(ranges, list):
        total = 0
        for item in ranges:
            if not isinstance(item, dict):
                return 0
            start = item.get("start_line")
            end = item.get("end_line")
            if not _valid_line_range(start, end):
                return 0
            total += end - start + 1
        return total

    start = result.get("start_line")
    end = result.get("end_line")
    return end - start + 1 if _valid_line_range(start, end) else 0


def _valid_line_range(start: Any, end: Any) -> bool:
    """Accept only ordinary positive inclusive line bounds."""
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and start >= 1
        and end >= start
    )

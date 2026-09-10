"""Detect repeated reads of substantially overlapping unchanged file ranges."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .runner import HookResponse


DEFAULT_REPEATED_READ_THRESHOLD = 2
SUBSTANTIAL_OVERLAP_RATIO = 0.7

_MAX_TRACKED_FILES = 100
_MAX_RANGES_PER_FILE = 64
_MUTATION_TOOLS = {"apply_patch", "write_file"}
_GUIDANCE = (
    "You recently inspected most of this unchanged file range. Reuse the existing "
    "result unless you need exact current text for an edit or a specific unresolved "
    "detail."
)


class RepeatedReadNudge:
    """Offer transient guidance after repeated overlapping reads of one file.

    Coverage comes only from successful ``read_file`` result metadata. Successful
    built-in mutations invalidate the affected file, so no filesystem timestamp
    checks are needed.
    """

    def __init__(
        self,
        *,
        threshold: int = DEFAULT_REPEATED_READ_THRESHOLD,
        source: str = "runtime",
    ) -> None:
        if threshold < 2:
            raise ValueError("repeated-read threshold must be at least 2")

        self.threshold = threshold
        # Hosts inspect Hook sources as configuration metadata.
        self.source = source
        self._coverage: dict[str, list[tuple[int, int]]] = {}
        self._redundant_counts: dict[str, int] = {}

    def before_run(self, _ctx) -> None:
        """Discard all observations from the preceding run."""
        self._coverage.clear()
        self._redundant_counts.clear()

    def tool_result(self, ctx) -> HookResponse | None:
        """Observe one final tool result and optionally emit an advisory nudge."""
        tool_name = ctx.action.get("tool")
        result = ctx.result

        if tool_name == "read_file":
            return self._observe_read(ctx.action, result)

        if tool_name in _MUTATION_TOOLS and result.get("ok") is True:
            path = _result_path(ctx.action, result)
            if path is not None:
                self._coverage.pop(path, None)
                self._redundant_counts.pop(path, None)

        return None

    def _observe_read(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
    ) -> HookResponse | None:
        if result.get("ok") is not True:
            return None

        path = _result_path(action, result)
        returned_ranges = _returned_ranges(result)
        if path is None or not returned_ranges:
            return None

        previous_coverage = self._coverage.get(path, ())
        is_redundant = (
            _overlap_ratio(previous_coverage, returned_ranges)
            >= SUBSTANTIAL_OVERLAP_RATIO
        )

        # Classify before recording so a read cannot overlap with itself. The
        # dedicated range list keeps truncated head and tail coverage separate.
        self._record_coverage(path, returned_ranges)

        if not is_redundant:
            self._redundant_counts.pop(path, None)
            return None

        count = self._redundant_counts.get(path, 0) + 1
        if count < self.threshold:
            self._redundant_counts[path] = count
            return None

        # Guidance is one-request-only; a later warning needs a fresh streak.
        self._redundant_counts.pop(path, None)
        return HookResponse(additional_context=_GUIDANCE)

    def _record_coverage(
        self,
        path: str,
        returned_ranges: list[tuple[int, int]],
    ) -> None:
        # Reinsertion keeps the dict ordered by recent use for simple eviction.
        existing = self._coverage.pop(path, [])
        if not existing and len(self._coverage) >= _MAX_TRACKED_FILES:
            oldest_path = next(iter(self._coverage))
            del self._coverage[oldest_path]
            self._redundant_counts.pop(oldest_path, None)
        self._coverage[path] = _merge_ranges(existing + returned_ranges)[
            -_MAX_RANGES_PER_FILE:
        ]


def _result_path(action: dict[str, Any], result: dict[str, Any]) -> str | None:
    """Return a normalized absolute identity from result or action metadata."""
    path = result.get("path")
    if not isinstance(path, str) or not path:
        args = action.get("args")
        path = args.get("path") if isinstance(args, dict) else None
    if not isinstance(path, str) or not path:
        return None
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _returned_ranges(result: dict[str, Any]) -> list[tuple[int, int]]:
    """Extract actual returned coverage, preferring the dedicated range list."""
    if "returned_line_ranges" in result:
        raw_ranges = result.get("returned_line_ranges")
        if not isinstance(raw_ranges, list):
            return []
        ranges = []
        for item in raw_ranges:
            if not isinstance(item, dict):
                continue
            line_range = _valid_range(item.get("start_line"), item.get("end_line"))
            if line_range is not None:
                ranges.append(line_range)
        return ranges

    fallback = _valid_range(result.get("start_line"), result.get("end_line"))
    return [fallback] if fallback is not None else []


def _valid_range(start: Any, end: Any) -> tuple[int, int] | None:
    if not _is_line_number(start) or not _is_line_number(end) or end < start:
        return None
    return start, end


def _is_line_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _overlap_ratio(
    previous: Sequence[tuple[int, int]],
    current: Sequence[tuple[int, int]],
) -> float:
    """Return the fraction of current returned lines covered by earlier reads."""
    merged_previous = _merge_ranges(previous)
    merged_current = _merge_ranges(current)
    current_lines = sum(end - start + 1 for start, end in merged_current)
    if current_lines == 0:
        return 0.0

    overlap_lines = 0
    for current_start, current_end in merged_current:
        for previous_start, previous_end in merged_previous:
            overlap_start = max(current_start, previous_start)
            overlap_end = min(current_end, previous_end)
            if overlap_start <= overlap_end:
                overlap_lines += overlap_end - overlap_start + 1
    return overlap_lines / current_lines


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge inclusive ranges so repeated coverage is never double-counted."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged

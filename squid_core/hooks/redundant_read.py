"""Detect repeated reads of substantially overlapping unchanged file ranges."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .runner import HookResponse


DEFAULT_REPEATED_READ_THRESHOLD = 1
SUBSTANTIAL_OVERLAP_RATIO = 0.7

_MAX_TRACKED_FILES = 100
_MAX_RANGES_PER_FILE = 64
_MUTATION_TOOLS = {"apply_patch", "write_file"}
_GUIDANCE = (
    "You recently inspected most of this unchanged file range. Reuse the existing "
    "result unless you need exact current text for an edit or a specific unresolved "
    "detail."
)
_ALREADY_COVERED_MESSAGE = (
    "You already read this unchanged section of the file. No file content is "
    "being returned again. Reuse the existing context, stop rereading this "
    "section, and take the next useful action."
)


class RepeatedReadNudge:
    """Escalate repeated overlapping reads of one unchanged file range.

    Coverage comes only from successful ``read_file`` result metadata. Successful
    built-in mutations adjust or invalidate the affected file, so no filesystem
    timestamp checks are needed.
    """

    def __init__(
        self,
        *,
        threshold: int = DEFAULT_REPEATED_READ_THRESHOLD,
        source: str = "runtime",
    ) -> None:
        if threshold < 1:
            raise ValueError("repeated-read threshold must be at least 1")

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
                self._redundant_counts.pop(path, None)
                if tool_name == "apply_patch":
                    self._adjust_coverage_for_patch(path, result)
                else:
                    self._coverage.pop(path, None)

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

        if count == self.threshold:
            # The first escalation remains advisory and leaves the successful
            # read intact. One more redundant read in this streak is masked.
            self._redundant_counts[path] = count
            return HookResponse(additional_context=_GUIDANCE)

        # After masking, require a fresh streak before escalating again.
        self._redundant_counts.pop(path, None)
        return HookResponse(updated_tool_output=_already_covered_result(action, result))

    def _adjust_coverage_for_patch(
        self,
        path: str,
        result: dict[str, Any],
    ) -> None:
        """Discard changed lines while preserving and shifting known coverage."""
        patch_range = _patch_range(result)
        if patch_range is None:
            # A successful mutation without trustworthy bounds cannot preserve
            # coverage safely, so fall back to whole-file invalidation.
            self._coverage.pop(path, None)
            return

        existing = self._coverage.get(path)
        if not existing:
            return

        start_line, end_line_before, end_line_after = patch_range
        delta = end_line_after - end_line_before
        adjusted: list[tuple[int, int]] = []
        for coverage_start, coverage_end in existing:
            if coverage_start < start_line:
                adjusted.append(
                    (coverage_start, min(coverage_end, start_line - 1))
                )
            if coverage_end > end_line_before:
                adjusted.append(
                    (
                        max(coverage_start, end_line_before + 1) + delta,
                        coverage_end + delta,
                    )
                )

        if adjusted:
            self._coverage[path] = _merge_ranges(adjusted)[-_MAX_RANGES_PER_FILE:]
        else:
            self._coverage.pop(path, None)

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


def _already_covered_result(
    action: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Build a successful model-facing result without duplicate file content."""
    masked = {
        "ok": True,
        "tool": "read_file",
        "path": result.get("path"),
        "already_covered": True,
        "message": _ALREADY_COVERED_MESSAGE,
    }

    args = action.get("args")
    if isinstance(args, dict):
        if masked["path"] is None:
            masked["path"] = args.get("path")
        for source_key, target_key in (
            ("start_line", "requested_start_line"),
            ("end_line", "requested_end_line"),
        ):
            if source_key in args:
                masked[target_key] = args[source_key]

    for key in ("start_line", "end_line", "returned_line_ranges"):
        if key in result:
            masked[key] = result[key]
    return masked


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


def _patch_range(result: dict[str, Any]) -> tuple[int, int, int] | None:
    """Extract inclusive before/after line bounds from a successful patch."""
    start = result.get("start_line")
    end_before = result.get("end_line_before")
    end_after = result.get("end_line_after")
    if (
        not _is_line_number(start)
        or not _is_line_number(end_before)
        or not _is_line_number(end_after)
        or end_before < start
        or end_after < start
    ):
        return None
    return start, end_before, end_after


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

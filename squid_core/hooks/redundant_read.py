"""Conservative detection of repeated reads of recently returned file lines."""

from __future__ import annotations

import os
from typing import Any, Sequence

from .runner import HookResponse


SMALL_READ_THRESHOLD = 100
REDUNDANT_READ_THRESHOLD = 2

_MAX_TRACKED_FILES = 100
_MAX_RANGES_PER_FILE = 64
_MUTATION_TOOLS = {"write_file", "apply_patch"}
_GUIDANCE = (
    "You've repeatedly read small regions of this unchanged file that were "
    "already returned recently. Use the existing context unless a fresh read "
    "is needed for a specific reason."
)


class RedundantReadNudge:
    """Offer transient guidance after repeated covered reads of one file.

    Coverage is based only on successful tool-result metadata. It is bounded,
    run-local, and invalidated only by successful built-in file mutations whose
    target can be identified exactly.
    """

    def __init__(self, *, source: str = "runtime") -> None:
        # Hosts inspect Hook sources as configuration metadata.
        self.source = source
        self._coverage: dict[str, list[tuple[int, int]]] = {}
        self._redundant_path: str | None = None
        self._redundant_count = 0

    def before_run(self, _ctx) -> None:
        """Discard all observations from the preceding run."""
        self._coverage.clear()
        self._reset_redundant_count()

    def tool_result(self, ctx) -> HookResponse | None:
        """Observe one final tool result and optionally emit a soft nudge."""
        tool_name = ctx.action.get("tool")
        result = ctx.result

        if tool_name == "read_file":
            return self._observe_read(ctx.action, result)

        if tool_name in _MUTATION_TOOLS and result.get("ok") is True:
            path = _result_path(ctx.action, result)
            if path is not None:
                self._coverage.pop(path, None)
                if path == self._redundant_path:
                    self._reset_redundant_count()

        return None

    def _observe_read(
        self,
        action: dict[str, Any],
        result: dict[str, Any],
    ) -> HookResponse | None:
        if result.get("ok") is not True:
            self._reset_redundant_count()
            return None

        path = _result_path(action, result)
        if path is None:
            self._reset_redundant_count()
            return None

        requested_range = _small_explicit_range(action, result)
        was_covered = (
            requested_range is not None
            and _range_is_covered(self._coverage.get(path, ()), requested_range)
        )

        # Record only what the result says was actually returned, and do so
        # after classification so a read cannot make itself redundant.
        returned_ranges = _returned_ranges(result)
        if returned_ranges:
            self._record_coverage(path, returned_ranges)

        if not was_covered:
            self._reset_redundant_count()
            return None

        if path != self._redundant_path:
            self._redundant_path = path
            self._redundant_count = 1
        else:
            self._redundant_count += 1

        if self._redundant_count < REDUNDANT_READ_THRESHOLD:
            return None

        self._reset_redundant_count()
        return HookResponse(additional_context=_GUIDANCE)

    def _record_coverage(
        self,
        path: str,
        returned_ranges: list[tuple[int, int]],
    ) -> None:
        # Reinsertion keeps the dict ordered by recent use for simple eviction.
        existing = self._coverage.pop(path, [])
        if not existing and len(self._coverage) >= _MAX_TRACKED_FILES:
            del self._coverage[next(iter(self._coverage))]
        self._coverage[path] = (existing + returned_ranges)[-_MAX_RANGES_PER_FILE:]

    def _reset_redundant_count(self) -> None:
        self._redundant_path = None
        self._redundant_count = 0


def _result_path(action: dict[str, Any], result: dict[str, Any]) -> str | None:
    """Return a stable key only when result or action exposes a real path."""
    path = result.get("path")
    if not isinstance(path, str) or not path:
        args = action.get("args")
        path = args.get("path") if isinstance(args, dict) else None
    if not isinstance(path, str) or not path:
        return None
    return os.path.normcase(os.path.normpath(path))


def _small_explicit_range(
    action: dict[str, Any],
    result: dict[str, Any],
) -> tuple[int, int] | None:
    """Return the requested range only when it is explicit, valid, and small."""
    args = action.get("args")
    if not isinstance(args, dict):
        return None

    raw_start = args.get("start_line")
    raw_end = args.get("end_line")
    if raw_start is None and raw_end is None:
        return None
    if raw_start is not None and not _is_line_number(raw_start):
        return None
    if raw_end is not None and not _is_line_number(raw_end):
        return None

    start = raw_start if raw_start is not None else 1
    end = raw_end if raw_end is not None else result.get("end_line")
    if not _is_line_number(start) or not _is_line_number(end) or end < start:
        return None
    if end - start + 1 > SMALL_READ_THRESHOLD:
        return None
    return start, end


def _returned_ranges(result: dict[str, Any]) -> list[tuple[int, int]]:
    """Extract exact returned coverage, preferring the dedicated range list."""
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


def _range_is_covered(
    coverage: Sequence[tuple[int, int]],
    requested: tuple[int, int],
) -> bool:
    """Check complete union coverage without introducing an interval subsystem."""
    requested_start, requested_end = requested
    next_needed = requested_start
    for start, end in sorted(coverage):
        if end < next_needed:
            continue
        if start > next_needed:
            return False
        next_needed = end + 1
        if next_needed > requested_end:
            return True
    return False

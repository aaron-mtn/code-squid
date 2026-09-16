"""Owns the read_file tool schema and file-reading behavior; must not own agent policy, loop control, or message formatting."""

from pathlib import Path
from typing import Any, Sequence

from squid_core.settings import ReadFileSettings

TOOL_NAME = "read_file"
DEFAULT_SETTINGS = ReadFileSettings()


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Read a UTF-8 file at an absolute path. Full-file reads return at most "
                f"{DEFAULT_SETTINGS.default_max_lines} lines. Use start_line/end_line for "
                "one 1-based inclusive region, or ranges for several known scattered "
                "regions in the same file; prefer one multi-range read to sequential reads "
                "when the needed regions are already known. A single-region read is not "
                "truncated. Small ranges may include surrounding context, and combined "
                "multi-range source coverage must stay within the normal "
                f"{DEFAULT_SETTINGS.default_max_lines}-line read limit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Optional 1-based inclusive starting line",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Optional 1-based inclusive ending line",
                    },
                    "ranges": {
                        "type": "array",
                        "description": (
                            "Optional scattered 1-based inclusive regions in this file; "
                            "cannot be combined with start_line or end_line"
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                            },
                            "required": ["start_line", "end_line"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                    },
                },
                "required": ["path"],
            },
        },
    }


# Read a file and return the result in a consistent shape.
def execute(
    _repo_root: Path,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    ranges: list[dict[str, int]] | None = None,
    *,
    settings: ReadFileSettings = DEFAULT_SETTINGS,
) -> dict:
    file_path = Path(path)
    if not file_path.is_absolute():
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "read_file requires an absolute path",
        }

    range_error = _validate_read_ranges(start_line, end_line, ranges)
    if range_error is not None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": range_error,
        }

    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if ranges is not None:
        return _read_multiple_ranges(
            path,
            lines,
            total_lines,
            ranges,
            settings,
        )

    ranged = start_line is not None or end_line is not None

    actual_start = start_line if start_line is not None else 1
    requested_end = end_line if end_line is not None else total_lines

    if ranged and actual_start > total_lines:
        actual_end = actual_start - 1
        content = ""
    else:
        actual_end = min(requested_end, total_lines)

    if ranged and actual_start <= total_lines:
        actual_start, actual_end = _expanded_range(
            actual_start,
            actual_end,
            total_lines,
            settings.minimum_range_lines,
        )
        content = "".join(lines[actual_start - 1 : actual_end])

    if ranged:
        content_metadata = {
            "truncated": False,
            "original_chars": len(content),
            "returned_chars": len(content),
        }
    else:
        original_chars = len(content)
        if total_lines <= settings.default_max_lines:
            content_metadata = {
                "truncated": False,
                "original_chars": original_chars,
                "returned_chars": original_chars,
            }
        else:
            # Keep both ends symmetrical so the omitted interval is easy to
            # inspect with a follow-up ranged read.
            head_lines = settings.default_max_lines // 2
            tail_lines = settings.default_max_lines - head_lines
            tail_start = total_lines - tail_lines + 1
            content = "".join((*lines[:head_lines], *lines[-tail_lines:]))
            content_metadata = {
                "truncated": True,
                "original_chars": original_chars,
                "returned_chars": len(content),
            }

    result = {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "content": content,
        "content_truncated": content_metadata["truncated"],
        "content_original_chars": content_metadata["original_chars"],
        "content_returned_chars": content_metadata["returned_chars"],
        "start_line": actual_start,
        "end_line": actual_end,
        "total_lines": total_lines,
        "ranged": ranged,
    }
    if content_metadata["truncated"]:
        result["returned_line_ranges"] = [
            {"start_line": 1, "end_line": head_lines},
            {"start_line": tail_start, "end_line": total_lines},
        ]
        result["truncation_guidance"] = (
            f"Full-file read truncated to {settings.default_max_lines} of {total_lines} lines; "
            f"returned lines 1-{head_lines} and {tail_start}-{total_lines}. Use "
            "start_line and end_line to inspect the missing relevant section."
        )
    return result


def _read_multiple_ranges(
    path: str,
    lines: list[str],
    total_lines: int,
    ranges: list[dict[str, int]],
    settings: ReadFileSettings,
) -> dict:
    """Return normalized scattered regions through the existing range-list contract."""

    normalized = []
    for requested in ranges:
        start_line = requested["start_line"]
        end_line = min(requested["end_line"], total_lines)
        if start_line > total_lines:
            continue
        normalized.append(
            _expanded_range(
                start_line,
                end_line,
                total_lines,
                settings.minimum_range_lines,
            )
        )

    merged = _merge_ranges(normalized)
    source_lines = sum(end - start + 1 for start, end in merged)
    if source_lines > settings.default_max_lines:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": (
                "multi-range read covers "
                f"{source_lines} lines after normalization; maximum total coverage is "
                f"{settings.default_max_lines} lines"
            ),
        }

    content = "".join(
        line
        for start_line, end_line in merged
        for line in lines[start_line - 1 : end_line]
    )
    if merged:
        actual_start = merged[0][0]
        actual_end = merged[-1][1]
    else:
        # Match a legacy range wholly past EOF: its empty interval begins at
        # the earliest requested line and ends immediately before it.
        actual_start = min(item["start_line"] for item in ranges)
        actual_end = actual_start - 1

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "content": content,
        "content_truncated": False,
        "content_original_chars": len(content),
        "content_returned_chars": len(content),
        "start_line": actual_start,
        "end_line": actual_end,
        "returned_line_ranges": _range_dicts(merged),
        "total_lines": total_lines,
        "ranged": True,
    }


def _expanded_range(
    start_line: int,
    end_line: int,
    total_lines: int,
    minimum_lines: int,
) -> tuple[int, int]:
    """Expand a valid requested region around its center, shifting at file edges."""

    target_lines = min(minimum_lines, total_lines)
    returned_lines = end_line - start_line + 1
    if returned_lines >= target_lines:
        return start_line, end_line

    missing_lines = target_lines - returned_lines
    expanded_start = max(1, start_line - missing_lines // 2)
    expanded_end = min(
        total_lines,
        end_line + (missing_lines - missing_lines // 2),
    )

    # If one file edge constrained the balanced window, use the available room
    # on the other side so small requests still receive the configured context.
    remaining = target_lines - (expanded_end - expanded_start + 1)
    if remaining and expanded_start == 1:
        expanded_end = min(total_lines, expanded_end + remaining)
    elif remaining:
        expanded_start = max(1, expanded_start - remaining)
    return expanded_start, expanded_end


# Validate caller-supplied 1-based inclusive line ranges before reading.
def _validate_range(start_line: int | None, end_line: int | None) -> str | None:
    if start_line is not None and start_line < 1:
        return "start_line must be >= 1"

    if end_line is not None and end_line < 1:
        return "end_line must be >= 1"

    if start_line is not None and end_line is not None and end_line < start_line:
        return "end_line must be >= start_line"

    return None


def _validate_read_ranges(
    start_line: int | None,
    end_line: int | None,
    ranges: object,
) -> str | None:
    """Validate the legacy range or the mutually exclusive multi-range form."""

    if ranges is None:
        return _validate_range(start_line, end_line)
    if start_line is not None or end_line is not None:
        return "ranges cannot be combined with start_line or end_line"
    if not isinstance(ranges, list) or not ranges:
        return "ranges must be a non-empty list"

    for index, item in enumerate(ranges):
        if not isinstance(item, dict):
            return f"ranges[{index}] must be an object"
        if "start_line" not in item or "end_line" not in item:
            return f"ranges[{index}] requires start_line and end_line"
        if set(item) != {"start_line", "end_line"}:
            return f"ranges[{index}] may contain only start_line and end_line"
        item_start = item["start_line"]
        item_end = item["end_line"]
        if not _is_line_number(item_start) or not _is_line_number(item_end):
            return f"ranges[{index}] start_line and end_line must be integers"
        error = _validate_range(item_start, item_end)
        if error is not None:
            return f"ranges[{index}]: {error}"
    return None


def _is_line_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge inclusive overlapping or adjacent ranges in source order."""

    merged: list[tuple[int, int]] = []
    for start_line, end_line in sorted(ranges):
        if merged and start_line <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_line))
        else:
            merged.append((start_line, end_line))
    return merged


def _range_dicts(ranges: Sequence[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"start_line": start, "end_line": end} for start, end in ranges]

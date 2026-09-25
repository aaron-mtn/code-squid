"""Owns the read_file tool schema and file-reading behavior; must not own agent policy, loop control, or message formatting."""

import hashlib
from pathlib import Path
from typing import Any, Callable, Sequence

from squid_core.image_content import (
    MAX_IMAGE_BYTES,
    SUPPORTED_IMAGE_SUFFIXES,
    UNSUPPORTED_IMAGE_SUFFIXES,
    ImageValidationError,
    inspect_image_bytes,
)
from squid_core.settings import ReadFileSettings

TOOL_NAME = "read_file"
DEFAULT_SETTINGS = ReadFileSettings()
MAX_REQUESTED_RANGES = 8


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Read a UTF-8 text file or supported PNG, JPG/JPEG, or WebP image at "
                "an absolute path. Image reads do not accept ranges. Use ranges for "
                "one or several "
                "known relevant 1-based inclusive regions of the same file, combining "
                "regions needed for the same decision. Omit ranges only when file-wide "
                "context is needed; full-file reads return at most "
                f"{DEFAULT_SETTINGS.default_max_lines} lines. Small ranges may include "
                "surrounding context, and total normalized coverage must stay within the "
                f"{DEFAULT_SETTINGS.default_max_lines}-line limit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "ranges": {
                        "type": "array",
                        "description": (
                            "Optional targeted 1-based inclusive regions in this file"
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
                        "maxItems": MAX_REQUESTED_RANGES,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }


# Read a file and return the result in a consistent shape.
def execute(
    _repo_root: Path,
    path: str,
    ranges: list[dict[str, int]] | None = None,
    *,
    settings: ReadFileSettings = DEFAULT_SETTINGS,
    snapshot_asset: Callable[[bytes, str], str] | None = None,
) -> dict:
    file_path = Path(path)
    if not file_path.is_absolute():
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "read_file requires an absolute path",
        }

    range_error = _validate_read_ranges(ranges)
    if range_error is not None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": range_error,
        }

    if file_path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
        return _read_image(file_path, path, ranges, snapshot_asset)
    if file_path.suffix.lower() in UNSUPPORTED_IMAGE_SUFFIXES:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": f"unsupported image extension: {file_path.suffix.lower()}",
        }

    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if ranges is not None:
        return _read_ranges(
            path,
            lines,
            total_lines,
            ranges,
            settings,
        )

    actual_start = 1
    actual_end = total_lines
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
        returned_ranges = [(1, head_lines), (tail_start, total_lines)]
        content = _render_ranges(lines, returned_ranges)
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
        "ranged": False,
    }
    if content_metadata["truncated"]:
        result["returned_line_ranges"] = _range_dicts(returned_ranges)
        result["truncation_guidance"] = (
            f"Full-file read truncated to {settings.default_max_lines} of {total_lines} lines; "
            f"returned lines 1-{head_lines} and {tail_start}-{total_lines}. Use "
            "ranges to inspect the missing relevant section."
        )
    return result


def _read_image(
    file_path: Path,
    path: str,
    ranges: list[dict[str, int]] | None,
    snapshot_asset: Callable[[bytes, str], str] | None,
) -> dict:
    """Validate and snapshot an image while preserving its exact source bytes."""

    if ranges is not None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "line ranges are not supported for image files",
        }
    if snapshot_asset is None:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "image reads require active session asset storage",
        }

    try:
        size_bytes = file_path.stat().st_size
        if size_bytes > MAX_IMAGE_BYTES:
            raise ImageValidationError(
                f"image is {size_bytes} bytes; maximum supported size is "
                f"{MAX_IMAGE_BYTES} bytes"
            )
        data = file_path.read_bytes()
        metadata = inspect_image_bytes(data, file_path.suffix)
    except (ImageValidationError, OSError) as error:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": str(error),
        }

    digest = hashlib.sha256(data).hexdigest()
    try:
        asset_id = snapshot_asset(data, metadata["canonical_extension"])
        expected_asset_id = f"{digest}{metadata['canonical_extension']}"
        if asset_id != expected_asset_id:
            raise OSError(
                "session asset storage returned an unexpected content identifier"
            )
    except Exception as error:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": f"could not snapshot image into the session: {error}",
        }

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "media_type": "image",
        "image": {
            "version": 1,
            "asset_id": asset_id,
            "sha256": digest,
            "mime_type": metadata["mime_type"],
            "format": metadata["format"],
            "width": metadata["width"],
            "height": metadata["height"],
            "size_bytes": metadata["size_bytes"],
        },
    }


def _read_ranges(
    path: str,
    lines: list[str],
    total_lines: int,
    ranges: list[dict[str, int]],
    settings: ReadFileSettings,
) -> dict:
    """Return normalized targeted regions through the public range-list contract."""

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
                "targeted read covers "
                f"{source_lines} lines after normalization; maximum total coverage is "
                f"{settings.default_max_lines} lines"
            ),
        }

    content = _render_ranges(lines, merged)
    if merged:
        actual_start = merged[0][0]
        actual_end = merged[-1][1]
    else:
        # An empty interval begins at the earliest requested line and ends
        # immediately before it, preserving useful location metadata.
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
def _validate_range(start_line: int, end_line: int) -> str | None:
    if start_line < 1:
        return "start_line must be >= 1"

    if end_line < 1:
        return "end_line must be >= 1"

    if end_line < start_line:
        return "end_line must be >= start_line"

    return None


def _validate_read_ranges(ranges: object) -> str | None:
    """Validate the optional public targeted-read representation."""

    if ranges is None:
        return None
    if not isinstance(ranges, list) or not ranges:
        return "ranges must be a non-empty list"
    if len(ranges) > MAX_REQUESTED_RANGES:
        return f"ranges may contain at most {MAX_REQUESTED_RANGES} items"

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


def _render_ranges(
    lines: list[str],
    ranges: Sequence[tuple[int, int]],
) -> str:
    """Render source regions with unmistakable markers at every line gap."""
    parts: list[str] = []
    previous_end = None
    for start_line, end_line in ranges:
        if previous_end is not None and start_line > previous_end + 1:
            parts.append(
                f"<<< CODE SQUID: lines {previous_end + 1}-{start_line - 1} "
                "omitted from this read >>>\n"
            )
        parts.extend(lines[start_line - 1 : end_line])
        previous_end = end_line
    return "".join(parts)

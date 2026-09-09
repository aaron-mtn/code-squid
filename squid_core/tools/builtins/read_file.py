"""Owns the read_file tool schema and file-reading behavior; must not own agent policy, loop control, or message formatting."""

from pathlib import Path

TOOL_NAME = "read_file"
MAX_FULL_FILE_LINES = 1000


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Read a UTF-8 file at an absolute path. Full-file reads return at most "
                "1000 lines; optional 1-based inclusive line ranges are not truncated."
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
                },
                "required": ["path"],
            },
        },
    }


# Read a file and return the result in a consistent shape.
def execute(_repo_root: Path, path: str, start_line: int | None = None, end_line: int | None = None) -> dict:
    file_path = Path(path)
    if not file_path.is_absolute():
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "read_file requires an absolute path",
        }

    range_error = _validate_range(start_line, end_line)
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
    ranged = start_line is not None or end_line is not None

    actual_start = start_line if start_line is not None else 1
    requested_end = end_line if end_line is not None else total_lines

    if ranged and actual_start > total_lines:
        actual_end = actual_start - 1
        content = ""
    else:
        actual_end = min(requested_end, total_lines)

    if ranged and actual_start <= total_lines:
        content = "".join(lines[actual_start - 1 : actual_end])

    if ranged:
        content_metadata = {
            "truncated": False,
            "original_chars": len(content),
            "returned_chars": len(content),
        }
    else:
        original_chars = len(content)
        if total_lines <= MAX_FULL_FILE_LINES:
            content_metadata = {
                "truncated": False,
                "original_chars": original_chars,
                "returned_chars": original_chars,
            }
        else:
            # Keep both ends symmetrical so the omitted interval is easy to
            # inspect with a follow-up ranged read.
            head_lines = MAX_FULL_FILE_LINES // 2
            tail_lines = MAX_FULL_FILE_LINES - head_lines
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
            f"Full-file read truncated to {MAX_FULL_FILE_LINES} of {total_lines} lines; "
            f"returned lines 1-{head_lines} and {tail_start}-{total_lines}. Use "
            "start_line and end_line to inspect the missing relevant section."
        )
    return result


# Validate caller-supplied 1-based inclusive line ranges before reading.
def _validate_range(start_line: int | None, end_line: int | None) -> str | None:
    if start_line is not None and start_line < 1:
        return "start_line must be >= 1"

    if end_line is not None and end_line < 1:
        return "end_line must be >= 1"

    if start_line is not None and end_line is not None and end_line < start_line:
        return "end_line must be >= start_line"

    return None

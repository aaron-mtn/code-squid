# tools/read_file.py

"""Owns the read_file tool schema and file-reading behavior; must not own agent policy, loop control, or message formatting."""

from pathlib import Path

from ._truncation import truncate_head_tail


TOOL_NAME = "read_file"


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Use this to inspect a known file. Before calling this tool, write a brief action note saying "
                "what you need to learn from this file and why it is the smallest useful next read."
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
        content, content_metadata = truncate_head_tail(content)

    return {
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


# Validate caller-supplied 1-based inclusive line ranges before reading.
def _validate_range(start_line: int | None, end_line: int | None) -> str | None:
    if start_line is not None and start_line < 1:
        return "start_line must be >= 1"

    if end_line is not None and end_line < 1:
        return "end_line must be >= 1"

    if start_line is not None and end_line is not None and end_line < start_line:
        return "end_line must be >= start_line"

    return None

"""Owns the apply_patch tool schema and exact-replacement behavior; must not own agent policy, loop control, or message formatting."""

from difflib import SequenceMatcher
from pathlib import Path


TOOL_NAME = "apply_patch"
MAX_REPORTED_MATCHES = 3
CONTEXT_LINES = 2
CLOSEST_MATCH_THRESHOLD = 0.8


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Replace exactly one occurrence of old_text in an existing UTF-8 file. "
                "Use this for small localized edits after reading the relevant content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact text currently in the file",
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    }


# Apply exactly one exact text replacement and return compact metadata.
def execute(_repo_root: Path, path: str, old_text: str, new_text: str) -> dict:
    file_path = Path(path)
    if not file_path.is_absolute():
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "path_not_absolute",
        }

    content = file_path.read_text(encoding="utf-8")
    occurrences = content.count(old_text)

    if occurrences == 0:
        result = {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "old_text_not_found",
            "occurrences": occurrences,
        }
        closest_match = _find_closest_match(content, old_text)
        if closest_match is not None:
            result["closest_match"] = closest_match
        return result

    if occurrences > 1:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "old_text_not_unique",
            "occurrences": occurrences,
            "matches": _describe_matches(content, old_text),
        }

    match_start = content.index(old_text)
    start_line, end_line_before = _line_range(content, match_start, old_text)
    _, end_line_after = _line_range(content, match_start, new_text)
    updated = content.replace(old_text, new_text, 1)
    file_path.write_text(updated, encoding="utf-8")

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "replacements": 1,
        "start_line": start_line,
        "end_line_before": end_line_before,
        "end_line_after": end_line_after,
        # Keep the original compact size metadata for existing consumers.
        "chars_before": len(content),
        "chars_after": len(updated),
    }


def _line_range(content: str, start: int, matched_text: str) -> tuple[int, int]:
    """Return the 1-based inclusive line range occupied by text at start."""
    start_line = content.count("\n", 0, start) + 1
    occupied_lines = max(1, len(matched_text.splitlines()))
    return start_line, start_line + occupied_lines - 1


def _describe_matches(content: str, old_text: str) -> list[dict]:
    """Describe the first few exact matches without returning broad file content."""
    lines = content.splitlines(keepends=True)
    matches = []
    search_start = 0
    while len(matches) < MAX_REPORTED_MATCHES:
        match_start = content.find(old_text, search_start)
        if match_start < 0:
            break

        start_line, end_line = _line_range(content, match_start, old_text)
        context_start_line = max(1, start_line - CONTEXT_LINES)
        context_end_line = min(len(lines), end_line + CONTEXT_LINES)
        matches.append(
            {
                "start_line": start_line,
                "end_line": end_line,
                "context_start_line": context_start_line,
                "context_end_line": context_end_line,
                "context": "".join(lines[context_start_line - 1 : context_end_line]),
            }
        )
        # Empty old_text retains Python's exact-count semantics and still advances.
        search_start = match_start + max(1, len(old_text))

    return matches


def _find_closest_match(content: str, old_text: str) -> dict | None:
    """Return one high-confidence same-sized line window for diagnostics only."""
    old_lines = old_text.splitlines()
    current_lines = content.splitlines(keepends=True)
    window_size = len(old_lines)
    if window_size == 0 or len(current_lines) < window_size:
        return None

    expected = "\n".join(old_lines)
    best_start = 0
    best_content = ""
    best_similarity = 0.0
    for start in range(len(current_lines) - window_size + 1):
        window = current_lines[start : start + window_size]
        comparison = "\n".join(line.rstrip("\r\n") for line in window)
        similarity = SequenceMatcher(None, expected, comparison).ratio()
        if similarity > best_similarity:
            best_start = start
            best_content = "".join(window)
            best_similarity = similarity

    if best_similarity < CLOSEST_MATCH_THRESHOLD:
        return None

    return {
        "start_line": best_start + 1,
        "end_line": best_start + window_size,
        "similarity": round(best_similarity, 3),
        "content": best_content,
    }

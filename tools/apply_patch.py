# tools/apply_patch.py

"""Owns the apply_patch tool schema and exact-replacement behavior; must not own agent policy, loop control, or message formatting."""

from pathlib import Path


TOOL_NAME = "apply_patch"


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Use this for a small exact replacement in an existing file. Prefer this for localized edits "
                "after reading the relevant content. Before calling this tool, write a brief action note saying "
                "what existing code was inspected and why this patch is safe and focused."
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
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "old_text_not_found",
            "occurrences": occurrences,
        }

    if occurrences > 1:
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "old_text_not_unique",
            "occurrences": occurrences,
        }

    updated = content.replace(old_text, new_text, 1)
    file_path.write_text(updated, encoding="utf-8")

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "replacements": 1,
        "chars_before": len(content),
        "chars_after": len(updated),
    }

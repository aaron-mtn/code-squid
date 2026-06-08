# tools/write_file.py

"""Owns the write_file tool schema and file-writing behavior; must not own agent policy, loop control, or message formatting."""

from pathlib import Path


TOOL_NAME = "write_file"


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Use this to create a new file or replace an entire file when full-file writing is genuinely "
                "appropriate. For existing files, prefer apply_patch unless the file is small, the intended "
                "change affects most of the file, or you have read the full current file and full replacement "
                "is clearer. Before calling this tool, write a brief action note saying whether the file is "
                "new or why full-file replacement is safer or clearer than apply_patch. Do not use write_file "
                "merely to avoid making a precise patch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file contents to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    }


# Write the full contents of a file and return the result in a consistent shape.
def execute(_repo_root: Path, path: str, content: str) -> dict:
    file_path = Path(path)
    if not file_path.is_absolute():
        return {
            "ok": False,
            "tool": TOOL_NAME,
            "path": path,
            "error": "write_file requires an absolute path",
        }

    characters_written = file_path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "summary": f"Wrote {characters_written} characters",
        "characters_written": characters_written,
    }

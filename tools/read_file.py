# tools/read_file.py

"""Owns the read_file tool schema and file-reading behavior; must not own agent policy, loop control, or message formatting."""

from pathlib import Path


TOOL_NAME = "read_file"


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Read the contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file relative to the repo root",
                    }
                },
                "required": ["path"],
            },
        },
    }


# Read a file from the repo and return the result in a consistent shape.
def execute(repo_root: Path, path: str) -> dict:
    file_path = repo_root / path
    content = file_path.read_text(encoding="utf-8")

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "content": content,
    }
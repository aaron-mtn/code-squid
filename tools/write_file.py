# tools/write_file.py

from pathlib import Path


TOOL_NAME = "write_file"


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Write the full contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file relative to the repo root",
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
def execute(repo_root: Path, path: str, content: str) -> dict:
    file_path = repo_root / path
    file_path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "path": path,
        "content": content,
    }
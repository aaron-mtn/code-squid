# tools/run_command.py

"""Owns the run_command tool schema and execution behavior; must not own agent policy, prompt guidance, or session updates."""

import subprocess
from pathlib import Path


TOOL_NAME = "run_command"
DEFAULT_TIMEOUT_SECONDS = 10


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Run a shell command in the repo root",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run",
                    }
                },
                "required": ["command"],
            },
        },
    }


# Run a command from the repo root and return the result in a consistent shape.
def execute(repo_root: Path, command: str) -> dict:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")

        return {
            "ok": False,
            "tool": TOOL_NAME,
            "command": command,
            "output": output,
            "returncode": -1,
            "timed_out": True,
        }

    return {
        "ok": result.returncode == 0,
        "tool": TOOL_NAME,
        "command": command,
        "output": result.stdout,
        "returncode": result.returncode,
    }

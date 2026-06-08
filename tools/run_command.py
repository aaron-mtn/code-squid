# tools/run_command.py

"""Owns the run_command tool schema and execution behavior; must not own agent policy, prompt guidance, or session updates."""

import subprocess
from pathlib import Path

from ._truncation import truncate_head_tail


TOOL_NAME = "run_command"
DEFAULT_TIMEOUT_SECONDS = 15


# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Use this for discovery, verification, tests, scripts, or shell behavior. Before calling this "
                "tool, write a brief action note saying what result you need from the command and how it "
                "reduces risk."
            ),
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
        output, output_metadata = truncate_head_tail(output)

        return {
            "ok": False,
            "tool": TOOL_NAME,
            "command": command,
            "output": output,
            "output_truncated": output_metadata["truncated"],
            "output_original_chars": output_metadata["original_chars"],
            "output_returned_chars": output_metadata["returned_chars"],
            "returncode": -1,
            "timed_out": True,
        }

    output, output_metadata = truncate_head_tail(result.stdout)

    return {
        "ok": result.returncode == 0,
        "tool": TOOL_NAME,
        "command": command,
        "output": output,
        "output_truncated": output_metadata["truncated"],
        "output_original_chars": output_metadata["original_chars"],
        "output_returned_chars": output_metadata["returned_chars"],
        "returncode": result.returncode,
    }

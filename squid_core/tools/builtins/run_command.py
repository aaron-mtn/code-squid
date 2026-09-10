"""Own deterministic ``run_command`` execution and failure diagnostics.

The Tool reports mechanical process facts. Recovery policy and model guidance
remain runtime/application concerns rather than behavior of this built-in.
"""

import errno
import re
import subprocess
from pathlib import Path

from squid_core.platform_context import PlatformContext, detect_platform_context

from ._truncation import truncate_head_tail


TOOL_NAME = "run_command"
DEFAULT_TIMEOUT_SECONDS = 15


_POWERSHELL_COMMAND_NOT_FOUND = re.compile(
    r"The term '.+?' is not recognized as the name of a cmdlet, function, "
    r"script file, or operable program",
    re.IGNORECASE | re.DOTALL,
)
_POWERSHELL_INVALID_SEPARATOR = re.compile(
    r"The token '(?:&&|\|\|)' is not a valid statement separator",
    re.IGNORECASE,
)
# Return the tool definition shown to the model.
def tool_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Run one shell command from the repository root and return its combined output and exit status."
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
def execute(
    repo_root: Path,
    command: str,
    platform_context: PlatformContext | None = None,
) -> dict:
    platform_context = platform_context or detect_platform_context()
    subprocess_command: str | list[str] = command
    use_shell = True
    if platform_context.is_windows:
        subprocess_command = [
            platform_context.shell_executable,
            "-NoProfile",
            "-Command",
            command,
        ]
        use_shell = False

    try:
        result = subprocess.run(
            subprocess_command,
            shell=use_shell,
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
            "failure_class": "timeout",
            "shell": platform_context.shell_name,
            "platform": platform_context.os_name,
        }
    except OSError as exc:
        output, output_metadata = truncate_head_tail(str(exc))
        if exc.errno in {errno.EACCES, errno.EPERM}:
            failure_class = "permission_denied"
        elif exc.errno == errno.ENOENT:
            # This exception describes the configured shell, cwd, or another
            # launch path. It does not prove that the requested command is absent.
            failure_class = "path_not_found"
        else:
            failure_class = "unknown_failure"

        return {
            "ok": False,
            "tool": TOOL_NAME,
            "command": command,
            "output": output,
            "output_truncated": output_metadata["truncated"],
            "output_original_chars": output_metadata["original_chars"],
            "output_returned_chars": output_metadata["returned_chars"],
            "returncode": -1,
            "failure_class": failure_class,
            "shell": platform_context.shell_name,
            "platform": platform_context.os_name,
        }

    output, output_metadata = truncate_head_tail(result.stdout)
    response = {
        "ok": result.returncode == 0,
        "tool": TOOL_NAME,
        "command": command,
        "output": output,
        "output_truncated": output_metadata["truncated"],
        "output_original_chars": output_metadata["original_chars"],
        "output_returned_chars": output_metadata["returned_chars"],
        "returncode": result.returncode,
    }
    if result.returncode != 0:
        response.update(
            {
                "failure_class": _classify_failure(
                    platform_context,
                    result.returncode,
                    result.stdout,
                ),
                "shell": platform_context.shell_name,
                "platform": platform_context.os_name,
            }
        )
    return response


def _classify_failure(
    platform_context: PlatformContext,
    returncode: int,
    output: str,
) -> str:
    """Classify only strong shell/process signals from a completed command."""
    if platform_context.is_windows:
        if (
            _POWERSHELL_INVALID_SEPARATOR.search(output)
            and re.search(r"At line:\d+ char:\d+", output)
        ) or (
            re.search(r"At line:\d+ char:\d+", output)
            and re.search(r"CategoryInfo\s*:\s*ParserError", output)
        ) or (
            re.search(r"^ParserError:\s*$", output, re.MULTILINE)
            and re.search(r"^Line \|\s*$", output, re.MULTILINE)
        ):
            return "shell_syntax_error"
        if _POWERSHELL_COMMAND_NOT_FOUND.search(output) and (
            "CommandNotFoundException" in output
            or re.search(r"CategoryInfo\s*:\s*ObjectNotFound", output)
        ):
            return "command_not_found"
        if re.search(
            r"Cannot find path '.+?' because it does not exist",
            output,
            re.IGNORECASE | re.DOTALL,
        ) and (
            "ItemNotFoundException" in output
            or re.search(r"CategoryInfo\s*:\s*ObjectNotFound", output)
        ):
            return "path_not_found"
        if "UnauthorizedAccessException" in output or re.search(
            r"CategoryInfo\s*:\s*PermissionDenied", output
        ):
            return "permission_denied"
        return "process_failed"

    # Exit status alone is not enough: an application may deliberately return
    # 126/127. Require the configured shell's recognizable diagnostic as well.
    shell_name = re.escape(platform_context.shell_name)
    shell_prefix = rf"^(?:.*/)?{shell_name}:\s*"
    if returncode == 127 and (
        re.search(
            shell_prefix
            + r"(?:(?:line )?\d+:\s*)?(?:[^:\r\n]+:\s*)?"
            + r"(?:command )?not found\s*$",
            output,
            re.IGNORECASE | re.MULTILINE,
        )
        or re.search(
            shell_prefix + r"\d+:\s*command not found:\s*[^\r\n]+$",
            output,
            re.IGNORECASE | re.MULTILINE,
        )
    ):
        return "command_not_found"
    if returncode == 126 and re.search(
        shell_prefix + r".*Permission denied\s*$",
        output,
        re.IGNORECASE | re.MULTILINE,
    ):
        return "permission_denied"

    if returncode == 2 and re.search(
        rf"^(?:.*/)?{shell_name}:.*syntax error",
        output,
        re.IGNORECASE | re.MULTILINE,
    ):
        return "shell_syntax_error"
    if re.search(
        rf"^(?:.*/)?{shell_name}:.*cd:.*No such file or directory",
        output,
        re.IGNORECASE | re.MULTILINE,
    ):
        return "path_not_found"
    return "process_failed"

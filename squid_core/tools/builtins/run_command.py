"""Own cancellable ``run_command`` execution and failure diagnostics."""

import errno
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

from squid_core.platform_context import PlatformContext, detect_platform_context

from ._truncation import truncate_head_tail


TOOL_NAME = "run_command"
DEFAULT_TIMEOUT_SECONDS = 15
POLL_INTERVAL_SECONDS = 0.05

_POWERSHELL_COMMAND_NOT_FOUND = re.compile(
    r"The term '.+?' is not recognized as the name of a cmdlet, function, "
    r"script file, or operable program",
    re.IGNORECASE | re.DOTALL,
)
_POWERSHELL_INVALID_SEPARATOR = re.compile(
    r"The token '(?:&&|\|\|)' is not a valid statement separator",
    re.IGNORECASE,
)


def tool_definition() -> dict:
    """Return the command Tool definition shown to the model."""
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Run one shell command from the repository root and return its "
                "combined output and exit status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "verification": {
                        "type": "boolean",
                        "description": (
                            "REQUIRED. True when this command checks whether the current "
                            "implementation is correct; false otherwise."
                        ),
                    },
                },
                "required": ["command", "verification"],
            },
        },
    }


def execute(
    repo_root: Path,
    command: str,
    verification: bool,
    platform_context: PlatformContext | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    """Run one owned process tree and return its normalized result."""
    platform_context = platform_context or detect_platform_context()
    should_cancel = should_cancel or (lambda: False)
    subprocess_command: str | list[str] = command
    use_shell = True
    popen_options = {}
    if platform_context.is_windows:
        subprocess_command = [
            platform_context.shell_executable,
            "-NoProfile",
            "-Command",
            command,
        ]
        use_shell = False
        popen_options["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        # A new session gives the Tool an exact process group to terminate.
        popen_options["start_new_session"] = True

    try:
        process = subprocess.Popen(
            subprocess_command,
            shell=use_shell,
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **popen_options,
        )
    except OSError as exc:
        return _launch_failure(command, verification, platform_context, exc)

    deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
    cancelled = False
    timed_out = False
    output_bytes = b""
    while True:
        if should_cancel():
            cancelled = True
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            output_bytes, _ = process.communicate(
                timeout=min(POLL_INTERVAL_SECONDS, remaining)
            )
            break
        except subprocess.TimeoutExpired:
            continue

    if cancelled or timed_out:
        _terminate_process_tree(process, platform_context.is_windows)
        try:
            output_bytes, _ = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            output_bytes, _ = process.communicate()

    output = (output_bytes or b"").decode("utf-8", errors="replace")
    # Match subprocess text mode's universal-newline behavior on every platform.
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    output, output_metadata = truncate_head_tail(output)
    if cancelled or timed_out:
        response = _base_response(
            command, verification, output, output_metadata, returncode=-1
        )
        response.update(
            {
                "cancelled": cancelled,
                "timed_out": timed_out,
                "failure_class": "cancelled" if cancelled else "timeout",
                "shell": platform_context.shell_name,
                "platform": platform_context.os_name,
            }
        )
        return response

    response = _base_response(
        command,
        verification,
        output,
        output_metadata,
        returncode=process.returncode,
    )
    response["ok"] = process.returncode == 0
    if process.returncode != 0:
        response.update(
            {
                "failure_class": _classify_failure(
                    platform_context, process.returncode, output
                ),
                "shell": platform_context.shell_name,
                "platform": platform_context.os_name,
            }
        )
    return response


def _terminate_process_tree(process: subprocess.Popen, is_windows: bool) -> None:
    """Terminate descendants using the process-tree primitive for this platform."""
    if process.poll() is not None:
        return
    if is_windows:
        # taskkill /T is the smallest dependable Windows descendant-tree primitive.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if process.poll() is None:
            process.kill()
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _base_response(
    command: str,
    verification: bool,
    output: str,
    output_metadata: dict,
    *,
    returncode: int,
) -> dict:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "command": command,
        "verification": verification,
        "output": output,
        "output_truncated": output_metadata["truncated"],
        "output_original_chars": output_metadata["original_chars"],
        "output_returned_chars": output_metadata["returned_chars"],
        "returncode": returncode,
    }


def _launch_failure(
    command: str,
    verification: bool,
    platform_context: PlatformContext,
    exc: OSError,
) -> dict:
    output, metadata = truncate_head_tail(str(exc))
    if exc.errno in {errno.EACCES, errno.EPERM}:
        failure_class = "permission_denied"
    elif exc.errno == errno.ENOENT:
        failure_class = "path_not_found"
    else:
        failure_class = "unknown_failure"
    response = _base_response(command, verification, output, metadata, returncode=-1)
    response.update(
        {
            "failure_class": failure_class,
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

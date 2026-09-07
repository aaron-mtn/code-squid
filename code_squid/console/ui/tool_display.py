"""Tool action labels and result presentation for the Code Squid console."""

from pathlib import Path
import re
import shlex

from code_squid.console.ui import formatting
from code_squid.console.ui.formatting import (
    SOFT_GREEN_STYLE,
    SOFT_RED_STYLE,
    SOFT_YELLOW_STYLE,
    single_line,
    short_path,
    truncate_middle,
)


COMMAND_LABEL_MAX = 64
APPROVAL_COMMAND_LABEL_MAX = 120
FILE_TOOLS = {"read_file", "write_file", "apply_patch"}


def action_label(action: dict, phase: str, display_root: Path) -> str:
    """Return the visible action label for a tool and lifecycle phase."""
    tool_name = action.get("tool", "")
    args = action.get("args", {})

    if tool_name == "read_file":
        path = short_path(args.get("path", ""), display_root)
        if phase == "failure":
            return f"{formatting.RECOVERABLE_STATUS_ICON} Read failed: {path}"
        return f"📖 Read: {path}"

    if tool_name == "write_file":
        path = short_path(args.get("path", ""), display_root)
        if phase == "success":
            return f"📝 Wrote: {path}"
        if phase == "failure":
            return f"{formatting.RECOVERABLE_STATUS_ICON} Write failed: {path}"
        return f"📝 Write: {path}"

    if tool_name == "apply_patch":
        path = short_path(args.get("path", ""), display_root)
        if phase == "success":
            return f"🩹 Patched: {path}"
        if phase == "failure":
            return f"{formatting.RECOVERABLE_STATUS_ICON} Patch failed: {path}"
        return f"🩹 Patch: {path}"

    if tool_name == "run_command":
        return command_label(
            args.get("command", ""),
            phase,
            display_root,
            max_length=(
                APPROVAL_COMMAND_LABEL_MAX if phase == "start" else COMMAND_LABEL_MAX
            ),
        )

    return f"🔧 Run: {tool_name}"


def generic_tool_success_label(tool_name: str, result: dict) -> str:
    """Return a compact success label for a non-built-in tool."""
    label = f"✅ {tool_name} completed"
    message = single_line(result.get("message", "")).strip()
    if not message:
        return label
    return f"{label}: {truncate_middle(message, APPROVAL_COMMAND_LABEL_MAX)}"


def tool_result_line(
    action: dict,
    result: dict,
    display_root: Path,
    *,
    debug: bool = False,
) -> tuple[str, str, bool] | None:
    """Return one result line as ``(label, style, dim)``."""
    tool_name = action.get("tool")
    if tool_name == "run_command":
        return run_command_result_line(action, result, display_root, debug=debug)

    if result.get("ok", False):
        if tool_name in FILE_TOOLS:
            return action_label(action, "success", display_root), "", True
        if tool_name:
            return generic_tool_success_label(str(tool_name), result), "", True
        return None

    error = result.get("error", "unknown error")
    style = SOFT_RED_STYLE if debug else ""
    dim = not debug
    if tool_name in FILE_TOOLS:
        label = action_label(action, "failure", display_root)
        return f"{label} - {error}", style, dim
    return f"{formatting.RECOVERABLE_STATUS_ICON} {tool_name} failed: {error}", style, dim


def run_command_result_line(
    action: dict,
    result: dict,
    display_root: Path,
    *,
    debug: bool = False,
) -> tuple[str, str, bool]:
    """Return the visible command-result label, style, and dimming decision."""
    if result.get("timed_out"):
        if debug:
            return (
                f"{formatting.RECOVERABLE_STATUS_ICON} Command timed out",
                SOFT_YELLOW_STYLE,
                False,
            )
        return f"{formatting.RECOVERABLE_STATUS_ICON} Command timed out", "", True

    summary = pytest_summary(result.get("output", ""))
    if summary:
        if "failed" in summary:
            if debug:
                return (
                    f"{formatting.RECOVERABLE_STATUS_ICON} Tests need review: {summary}",
                    SOFT_YELLOW_STYLE,
                    False,
                )
            return (
                f"{formatting.RECOVERABLE_STATUS_ICON} Tests need review: {summary}",
                "",
                True,
            )
        return f"🧪 Tests passed: {summary}", SOFT_GREEN_STYLE, False

    phase = "success" if result.get("ok", False) else "failure"
    label = action_label(action, phase, display_root)
    if phase == "failure":
        if debug:
            return label, SOFT_RED_STYLE, False
        return label, "", True
    return label, "", True


def command_label(
    command: str,
    phase: str,
    display_root: Path,
    max_length: int = COMMAND_LABEL_MAX,
) -> str:
    """Recognize common command shapes and return their concise action label."""
    command = str(command).strip()
    tokens = command_tokens(command)
    first = Path(tokens[0]).name if tokens else ""

    if is_pytest_command(tokens):
        pytest_command = (
            "python -m pytest" if Path(tokens[0]).name.startswith("python") else "pytest"
        )
        verb = "Ran" if phase == "success" else "Run"
        if phase == "failure":
            return f"{formatting.RECOVERABLE_STATUS_ICON} Command failed: {pytest_command}"
        return f"💿 {verb}: {pytest_command}"

    if first in {"find", "rg", "grep"}:
        return "🔎 Searched files" if phase == "success" else "🔎 Search files"
    if first == "ls":
        return "🔎 Listed files" if phase == "success" else "🔎 List files"

    node_check = node_check_label(tokens, display_root)
    if node_check:
        verb = "Ran" if phase == "success" else "Run"
        if phase == "failure":
            return f"{formatting.RECOVERABLE_STATUS_ICON} Command failed: {node_check}"
        return f"💿 {verb}: {node_check}"

    command = truncate_middle(command, max_length)
    if phase == "success":
        return f"💿 Ran: {command}"
    if phase == "failure":
        return f"{formatting.RECOVERABLE_STATUS_ICON} Command failed: {command}"
    return f"💿 Run: {command}"


def command_tokens(command: str) -> list[str]:
    """Split a command for display recognition, tolerating incomplete quoting."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def is_pytest_command(tokens: list[str]) -> bool:
    """Return whether tokens invoke pytest through a supported spelling."""
    if not tokens:
        return False
    first = Path(tokens[0]).name
    return first == "pytest" or tokens[:3] in (
        ["python", "-m", "pytest"],
        ["python3", "-m", "pytest"],
    )


def node_check_label(tokens: list[str], display_root: Path) -> str:
    """Return the concise label for a node syntax check, if recognized."""
    if len(tokens) < 3:
        return ""
    if Path(tokens[0]).name != "node" or tokens[1] != "--check":
        return ""
    return f"node --check {short_path(tokens[2], display_root)}"


def pytest_summary(output: str) -> str:
    """Extract the final compact pytest pass/fail summary from command output."""
    matches = re.findall(
        r"\d+\s+failed,\s+\d+\s+passed|\d+\s+passed|\d+\s+failed",
        output,
    )
    return matches[-1] if matches else ""


def debug_action_lines(action: dict, display_root: Path) -> list[str]:
    """Format one model-requested tool action for the debug transcript."""
    tool_name = action.get("tool", "")
    args = action.get("args", {})
    lines = [f"tool: {tool_name}"]

    if tool_name in FILE_TOOLS and args.get("path"):
        lines.append(f"path: {short_path(str(args['path']), display_root)}")
    if tool_name == "run_command" and args.get("command"):
        lines.append(
            f"command: {truncate_middle(str(args['command']), COMMAND_LABEL_MAX)}"
        )
    if action.get("tool_call_id"):
        lines.append(f"tool_call_id: {action['tool_call_id']}")
    return lines


def debug_tool_result_lines(
    action: dict,
    result: dict,
    display_root: Path,
) -> list[str]:
    """Format a tool result for the debug transcript without changing semantics."""
    tool_name = action.get("tool", "")
    lines = [
        f"ok: {_debug_value(result.get('ok', False))}",
        f"tool: {tool_name}",
    ]
    args = action.get("args", {})

    if tool_name == "read_file":
        if args.get("path"):
            lines.append(f"path: {short_path(str(args['path']), display_root)}")
        if not result.get("ok", False) and result.get("error"):
            lines.append(f"error: {result['error']}")
            return lines
        lines.extend(
            [
                "chars: "
                f"{result.get('content_returned_chars', 0)} / "
                f"{result.get('content_original_chars', 0)}",
                "lines: "
                f"{result.get('start_line', '')}-{result.get('end_line', '')} / "
                f"{result.get('total_lines', '')}",
                f"truncated: {_debug_value(result.get('content_truncated', False))}",
            ]
        )
        return lines

    if tool_name == "write_file":
        if args.get("path"):
            lines.append(f"path: {short_path(str(args['path']), display_root)}")
        if not result.get("ok", False) and result.get("error"):
            lines.append(f"error: {result['error']}")
            return lines
        lines.extend(
            [
                f"characters_written: {result.get('characters_written', 0)}",
                f"summary: {result.get('summary', '')}",
            ]
        )
        return lines

    if tool_name == "apply_patch":
        if args.get("path"):
            lines.append(f"path: {short_path(str(args['path']), display_root)}")
        if not result.get("ok", False) and result.get("error"):
            lines.append(f"error: {result['error']}")
            return lines
        lines.extend(
            [
                f"replacements: {result.get('replacements', 0)}",
                f"chars: {result.get('chars_before', 0)} -> {result.get('chars_after', 0)}",
            ]
        )
        return lines

    if tool_name == "run_command":
        lines.extend(
            [
                f"returncode: {result.get('returncode', '')}",
                f"timed_out: {_debug_value(result.get('timed_out', False))}",
                "chars: "
                f"{result.get('output_returned_chars', 0)} / "
                f"{result.get('output_original_chars', 0)}",
                f"truncated: {_debug_value(result.get('output_truncated', False))}",
            ]
        )
        summary = pytest_summary(result.get("output", ""))
        if summary:
            lines.append(f"pytest: {summary}")
        return lines

    if result.get("error"):
        lines.append(f"error: {result['error']}")
    return lines


def _debug_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)

"""Approval panel, prompt, and result presentation for the Code Squid console."""

from pathlib import Path
import sys

from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText

from code_squid.console.ui.formatting import (
    DISPLAY_WRAP_WIDTH,
    SOFT_CYAN_STYLE,
    SOFT_RED_STYLE,
    short_path,
    single_line,
    structural_bordered_line,
    structural_text,
    styled_text,
    truncate_middle,
)
from code_squid.console.ui.tool_display import action_label


APPROVAL_PANEL_WIDTH = 61
INPUT_PROMPT_PREFIX = "› "
INPUT_PROMPT_STYLE = "#7dd3fc bold"


def approval_panel(
    action: dict,
    *,
    debug: bool,
    display_root: Path,
    detail_indent: str,
) -> tuple[list[str], AnyFormattedText]:
    """Build the approval panel and prompt without making a safety decision."""
    inner_width = APPROVAL_PANEL_WIDTH - 2
    title = " approval required "
    top = f"╭─{title}{'─' * max(inner_width - len(title) - 1, 0)}╮"
    bottom = f"╰{'─' * inner_width}╯"

    def approval_line(line: str) -> str:
        return line if debug else _indented_line(line, detail_indent)

    lines = [
        approval_line(structural_text(top)),
        _panel_line("Tool", str(action.get("tool", "")), inner_width, approval_line),
        _panel_action_line(action, inner_width, display_root, approval_line),
    ]
    if action.get("approval_reason"):
        lines.append(
            _panel_line(
                "Reason",
                approval_reason_label(action),
                inner_width,
                approval_line,
            )
        )
    lines.append(approval_line(structural_text(bottom)))
    return lines, approval_prompt(debug=debug, detail_indent=detail_indent)


def approval_reason_label(action: dict) -> str:
    """Return the compact visible reason while retaining the source action."""
    reason = single_line(str(action.get("approval_reason", "")))
    if reason.startswith("Requested path is outside the workspace root:"):
        return "Outside workspace"
    return reason


def approval_prompt(*, debug: bool, detail_indent: str) -> AnyFormattedText:
    """Build the formatted multiline-input prompt for an approval decision."""
    prompt_text = "Enter to approve, or type guidance instead:\n"
    if not debug:
        prompt_text = _indented_line(prompt_text, detail_indent)
    return FormattedText(
        [
            ("", prompt_text),
            (INPUT_PROMPT_STYLE, INPUT_PROMPT_PREFIX),
        ]
    )


def printed_prompt_line_count(prompt: AnyFormattedText) -> int:
    """Count occupied terminal lines so an interactive prompt can be compacted."""
    if isinstance(prompt, str):
        text = prompt
    else:
        text = "".join(fragment[1] for fragment in prompt)
    return text.count("\n") + 1


def can_compact_approval_prompt(*, debug: bool, show_transcript: bool) -> bool:
    """Return whether ephemeral approval UI may be erased from the terminal."""
    return not debug and not show_transcript and sys.stdout.isatty()


def clear_printed_lines(line_count: int) -> None:
    """Erase the requested number of already printed interactive terminal lines."""
    for _ in range(line_count):
        sys.stdout.write("\033[1A\r\033[2K")
    sys.stdout.flush()


def rejected_approval_result(instruction: str, detail_indent: str) -> str:
    """Render a compact rejected-approval line, including optional guidance."""
    if instruction:
        comment = truncate_middle(single_line(instruction), DISPLAY_WRAP_WIDTH)
        label = f"💬 User note: {comment}"
        style = SOFT_CYAN_STYLE
    else:
        label = "🚫 Action denied"
        style = SOFT_RED_STYLE
    return styled_text(_indented_line(label, detail_indent), style)


def _panel_action_line(
    action: dict,
    inner_width: int,
    display_root: Path,
    approval_line,
) -> str:
    tool_name = action.get("tool", "")
    args = action.get("args", {})
    if tool_name in {"read_file", "write_file", "apply_patch"}:
        value = short_path(single_line(args.get("path", "")), display_root)
        return _panel_line("Path", value, inner_width, approval_line)
    if tool_name == "run_command":
        value = single_line(args.get("command", ""))
        return _panel_line("Action", value, inner_width, approval_line)
    return _panel_line(
        "Action",
        action_label(action, "start", display_root),
        inner_width,
        approval_line,
    )


def _panel_line(label: str, value: str, inner_width: int, approval_line) -> str:
    label_text = f"{label}:"
    label_width = 7
    available = inner_width - 2 - label_width - 1
    value = truncate_middle(str(value), max(available, 1))
    content = f" {label_text:<{label_width}} {value}"
    return approval_line(
        structural_bordered_line("│", f"{content:<{inner_width}}", "│")
    )


def _indented_line(line: str, indent: str) -> str:
    if not line:
        return line
    return f"{indent}{line}"

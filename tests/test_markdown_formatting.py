"""Focused tests for the shared lightweight terminal Markdown renderer."""

import re
import sys

import pytest

from code_squid.console.ui.display import (
    PANEL_CONTENT_WIDTH,
    PANEL_LEFT_PADDING,
    RUN_PANEL_WIDTH,
    TerminalDisplay,
    _display_width,
)
from code_squid.console.ui.formatting import (
    BOLD_STYLE,
    ITALIC_STYLE,
    RESET_STYLE,
    SOFT_CYAN_STYLE,
    STRIKETHROUGH_STYLE,
    display_width,
    render_inline_markdown,
    render_markdown_lines,
)


CONTROL_SEQUENCE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x1b]*(?:\x1b\\|\x07))"
)


def test_inline_styles_code_links_and_escapes_in_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    rendered = render_inline_markdown(
        r"**bold words** *italic* _also italic_ ~~gone~~ `value` "
        r"[docs](https://example.com) \*literal\*"
    )

    assert f"{BOLD_STYLE}bold words{RESET_STYLE}" in rendered
    assert f"{ITALIC_STYLE}italic{RESET_STYLE}" in rendered
    assert f"{ITALIC_STYLE}also italic{RESET_STYLE}" in rendered
    assert f"{STRIKETHROUGH_STYLE}gone{RESET_STYLE}" in rendered
    assert f"{SOFT_CYAN_STYLE}value{RESET_STYLE}" in rendered
    assert "\033]8;;https://example.com\033\\docs\033]8;;\033\\" in rendered
    assert "*literal*" in rendered


def test_incomplete_streamed_inline_markdown_stays_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    assert render_inline_markdown("**unfinished") == "**unfinished"
    assert render_inline_markdown("`unfinished") == "`unfinished"


def test_headings_lists_quotes_fence_and_rule_render_as_blocks() -> None:
    lines = render_markdown_lines(
        "# Heading one\n"
        "## Heading two\n"
        "### Heading three\n"
        "- parent\n"
        "  - child\n"
        "1. first\n"
        "> quoted words\n"
        "```python\n"
        "  print('hello')\n"
        "```\n"
        "---",
        width=32,
    )

    assert lines[:3] == ["Heading one", "Heading two", "Heading three"]
    assert "• parent" in lines
    assert "  • child" in lines
    assert "1. first" in lines
    assert "│ quoted words" in lines
    assert "    print('hello')" in lines
    assert lines[-1] == "─" * 32


@pytest.mark.parametrize("marker", ["#", "##", "###"])
def test_heading_levels_preserve_caller_indent_when_wrapped(marker: str) -> None:
    lines = render_markdown_lines(
        f"{marker} alpha beta gamma delta",
        width=14,
        indent="  ",
    )

    assert lines == ["  alpha beta", "  gamma delta"]


def test_incomplete_fence_keeps_source_visible() -> None:
    lines = render_markdown_lines("```python\nprint('still arriving')", width=40)

    assert lines == ["```python", "print('still arriving')"]


def test_pipe_table_alignment_and_width_constraint() -> None:
    lines = render_markdown_lines(
        "| File       | Status  | Notes              |\n"
        "| :--------- | :-----: | -----------------: |\n"
        "| backend.py | Changed | Added tab tracking |\n"
        "| tests.py   | Passed  | 7 tests            |",
        width=36,
    )

    assert len(lines) == 4
    assert "File" in lines[0] and "Status" in lines[0] and "Notes" in lines[0]
    assert "┼" in lines[1]
    assert "backend.py" in lines[2]
    assert all(display_width(line) <= 36 for line in lines)


def test_table_remains_safe_in_minimum_streaming_viewport() -> None:
    lines = TerminalDisplay()._assistant_narration_panel_lines(
        "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |",
        viewport_width=9,
    )

    assert lines
    assert all(_display_width(line) == 9 for line in lines)


def test_unicode_and_osc_width_are_measured_as_terminal_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    rendered = render_inline_markdown("漢 [link](https://example.com/a/very/long/path)")

    assert display_width(rendered) == 7
    assert "\033]8;;" in rendered
    assert CONTROL_SEQUENCE.sub("", rendered) == "漢 link"


def test_narration_and_final_response_share_markdown_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    display = TerminalDisplay()

    narration = "\n".join(display._assistant_narration_panel_lines("## **Shared**\n- `code`"))
    final = display._format_final_summary("## **Shared**\n- `code`")

    for output in (narration, final):
        assert "##" not in output
        assert "**Shared**" not in output
        assert "`code`" not in output
        assert f"{BOLD_STYLE}Shared{RESET_STYLE}" in output
        assert f"{SOFT_CYAN_STYLE}code{RESET_STYLE}" in output
        assert "• " in output
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in narration.splitlines())


def test_inline_ansi_and_osc_do_not_break_panel_wrapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    display = TerminalDisplay()
    lines = display._assistant_narration_panel_lines(
        "**Wide 漢字 text** and [a link](https://example.com/long/url) " * 3
    )

    assert len(lines) > 3
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)


def test_wider_panel_preserves_established_narration_wrapping_and_adds_padding(
) -> None:
    display = TerminalDisplay()
    content = "word " * 20

    wide_lines = display._assistant_narration_panel_lines(content)
    baseline_lines = display._assistant_narration_panel_lines(content, viewport_width=61)

    wide_content = [
        line[len(PANEL_LEFT_PADDING) + 1 :].rstrip(" │")
        for line in wide_lines[1:-1]
    ]
    baseline_content = [
        line[len(PANEL_LEFT_PADDING) + 1 :].rstrip(" │")
        for line in baseline_lines[1:-1]
    ]
    assert wide_content == baseline_content
    assert _display_width(wide_lines[1]) == RUN_PANEL_WIDTH
    wide_padding = len(wide_lines[1][:-1]) - len(wide_lines[1][:-1].rstrip(" "))
    baseline_padding = len(baseline_lines[1][:-1]) - len(
        baseline_lines[1][:-1].rstrip(" ")
    )
    assert wide_padding == baseline_padding + 4
    assert PANEL_CONTENT_WIDTH == 56


def test_panel_wraps_content_beyond_its_intended_width() -> None:
    lines = TerminalDisplay()._render_panel_lines(
        ["x" * (PANEL_CONTENT_WIDTH + 1)]
    )

    assert len(lines) == 4
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)

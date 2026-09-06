"""Tests for Code Squid terminal presentation and interaction helpers."""

import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest
from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText

from squid_core.safety import USER_DENIED_TOOL_ACTION
from squid_core.agent_loop import RunResult
from code_squid.console.ui.display import (
    APPROVAL_PANEL_WIDTH,
    BOLD_STYLE,
    DIM_STYLE,
    DEFAULT_MOD_ACCENT_HEX,
    FINAL_SUMMARY_INDENT,
    INPUT_PROMPT_PREFIX,
    INPUT_PROMPT_STYLE,
    RUN_PANEL_WIDTH,
    RUN_DETAIL_INDENT,
    RESET_STYLE,
    RUN_EVENT_INDENT,
    SOFT_CYAN_HEX,
    SOFT_CYAN_STYLE,
    SOFT_GREEN_HEX,
    SOFT_GREEN_STYLE,
    SOFT_RED_HEX,
    SOFT_RED_STYLE,
    SOFT_YELLOW_HEX,
    SOFT_YELLOW_STYLE,
    _accent_for_mod,
    _display_width,
    StartupInfo,
    TerminalDisplay,
)
from code_squid.console.ui.banner import (
    concise_workspace_name,
    startup_info_panel,
    startup_panel_items,
)
from code_squid.console.ui.formatting import (
    MOD_ACCENT_HEX,
    SQUID_GLYPH,
    ansi_fg,
    mod_accent_hex,
)


class FakeSpinner:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


def empty_session(**overrides):
    """Return the smallest session-shaped object used by display tests."""
    values = {"files_read": set(), "files_written": set(), "messages": []}
    values.update(overrides)
    return SimpleNamespace(**values)


def finish_display(display: TerminalDisplay, content: str = "") -> None:
    """Drive the two callbacks that compose the final completion panel."""
    display.final_message(content)
    display.loop_finished(empty_session())


class FakeHeader:
    def __init__(self) -> None:
        self.startup_infos: list[StartupInfo | None] = []

    def set_startup_info(self, startup_info: StartupInfo | None) -> None:
        self.startup_infos.append(startup_info)

def _approval_panel_output(tool: str, label: str, value: str) -> str:
    inner_width = APPROVAL_PANEL_WIDTH - 2
    label_width = 7
    value_width = inner_width - 2 - label_width - 1
    title = " approval required "
    top = f"╭─{title}{'─' * max(inner_width - len(title) - 1, 0)}╮"
    bottom = f"╰{'─' * inner_width}╯"
    tool_content = f" {'Tool:':<{label_width}} {tool:<{value_width}}"
    action_content = f" {f'{label}:':<{label_width}} {value:<{value_width}}"
    return "\n".join(
        [
            f"{RUN_DETAIL_INDENT}{top}",
            f"{RUN_DETAIL_INDENT}│{tool_content:<{inner_width}}│",
            f"{RUN_DETAIL_INDENT}│{action_content:<{inner_width}}│",
            f"{RUN_DETAIL_INDENT}{bottom}",
            "",
        ]
    )


def _approval_prompt() -> FormattedText:
    return FormattedText(
        [
            ("", f"{RUN_DETAIL_INDENT}Enter to approve, or type guidance instead:\n"),
            (INPUT_PROMPT_STYLE, INPUT_PROMPT_PREFIX),
        ]
    )


def _prompt_plain_text(prompt: AnyFormattedText) -> str:
    if isinstance(prompt, str):
        return prompt
    return "".join(fragment[1] for fragment in prompt)


@pytest.mark.parametrize("response", ["", "   "])
def test_approve_action_accepts_empty_input(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: response)

    decision = TerminalDisplay().approve_action({"tool": "read_file"})

    assert decision.approved is True
    assert decision.instruction == ""


@pytest.mark.parametrize("response", ["n", "no", "use python instead"])
def test_approve_action_rejects_non_empty_input_as_instruction(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: response)

    decision = TerminalDisplay().approve_action({"tool": "read_file"})

    assert decision.approved is False
    assert decision.instruction == response


def test_approve_action_rejects_multiline_input_with_full_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = "Use a narrower change.\nKeep the tests focused.\nDo not run npm."
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: response)

    decision = TerminalDisplay().approve_action({"tool": "read_file"})

    assert decision.approved is False
    assert decision.instruction == response


def test_multiline_rejection_summary_is_compacted_without_losing_instruction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    response = (
        "Use a narrower change.\n"
        "This second line should reach the model.\n"
        "This third line can stay out of the visible summary."
    )
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: response)

    decision = TerminalDisplay().approve_action({"tool": "read_file"})

    assert decision.instruction == response
    out = capsys.readouterr().out
    assert "User note: Use a narrower change." in out
    assert "…" in out
    assert "\nThis second line should reach the model" not in out


def test_approve_action_uses_multiline_prompt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts: list[AnyFormattedText] = []

    def fake_input(prompt: AnyFormattedText) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", fake_input)

    assert (
        TerminalDisplay().approve_action(
            {
                "tool": "run_command",
                "args": {"command": "python -m pytest -q"},
            }
        )
        .approved
        is True
    )

    assert capsys.readouterr().out == _approval_panel_output(
        "run_command",
        "Action",
        "python -m pytest -q",
    )
    assert prompts == [_approval_prompt()]


@pytest.mark.parametrize(
    ("action", "tool", "label", "value"),
    [
        (
            {"tool": "read_file", "args": {"path": "kanban_toy2/index.html"}},
            "read_file",
            "Path",
            "kanban_toy2/index.html",
        ),
        (
            {"tool": "write_file", "args": {"path": "kanban_toy2/index.html"}},
            "write_file",
            "Path",
            "kanban_toy2/index.html",
        ),
        (
            {"tool": "run_command", "args": {"command": "mkdir -p /some/path"}},
            "run_command",
            "Action",
            "mkdir -p /some/path",
        ),
    ],
)
def test_approve_action_uses_boxed_panel_for_common_tools(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: dict,
    tool: str,
    label: str,
    value: str,
) -> None:
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: "")

    TerminalDisplay().approve_action(action)

    assert capsys.readouterr().out == _approval_panel_output(tool, label, value)


@pytest.mark.parametrize(
    "action",
    [
        {
            "tool": "run_command",
            "args": {
                "command": (
                    "python -m pytest tests/test_terminal.py "
                    "--some-extremely-long-option-name with-a-very-long-value"
                )
            },
        },
        {
            "tool": "write_file",
            "args": {
                "path": (
                    "/tmp/code-squid-workspace/projects/very/deep/example/"
                    "kanban_toy2/subdirectory/index.html"
                )
            },
        },
    ],
)
def test_approval_panel_truncates_long_command_or_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: dict,
) -> None:
    prompts: list[AnyFormattedText] = []

    def fake_input(prompt: AnyFormattedText) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", fake_input)

    TerminalDisplay().approve_action(action)

    out = capsys.readouterr().out
    if action["tool"] == "run_command":
        assert "…" in out
    else:
        assert "subdirectory/index.html" in out
    for line in out.splitlines():
        assert len(line) <= len(RUN_DETAIL_INDENT) + APPROVAL_PANEL_WIDTH
    assert len(prompts) == 1
    assert all(
        len(line) <= len(RUN_DETAIL_INDENT) + APPROVAL_PANEL_WIDTH + 1
        for line in _prompt_plain_text(prompts[0]).splitlines()
    )


def test_approval_panel_colors_only_structural_borders_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts: list[AnyFormattedText] = []

    def fake_input(prompt: AnyFormattedText) -> str:
        prompts.append(prompt)
        return ""

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", fake_input)

    TerminalDisplay(show_transcript=True).approve_action(
        {"tool": "write_file", "args": {"path": "kanban_toy2/index.html"}}
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"{RUN_DETAIL_INDENT}{SOFT_CYAN_STYLE}╭─ approval required ")
    assert lines[0].endswith(f"╮{RESET_STYLE}")
    assert lines[1].startswith(f"{RUN_DETAIL_INDENT}{SOFT_CYAN_STYLE}│{RESET_STYLE} Tool:")
    assert lines[1].endswith(f"{SOFT_CYAN_STYLE}│{RESET_STYLE}")
    assert f"{SOFT_CYAN_STYLE}Tool" not in lines[1]
    assert lines[3] == f"{RUN_DETAIL_INDENT}{SOFT_CYAN_STYLE}╰{'─' * (APPROVAL_PANEL_WIDTH - 2)}╯{RESET_STYLE}"
    assert prompts == [_approval_prompt()]


def test_approve_action_compacts_approved_panel_in_interactive_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_input(prompt: AnyFormattedText) -> str:
        print(_prompt_plain_text(prompt))
        return ""

    action = {"tool": "run_command", "args": {"command": "python -m pytest -q"}}
    display = TerminalDisplay()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", fake_input)

    assert display.approve_action(action).approved is True

    out = capsys.readouterr().out
    assert out.count("\033[1A\r\033[2K") == 6
    assert "✅ Approved" not in out
    assert "🚫 Denied" not in out
    assert "💬 User note" not in out
    assert out.endswith("\033[1A\r\033[2K")

    display.tool_result(action, {"ok": True, "output": ""})

    assert capsys.readouterr().out == (
        f"{DIM_STYLE}{RUN_DETAIL_INDENT}💿 Ran: python -m pytest{RESET_STYLE}\n"
    )


def test_approve_action_compacts_denied_panel_with_short_path_in_interactive_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_input(prompt: AnyFormattedText) -> str:
        print(_prompt_plain_text(prompt))
        return "use the existing directory"

    action = {
        "tool": "write_file",
        "args": {
            "path": (
                "/tmp/code-squid-workspace/projects/very/deep/example/"
                "kanban_toy2/subdirectory/index.html"
            )
        },
    }
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", fake_input)

    decision = TerminalDisplay().approve_action(action)

    assert decision.approved is False
    assert decision.instruction == "use the existing directory"

    out = capsys.readouterr().out
    assert out.count("\033[1A\r\033[2K") == 6
    assert "approval required" not in out.split("\033[2K")[-1]
    assert out.endswith(
        f"{SOFT_CYAN_STYLE}{RUN_DETAIL_INDENT}"
        "💬 User note: use the existing directory"
        f"{RESET_STYLE}\n"
    )


def test_compact_denial_suppresses_duplicate_denied_tool_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_input(prompt: AnyFormattedText) -> str:
        print(_prompt_plain_text(prompt))
        return "try reading first"

    action = {"tool": "write_file", "args": {"path": "kanban_toy2/index.html"}}
    display = TerminalDisplay()
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", fake_input)

    assert display.approve_action(action).approved is False
    capsys.readouterr()

    display.tool_result(action, {"ok": False, "error": USER_DENIED_TOOL_ACTION})

    assert capsys.readouterr().out == ""


def test_action_started_is_quiet_in_normal_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().action_started(
        {"tool": "write_file", "args": {"path": "kanban_toy2/app.js"}}
    )

    assert capsys.readouterr().out == ""


def test_normal_thinking_starts_spinner_without_printing_working(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.thinking()
    display.thinking()

    assert spinner.starts == 2
    assert spinner.stops == 0
    assert capsys.readouterr().out == ""


def test_thinking_after_visible_tool_result_prints_one_leading_blank(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.tool_result(
        {"tool": "run_command", "args": {"command": "ls tests"}},
        {"ok": True, "output": ""},
    )
    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}🔎 Listed files\n"

    display.thinking()
    display.thinking()

    assert spinner.starts == 2
    assert spinner.stops == 1
    assert capsys.readouterr().out == "\n"


def test_first_thinking_after_startup_scene_does_not_print_extra_blank(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.start()
    assert capsys.readouterr().out == ""

    display.thinking()

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == ""


def test_display_marks_temporary_scene_ownership_without_rendering(capsys) -> None:
    header = FakeHeader()
    display = TerminalDisplay(_header=header)

    display.start()
    display.run_started()
    display.stop_header()

    assert header.startup_infos == [None]
    assert display.session_scene_active is False
    assert capsys.readouterr().out == "\n"


def test_display_retires_and_restarts_one_session_scene(capsys) -> None:
    header = FakeHeader()
    display = TerminalDisplay(_header=header)

    display.start()
    display.retire_session_scene()
    display.retire_session_scene()
    display.start_session_scene()
    display.start_session_scene()

    assert header.startup_infos == [None, None]
    assert display.session_scene_active is True
    assert capsys.readouterr().out == ""


def test_display_updates_specialization_used_by_later_scene_frames() -> None:
    header = FakeHeader()
    display = TerminalDisplay(
        startup_info=StartupInfo(Path("workspace"), "provider", "model", "yolo"),
        _header=header,
    )

    display.set_specialization(mod_name="review-pack", skill_name=None)

    assert display.startup_info is not None
    assert display.startup_info.mod_name == "review-pack"
    assert header.startup_infos[-1] == display.startup_info


def test_startup_prepares_rain_model_without_printing_legacy_branding(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().start()

    output = capsys.readouterr().out
    assert output == ""
    assert "██████" not in output
    assert "A small coding agent with tentacles." not in output


def test_startup_panel_contains_five_default_rows_and_concise_workspace() -> None:
    info = StartupInfo(
        directory=Path("/tmp/project"),
        provider="openai_compatible",
        model="qwen3.5-9b",
        approval_mode="yolo",
    )
    panel = TerminalDisplay()._startup_info_panel(
        info
    )

    assert "Provider  openai_compatible" in panel
    assert "Model     qwen3.5-9b" in panel
    assert "Safety    yolo" in panel
    assert "Mod       none" in panel
    assert "Workspace project" in panel
    assert str(info.directory) not in panel
    assert "Enter send" not in panel
    assert "Controls" not in panel
    assert any(line.lstrip().startswith("╭") for line in panel.splitlines())
    assert any(line.lstrip().startswith("╰") for line in panel.splitlines())


def test_startup_panel_preserves_blank_rows_between_every_menu_item() -> None:
    panel = startup_info_panel(
        StartupInfo(Path("code-squid"), "provider", "model", "balanced"),
        terminal_columns=80,
    )
    owned_lines = [line.lstrip() for line in panel.splitlines()]

    assert len(owned_lines) == 13
    assert all(line == f"│{' ' * 38}│" for line in owned_lines[1:-1:2])


def test_startup_panel_includes_active_skill_when_set() -> None:
    panel = TerminalDisplay()._startup_info_panel(
        StartupInfo(
            directory=Path("/tmp/project"),
            provider="openai_compatible",
            model="qwen3.5-9b",
            approval_mode="yolo",
            skill_name="user-review",
        )
    )

    assert "Skill     user-review" in panel
    assert "Mod       none" in panel
    assert len(panel.splitlines()) == 15


def test_startup_panel_uses_actual_mod_without_duplicate_skill_row() -> None:
    panel = startup_info_panel(
        StartupInfo(
            directory=Path("/tmp/project"),
            provider="openai_compatible",
            model="qwen3.5-9b",
            approval_mode="yolo",
            skill_name="review-skill",
            mod_name="review-pack",
        ),
    )

    assert "Mod       review-pack" in panel
    assert "Skill" not in panel


def test_startup_panel_is_centered_and_adapts_to_supported_narrow_width() -> None:
    panel = startup_info_panel(
        StartupInfo(
            directory=Path("/tmp/project"),
            provider="openai_compatible",
            model="qwen3.5-9b",
            approval_mode="yolo",
        ),
        terminal_columns=24,
    )

    lines = panel.splitlines()
    assert all(len(line) <= 23 for line in lines)
    assert lines[0] == f"╭{'─' * 21}╮"
    assert lines[-1] == f"╰{'─' * 21}╯"


@pytest.mark.parametrize(
    ("path", "expected"),
    [(Path("/tmp/project"), "project"), (Path("/"), "\\")],
)
def test_concise_workspace_name_handles_normal_and_root_paths(
    path: Path,
    expected: str,
) -> None:
    # pathlib uses the host platform, so the root spelling here is Windows.
    assert concise_workspace_name(path) == expected


def test_startup_panel_items_have_stable_menu_order() -> None:
    labels = [
        label
        for label, _ in startup_panel_items(
            StartupInfo(Path("workspace"), "provider", "model", "balanced")
        )
    ]

    assert labels == ["Provider", "Model", "Safety", "Mod", "Workspace"]


def test_short_path_prefers_startup_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('hello')\n", encoding="utf-8")
    display = TerminalDisplay(
        startup_info=StartupInfo(
            directory=workspace,
            provider="openai_compatible",
            model="qwen3.5-9b",
            approval_mode="yolo",
        )
    )

    assert display._short_path(str(target)) == "src/app.py"


def test_soft_color_constants_derive_expected_ansi_styles() -> None:
    assert SOFT_CYAN_HEX == "#7dd3fc"
    assert SOFT_GREEN_HEX == "#86efac"
    assert SOFT_YELLOW_HEX == "#ffea80"
    assert SOFT_RED_HEX == "#f77998"
    assert SOFT_CYAN_STYLE == "\033[38;2;125;211;252m"
    assert SOFT_GREEN_STYLE == "\033[38;2;134;239;172m"
    assert SOFT_YELLOW_STYLE == "\033[38;2;255;234;128m"
    assert SOFT_RED_STYLE == "\033[38;2;247;121;152m"


def test_mod_accent_palette_uses_exact_product_colors() -> None:
    assert MOD_ACCENT_HEX == {
        "cyan": "#3edcff",
        "blue": "#5d9cff",
        "green": "#55e6a5",
        "yellow": "#ffe06a",
        "orange": "#ff9b55",
        "red": "#ff6475",
        "pink": "#ff75c8",
        "purple": "#bd88ff",
        "white": "#f4fbff",
        "gray": "#a8b7c5",
    }


@pytest.mark.parametrize(("name", "expected"), MOD_ACCENT_HEX.items())
def test_supported_mod_accent_names_resolve(name: str, expected: str) -> None:
    assert mod_accent_hex(name) == expected


def test_accent_squid_uses_text_presentation_sequence() -> None:
    assert SQUID_GLYPH == "\U0001f991\ufe0e"


@pytest.mark.parametrize("accent", [None, "unknown", "#bd88ff"])
def test_missing_unknown_or_hex_mod_accent_falls_back_to_cyan(accent) -> None:
    # Metadata remains semantic: arbitrary hex strings are not palette names.
    assert mod_accent_hex(accent) == "#3edcff"


def test_no_active_or_unknown_mod_uses_default_accent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("code_squid.console.ui.display.discover_mods", lambda home: {})

    assert _accent_for_mod(None) == "#3edcff"
    assert _accent_for_mod("missing") == "#3edcff"


def test_missing_or_invalid_active_mod_accent_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.ui.display.discover_mods",
        lambda home: {
            "missing": SimpleNamespace(),
            "invalid": SimpleNamespace(accent="ultraviolet"),
        },
    )

    assert _accent_for_mod("missing") == "#3edcff"
    assert _accent_for_mod("invalid") == "#3edcff"


def test_active_mod_change_updates_later_squid_glyphs_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        "code_squid.console.ui.display.discover_mods",
        lambda home: {
            "violet": SimpleNamespace(accent="purple"),
            "warm": SimpleNamespace(accent="red"),
        },
    )
    menu = SimpleNamespace(mod_name="violet")
    header = FakeHeader()
    header.startup_menu = menu
    display = TerminalDisplay(debug=True, _header=header)

    display.thinking()
    display.assistant_message("First narration.")
    menu.mod_name = "warm"
    display.final_message("Finished.")
    display.loop_finished(empty_session())

    output = capsys.readouterr().out
    purple_squid = f"{ansi_fg('#bd88ff')}{SQUID_GLYPH}{RESET_STYLE}"
    red_squid = f"{ansi_fg('#ff6475')}{SQUID_GLYPH}{RESET_STYLE}"
    assert f"{purple_squid} Thinking..." in output
    assert f"{purple_squid} First narration." in output
    assert f"{red_squid} Report:" in output
    assert f"{ansi_fg('#bd88ff')}{SQUID_GLYPH} First" not in output
    assert f"{ansi_fg('#ff6475')}{SQUID_GLYPH} Report" not in output


def test_mod_accent_does_not_theme_tool_or_changed_file_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(
        "code_squid.console.ui.display.discover_mods",
        lambda home: {"violet": SimpleNamespace(accent="purple")},
    )
    header = FakeHeader()
    header.startup_menu = SimpleNamespace(mod_name="violet")
    display = TerminalDisplay(_header=header)

    display.tool_result({"tool": "read_file", "args": {"path": "app.py"}}, {"ok": True})
    display.loop_finished(
        SimpleNamespace(files_read={"app.py"}, files_written={"app.py"}, messages=[])
    )

    output = capsys.readouterr().out
    # TTY border styling inserts ANSI resets between the border and its padding.
    assert "  Changed files" in output
    assert "🗂️" not in output
    accented_squid = f"{ansi_fg('#bd88ff')}{SQUID_GLYPH}{RESET_STYLE}"
    assert output.count(ansi_fg("#bd88ff")) == 1
    assert accented_squid in output
    assert f"{ansi_fg('#bd88ff')}╭" not in output


def test_default_spinner_uses_default_mod_accent(monkeypatch: pytest.MonkeyPatch) -> None:
    spinner_kwargs = []

    class CapturingSpinner(FakeSpinner):
        def __init__(self, **kwargs) -> None:
            super().__init__()
            spinner_kwargs.append(kwargs)

    monkeypatch.setattr("code_squid.console.ui.display.TerminalSpinner", CapturingSpinner)

    TerminalDisplay()

    assert spinner_kwargs == [
        {
            "enabled": True,
            "prefix": RUN_EVENT_INDENT,
            "style": ansi_fg(DEFAULT_MOD_ACCENT_HEX),
        }
    ]


def test_run_started_uses_blank_spacing_without_a_divider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    TerminalDisplay().run_started()

    output = capsys.readouterr().out
    assert output == "\n"
    assert "starting run" not in output
    assert "─" * RUN_PANEL_WIDTH not in output
    assert ansi_fg(DEFAULT_MOD_ACCENT_HEX) not in output


def test_run_panel_uses_the_existing_canonical_rail_width() -> None:
    assert RUN_PANEL_WIDTH == 61


def test_model_request_failed_prints_short_message_with_log_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().model_request_failed(Path(".code-squid/logs/latest.log"))

    assert capsys.readouterr().out == (
        "🚫 Model request failed\n"
        "\n"
        "Code Squid could not get a response from the configured model provider.\n"
        "Details saved to: .code-squid/logs/latest.log\n"
    )


def test_read_write_action_started_is_quiet_in_debug_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay(debug=True)

    display.action_started({"tool": "read_file", "args": {"path": "kanban_toy2/app.js"}})
    display.action_started({"tool": "write_file", "args": {"path": "kanban_toy2/app.js"}})

    assert capsys.readouterr().out == ""


def test_run_command_action_started_still_prints_in_debug_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay(debug=True).action_started(
        {"tool": "run_command", "args": {"command": "python -m pytest -q"}}
    )

    assert capsys.readouterr().out == "💿 Run: python -m pytest\n"


def test_debug_reply_prints_boxed_model_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay(debug=True).debug_reply(
        {
            "actions": [
                {
                    "tool": "read_file",
                    "args": {"path": "/tmp/project/calculator.py"},
                    "tool_call_id": "call_123",
                    "raw_arguments": '{"path": "/tmp/project/calculator.py"}',
                }
            ]
        }
    )

    output = capsys.readouterr().out
    assert "┌─ model action " in output
    assert "│ tool: read_file" in output
    assert "│ path: " in output
    assert "│ tool_call_id: call_123" in output
    assert "actions: [" not in output
    assert "raw_arguments" not in output


def test_debug_block_colors_structural_rails_cyan_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    TerminalDisplay(debug=True)._debug_block("model action", ["tool: read_file"])

    output = capsys.readouterr().out
    assert output.startswith(f"{SOFT_CYAN_STYLE}┌─ model action ")
    assert f"\n{SOFT_CYAN_STYLE}│{RESET_STYLE} tool: read_file\n" in output
    assert output.rstrip().endswith(f"─{RESET_STYLE}")
    assert f"{SOFT_CYAN_STYLE}tool: read_file" not in output


def test_debug_reply_prints_none_for_no_actions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay(debug=True).debug_reply({"actions": []})

    output = capsys.readouterr().out
    assert "┌─ model action " in output
    assert "│ none" in output


def test_reply_rejected_prints_friendly_nudge_for_empty_final_reply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().reply_rejected("empty_final_reply")

    assert capsys.readouterr().out == (
        f"{RUN_DETAIL_INDENT}↪ Asking model to continue or finalize…\n"
    )


def test_reply_rejected_colors_friendly_nudge_yellow_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    TerminalDisplay().reply_rejected("empty_final_reply")

    assert capsys.readouterr().out == (
        f"{SOFT_YELLOW_STYLE}{RUN_DETAIL_INDENT}↪ Asking model to continue or finalize…"
        f"{RESET_STYLE}\n"
    )


def test_debug_reply_rejected_keeps_raw_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay(debug=True).reply_rejected("empty_final_reply")

    assert capsys.readouterr().out == (
        "⚠️ Reply rejected: empty_final_reply\n"
    )


def test_approve_action_still_prints_requested_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: "")

    TerminalDisplay().approve_action(
        {"tool": "write_file", "args": {"path": "kanban_toy2/app.js"}}
    )

    assert capsys.readouterr().out == _approval_panel_output(
        "write_file",
        "Path",
        "kanban_toy2/app.js",
    )


def test_outside_absolute_path_uses_parent_file_label(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().tool_result(
        {
            "tool": "read_file",
            "args": {
                "path": "/tmp/code-squid-workspace/pomodoro_timer/index.html",
            },
        },
        {"ok": True},
    )

    assert capsys.readouterr().out == (
        f"{RUN_DETAIL_INDENT}📖 Read: pomodoro_timer/index.html\n"
    )


def test_repo_local_path_becomes_relative(capsys: pytest.CaptureFixture[str]) -> None:
    TerminalDisplay().tool_result(
        {
            "tool": "read_file",
            "args": {"path": str(Path.cwd() / "ui/terminal.py")},
        },
        {"ok": True},
    )

    assert capsys.readouterr().out == (
        f"{RUN_DETAIL_INDENT}📖 Read: ui/terminal.py\n"
    )


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("pytest -q", "💿 Ran: pytest\n"),
        ("python -m pytest -q tests", "💿 Ran: python -m pytest\n"),
    ],
)
def test_pytest_command_success_label_is_compact(
    capsys: pytest.CaptureFixture[str],
    command: str,
    expected: str,
) -> None:
    TerminalDisplay().tool_result(
        {"tool": "run_command", "args": {"command": command}},
        {"ok": True, "output": ""},
    )

    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}{expected}"


@pytest.mark.parametrize(
    ("command", "success_label"),
    [
        ("find . -name '*.py'", "🔎 Searched files\n"),
        ("rg TODO", "🔎 Searched files\n"),
        ("grep -R TODO .", "🔎 Searched files\n"),
        ("ls tests", "🔎 Listed files\n"),
    ],
)
def test_search_and_list_commands_use_compact_success_labels(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    success_label: str,
) -> None:
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: "")
    action = {"tool": "run_command", "args": {"command": command}}

    TerminalDisplay().approve_action(action)
    assert capsys.readouterr().out == _approval_panel_output(
        "run_command",
        "Action",
        command,
    )

    TerminalDisplay().tool_result(action, {"ok": True, "output": ""})
    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}{success_label}"


@pytest.mark.parametrize(
    ("command", "success_label"),
    [
        ("rg TODO", "🔎 Searched files"),
        ("ls tests", "🔎 Listed files"),
    ],
)
def test_search_and_list_success_labels_are_dim_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    success_label: str,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    TerminalDisplay().tool_result(
        {"tool": "run_command", "args": {"command": command}},
        {"ok": True, "output": ""},
    )

    assert capsys.readouterr().out == (
        f"{DIM_STYLE}{RUN_DETAIL_INDENT}{success_label}{RESET_STYLE}\n"
    )


def test_write_file_result_prints_one_success_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "write_file", "args": {"path": "kanban_toy2/app.js"}}
    display = TerminalDisplay()

    display.action_started(action)
    display.tool_result(action, {"ok": True})

    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}📝 Wrote: kanban_toy2/app.js\n"


def test_run_command_result_prints_one_success_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "run_command", "args": {"command": "node --check app.js"}}
    display = TerminalDisplay()

    display.action_started(action)
    display.tool_result(action, {"ok": True, "output": ""})

    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}💿 Ran: node --check app.js\n"


def test_successful_unknown_tool_result_prints_compact_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().tool_result(
        {"tool": "ls", "args": {"path": "/tmp/project"}},
        {
            "ok": True,
            "tool": "ls",
            "message": (
                "Listed 4 entries from "
                "/home/aaron/Desktop/coding_agent_eval_repos/02_two_file_dependency"
            ),
            "data": {"entries": [{"name": "README.md", "type": "file"}]},
        },
    )

    assert capsys.readouterr().out == (
        f"{RUN_DETAIL_INDENT}"
        "✅ ls completed: Listed 4 entries from "
        "/home/aaron/Desktop/coding_agent_eval_repos/02_two_file_dependency\n"
    )


def test_tool_result_followed_by_assistant_message_has_one_blank_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()

    display.tool_result(
        {"tool": "run_command", "args": {"command": "ls tests"}},
        {"ok": True, "output": ""},
    )
    display.assistant_message("The directory doesn't exist yet.")

    output = capsys.readouterr().out
    assert output.startswith(f"{RUN_DETAIL_INDENT}🔎 Listed files\n\n╭")
    assert f"│  {SQUID_GLYPH} The directory doesn't exist yet." in output


def test_assistant_message_followed_by_tool_result_has_blank_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()

    display.assistant_message("Directory created.")
    display.tool_result(
        {"tool": "write_file", "args": {"path": "kanban_toy2/index.html"}},
        {"ok": True},
    )

    output = capsys.readouterr().out
    assert output.startswith("╭")
    assert f"│  {SQUID_GLYPH} Directory created." in output
    assert output.endswith(f"\n\n{RUN_DETAIL_INDENT}📝 Wrote: kanban_toy2/index.html\n")


def test_first_visible_output_after_startup_has_no_extra_leading_blank(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()

    display.start()
    display.tool_result(
        {"tool": "run_command", "args": {"command": "ls tests"}},
        {"ok": True, "output": ""},
    )

    assert capsys.readouterr().out == (
        f"{RUN_DETAIL_INDENT}🔎 Listed files\n"
    )


def test_run_command_result_prints_one_test_summary_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "run_command", "args": {"command": "pytest -q"}}
    display = TerminalDisplay()

    display.action_started(action)
    display.tool_result(action, {"ok": True, "output": "2 passed in 0.01s"})

    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}🧪 Tests passed: 2 passed\n"


def test_tests_passed_line_is_green_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    TerminalDisplay().tool_result(
        {"tool": "run_command", "args": {"command": "pytest -q"}},
        {"ok": True, "output": "2 passed in 0.01s"},
    )

    assert capsys.readouterr().out == (
        f"{SOFT_GREEN_STYLE}{RUN_DETAIL_INDENT}🧪 Tests passed: 2 passed{RESET_STYLE}\n"
    )


def test_command_failure_line_is_red_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    TerminalDisplay().tool_result(
        {"tool": "run_command", "args": {"command": "pytest -q"}},
        {"ok": False, "output": ""},
    )

    assert capsys.readouterr().out == (
        f"{SOFT_RED_STYLE}{RUN_DETAIL_INDENT}❌ Command failed: pytest{RESET_STYLE}\n"
    )


def test_debug_read_file_result_omits_full_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "read_file", "args": {"path": "/tmp/project/calculator.py"}}
    result = {
        "ok": True,
        "tool": "read_file",
        "path": "/tmp/project/calculator.py",
        "content": "SECRET FILE CONTENT",
        "content_truncated": False,
        "content_original_chars": 19,
        "content_returned_chars": 19,
        "start_line": 1,
        "end_line": 3,
        "total_lines": 3,
    }

    TerminalDisplay(debug=True).tool_result(action, result)

    output = capsys.readouterr().out
    assert "📖 Read:" in output
    assert "┌─ tool result " in output
    assert "│ ok: true" in output
    assert "│ tool: read_file" in output
    assert "│ chars: 19 / 19" in output
    assert "│ lines: 1-3 / 3" in output
    assert "SECRET FILE CONTENT" not in output
    assert "tool result: {" not in output


def test_debug_failed_read_file_result_shows_error_not_empty_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "read_file", "args": {"path": "/tmp/project/missing.py"}}
    result = {
        "ok": False,
        "tool": "read_file",
        "path": "/tmp/project/missing.py",
        "error": "file not found",
    }

    TerminalDisplay(debug=True).tool_result(action, result)

    output = capsys.readouterr().out
    assert "❌ Read failed:" in output
    assert "│ ok: false" in output
    assert "│ tool: read_file" in output
    assert "│ error: file not found" in output
    assert "│ chars:" not in output
    assert "│ lines:" not in output


def test_debug_failed_write_file_result_shows_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "write_file", "args": {"path": "/tmp/project/app.py"}}
    result = {
        "ok": False,
        "tool": "write_file",
        "path": "/tmp/project/app.py",
        "error": "permission denied",
    }

    TerminalDisplay(debug=True).tool_result(action, result)

    output = capsys.readouterr().out
    assert "❌ Write failed:" in output
    assert "│ ok: false" in output
    assert "│ tool: write_file" in output
    assert "│ error: permission denied" in output
    assert "│ characters_written:" not in output
    assert "│ summary:" not in output


def test_debug_run_command_result_omits_full_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "run_command", "args": {"command": "pytest -q"}}
    result = {
        "ok": True,
        "tool": "run_command",
        "output": "SECRET COMMAND OUTPUT\n2 passed in 0.01s",
        "output_truncated": False,
        "output_original_chars": 36,
        "output_returned_chars": 36,
        "returncode": 0,
        "timed_out": False,
    }

    TerminalDisplay(debug=True).tool_result(action, result)

    output = capsys.readouterr().out
    assert "🧪 Tests passed: 2 passed" in output
    assert "┌─ tool result " in output
    assert "│ returncode: 0" in output
    assert "│ timed_out: false" in output
    assert "│ chars: 36 / 36" in output
    assert "│ pytest: 2 passed" in output
    assert "SECRET COMMAND OUTPUT" not in output
    assert "tool result: {" not in output


def test_normal_non_tty_thinking_does_not_print_working(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().thinking()
    TerminalDisplay().thinking()

    assert capsys.readouterr().out == ""


def test_debug_thinking_is_plain_and_does_not_animate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()

    TerminalDisplay(debug=True, _spinner=spinner).thinking()

    assert spinner.starts == 0
    assert spinner.stops == 0
    assert capsys.readouterr().out == f"{SQUID_GLYPH} Thinking...\n\n"


def test_assistant_message_stops_spinner_before_printing_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.thinking()
    display.assistant_message("The directory doesn't exist yet.")

    assert spinner.starts == 1
    assert spinner.stops == 1
    output = capsys.readouterr().out
    assert f"│  {SQUID_GLYPH} The directory doesn't exist yet." in output
    assert output.count("╭") == output.count("╰") == 1


def test_normal_assistant_message_uses_squid_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message("The directory doesn't exist yet.")

    output = capsys.readouterr().out
    assert f"│  {SQUID_GLYPH} The directory doesn't exist yet." in output
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in output.splitlines())


def test_assistant_message_does_not_hide_fallback_like_narration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message("Using read_file.")

    output = capsys.readouterr().out
    assert f"│  {SQUID_GLYPH} Using read_file." in output


def test_multiline_assistant_message_indents_continuation_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message(
        "The directory doesn't exist yet.\n"
        "I need to create it and then build the Kanban board."
    )

    output = capsys.readouterr().out
    assert f"│  {SQUID_GLYPH} The directory doesn't exist yet." in output
    assert "│     I need to create it and then build the Kanban board." in output


def test_assistant_message_wraps_to_fixed_panel_width(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "code_squid.console.ui.formatting.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((44, 24)),
    )

    TerminalDisplay().assistant_message(
        "This assistant narration line should wrap cleanly under the squid marker."
    )

    output = capsys.readouterr().out
    lines = output.splitlines()
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)
    assert f"│  {SQUID_GLYPH} This assistant narration line should wrap cleanly" in output
    assert "│     under the squid marker." in output


def test_multiple_narration_messages_use_separate_equal_width_panels(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()

    display.assistant_message("Short.")
    display.assistant_message("A second narration message in its own box.")

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line]
    assert sum(line.startswith("╭") for line in lines) == 2
    assert sum(line.startswith("╰") for line in lines) == 2
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)
    assert "╯\n\n╭" in output


def test_long_unbroken_narration_wraps_without_expanding_panel(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message("x" * 140)

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) > 3
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)


def test_wide_character_narration_stays_within_panel_cells(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message("漢" * 80)

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) > 3
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)


def test_tool_result_remains_outside_narration_panel(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    display.assistant_message("I'll write the file.")
    display.tool_result(
        {"tool": "write_file", "args": {"path": "notes.txt"}},
        {"ok": True},
    )

    output = capsys.readouterr().out
    panel_end = output.index("╯\n")
    tool_index = output.index("📝 Wrote: notes.txt")
    assert tool_index > panel_end
    assert "│    📝 Wrote" not in output


def test_tool_result_stops_spinner_before_printing_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.thinking()
    display.tool_result(
        {"tool": "write_file", "args": {"path": "kanban_toy2/index.html"}},
        {"ok": True},
    )

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == (
        f"{RUN_DETAIL_INDENT}📝 Wrote: kanban_toy2/index.html\n"
    )


def test_approval_prompt_stops_spinner_before_asking(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: "stop")

    display.thinking()
    assert display.approve_action({"tool": "read_file"}).approved is False

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == (
        _approval_panel_output("read_file", "Path", "")
        + f"{RUN_DETAIL_INDENT}💬 User note: stop\n"
    )


def test_approval_prompt_shows_short_outside_workspace_reason(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reason = (
        "Requested path is outside the workspace root: /tmp/code-squid-workspace/circus.md "
        "(workspace root: /tmp/code-squid-workspace/projects). "
        "Approval is required unless approval_mode=never."
    )
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: "")

    TerminalDisplay(
        startup_info=StartupInfo(
            directory=Path("/tmp/code-squid-workspace/projects"),
            provider="openai",
            model="gpt-5",
            approval_mode="on-request",
        )
    ).approve_action(
        {
            "tool": "read_file",
            "args": {"path": "/tmp/code-squid-workspace/circus.md"},
            "approval_reason": reason,
        }
    )

    output = capsys.readouterr().out
    assert "Reason:" in output
    assert "Outside workspace" in output
    assert "Path:" in output
    assert "code-squid-workspace/circus.md" in output
    assert "Requested path is outside the workspace root" not in output
    assert "Approval is required unless approval_mode=never" not in output
    assert "Requested path:" not in output
    assert "Workspace root:" not in output


def test_approval_prompt_preserves_ctrl_c_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(prompt: str) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", interrupt)

    with pytest.raises(KeyboardInterrupt):
        TerminalDisplay().approve_action({"tool": "read_file"})


def test_approval_prompt_follows_assistant_with_single_blank(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("code_squid.console.ui.display.prompt_multiline_input", lambda prompt: "")
    display = TerminalDisplay()

    display.assistant_message("I'll inspect the file.")
    display.approve_action({"tool": "read_file"})

    output = capsys.readouterr().out
    narration_end = output.index("╯\n") + len("╯\n")
    assert output[narration_end:].startswith("\n" + _approval_panel_output("read_file", "Path", ""))


def test_interrupted_stops_spinner_before_printing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.thinking()
    display.interrupted()

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}⏹️ Interrupted\n"


def test_generic_long_command_gets_middle_truncated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = "printf '" + ("x" * 140) + "'"
    action = {"tool": "run_command", "args": {"command": command}}

    TerminalDisplay().tool_result(action, {"ok": True, "output": ""})

    output = capsys.readouterr().out
    assert output.startswith(f"{RUN_DETAIL_INDENT}💿 Ran: printf '")
    assert "…" in output
    assert len(output.removesuffix("\n")) <= len(RUN_DETAIL_INDENT) + len("💿 Ran: ") + 80


def test_normal_completion_omits_redundant_success_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SimpleNamespace(files_read=set(), files_written=set(), messages=[])

    TerminalDisplay().loop_finished(session)

    output = capsys.readouterr().out
    assert "✅ Done!" not in output
    assert "Changed files" not in output


@pytest.mark.parametrize(
    ("run_result", "expected"),
    [
        (RunResult(status="complete"), None),
        (RunResult(status="failed", reason="invalid reply"), "❌ Session failed"),
        (RunResult(status="interrupted", reason="user interrupted"), "⚠️ Session interrupted"),
    ],
)
def test_loop_Done_prints_status_label(
    capsys: pytest.CaptureFixture[str],
    run_result: RunResult,
    expected: str | None,
) -> None:
    session = SimpleNamespace(files_read=set(), files_written=set(), messages=[])

    TerminalDisplay().loop_finished(session, run_result)

    output = capsys.readouterr().out
    if expected is not None:
        assert expected in output
    assert "✅ Done!" not in output


def test_loop_finished_prints_only_changed_files_in_shared_completion_panel(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SimpleNamespace(
        files_read={"read-only.py"},
        files_written={"app.py"},
        messages=[],
    )

    TerminalDisplay().loop_finished(session)

    output = capsys.readouterr().out
    lines = output.strip().splitlines()
    assert lines[0] == f"╭{'─' * (RUN_PANEL_WIDTH - 2)}╮"
    assert lines[-1] == f"╰{'─' * (RUN_PANEL_WIDTH - 2)}╯"
    assert f"│  {SQUID_GLYPH} Report:" in output
    assert "│  Changed files" in output
    assert "🗂️" not in output
    assert "      app.py" in output
    assert "read-only.py" not in output
    assert "Read" not in output
    assert "Written" not in output
    assert "─" * RUN_PANEL_WIDTH not in output
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)


def test_completion_panel_keeps_edges_aligned_across_unicode_and_styling(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    path = str(tmp_path / "wide-漢-file.py")
    session = SimpleNamespace(
        files_read={path},
        files_written={path},
        messages=[],
    )
    display = TerminalDisplay()
    display.final_message("## What changed\n- **Styled report** with 🚫 content.")
    display.loop_finished(session)

    lines = capsys.readouterr().out.strip().splitlines()
    assert any(SQUID_GLYPH in line and "Report:" in line for line in lines)
    changed_files_index = next(
        index for index, line in enumerate(lines) if "Changed files" in line
    )
    assert lines[changed_files_index - 1]
    assert lines[changed_files_index + 1]
    assert _display_width(lines[changed_files_index - 1]) == RUN_PANEL_WIDTH
    assert _display_width(lines[changed_files_index]) == RUN_PANEL_WIDTH
    assert _display_width(lines[changed_files_index + 1]) == RUN_PANEL_WIDTH
    assert any("\033]8;;" in line for line in lines)
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in lines)


def test_direct_final_run_prints_one_clean_completion_panel(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    display.run_started()
    finish_display(display, "Yes.")

    output = capsys.readouterr().out
    assert output.startswith("\n╭")
    assert not output.startswith("\n\n")
    assert output.count("╭") == output.count("╰") == 1
    assert f"│  {SQUID_GLYPH} Report:" in output
    assert "Yes." in output
    assert "Changed files" not in output
    assert "─" * RUN_PANEL_WIDTH not in output


def test_completion_panel_borders_are_neutral_and_dim_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    session = SimpleNamespace(files_read=set(), files_written=set(), messages=[])

    TerminalDisplay().loop_finished(session)

    output = capsys.readouterr().out
    top = f"{DIM_STYLE}╭{'─' * (RUN_PANEL_WIDTH - 2)}╮{RESET_STYLE}"
    assert output.startswith(f"{top}\n")
    assert f"{ansi_fg(DEFAULT_MOD_ACCENT_HEX)}{SQUID_GLYPH}{RESET_STYLE}" in output
    assert f"{ansi_fg(DEFAULT_MOD_ACCENT_HEX)}╭" not in output


def test_loop_finished_prints_shortened_paths_in_final_file_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    full_path = "/tmp/code-squid-workspace/pomodoro_timer/index.html"
    session = SimpleNamespace(
        files_read={full_path},
        files_written={full_path},
        messages=[],
    )

    TerminalDisplay().loop_finished(session)

    output = capsys.readouterr().out
    assert "      pomodoro_timer/index.html" in output
    assert "\033]8" not in output
    assert full_path not in output


def test_loop_finished_prints_clickable_file_links_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    full_path = str(tmp_path / "pomodoro_timer" / "index.html")
    file_uri = Path(full_path).expanduser().resolve().as_uri()
    label = "pomodoro_timer/index.html"
    session = SimpleNamespace(
        files_read={full_path},
        files_written={full_path},
        messages=[],
    )

    TerminalDisplay().loop_finished(session)

    output = capsys.readouterr().out
    assert f"      \033]8;;{file_uri}\033\\{label}\033]8;;\033\\" in output
    assert f"\033\\{full_path}\033]8" not in output


def test_debug_loop_finished_keeps_file_paths_plain_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    full_path = str(tmp_path / "calculator.py")
    session = SimpleNamespace(
        files_read={full_path},
        files_written={full_path},
        messages=[],
    )

    TerminalDisplay(debug=True).loop_finished(session)

    output = capsys.readouterr().out
    assert all(part in output for part in ("C:\\Users", "calcula", "tor.py"))
    assert "\033]8" not in output


def test_final_message_renders_report_heading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    finish_display(display,
        "## Files changed\n"
        "- `ui/terminal.py`\n"
        "\n"
        "## What changed\n"
        "- Polished display.\n"
        "\n"
        "## Verification\n"
        "- `pytest tests/test_terminal.py`\n"
        "\n"
        "## Remaining risks / notes\n"
        "- No known remaining risks; terminal display tests passed."
    )

    output = capsys.readouterr().out
    assert f"│  {SQUID_GLYPH} Report:" in output
    assert "Changed files" not in output
    assert f"{FINAL_SUMMARY_INDENT}Files changed" in output
    assert f"{FINAL_SUMMARY_INDENT}• `ui/terminal.py`" in output
    assert f"{FINAL_SUMMARY_INDENT}What changed" in output
    assert f"{FINAL_SUMMARY_INDENT}• Polished display." in output


def test_final_message_displays_unlabeled_content_under_report_heading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    finish_display(display,
        "I ran `pwd`; the workspace is "
        "`/tmp/code-squid-workspace/projects`."
    )

    output = capsys.readouterr().out
    assert f"│  {SQUID_GLYPH} Report:" in output
    assert f"{FINAL_SUMMARY_INDENT}I ran `pwd`; the workspace is" in output
    assert f"{FINAL_SUMMARY_INDENT}`/tmp/code-squid-workspace/projects`." in output


def test_final_summary_keeps_divider_neutral_and_accents_only_squid_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    display = TerminalDisplay()
    finish_display(display,
        "## Files changed\n"
        "- `ui/terminal.py`\n"
        "## What changed\n"
        "- Polished display.\n"
        "## Verification\n"
        "- `pytest tests/test_terminal.py`\n"
        "## Remaining risks / notes\n"
        "- none"
    )

    accent_style = ansi_fg(DEFAULT_MOD_ACCENT_HEX)
    output = capsys.readouterr().out
    assert f"{accent_style}{SQUID_GLYPH}{RESET_STYLE} Report:" in output
    assert f"{accent_style}╭" not in output
    assert f"{DIM_STYLE}╭" in output


def test_final_summary_headings_are_bold_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    display = TerminalDisplay()
    finish_display(display,
        "## Files changed\n"
        "- `ui/terminal.py`\n"
        "## What changed\n"
        "- Polished display.\n"
        "## Verification\n"
        "- `pytest tests/test_terminal.py`\n"
        "## Remaining risks / notes\n"
        "- none"
    )

    output = capsys.readouterr().out
    assert f"{FINAL_SUMMARY_INDENT}{BOLD_STYLE}Files changed{RESET_STYLE}" in output
    assert f"{FINAL_SUMMARY_INDENT}• `ui/terminal.py`" in output
    assert f"{FINAL_SUMMARY_INDENT}{BOLD_STYLE}What changed{RESET_STYLE}" in output
    assert f"{FINAL_SUMMARY_INDENT}• Polished display." in output
    assert f"{FINAL_SUMMARY_INDENT}{BOLD_STYLE}Verification{RESET_STYLE}" in output
    assert f"{FINAL_SUMMARY_INDENT}{BOLD_STYLE}Remaining risks / notes{RESET_STYLE}" in output


def test_final_summary_inline_bold_markers_render_as_bold_in_tty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    display = TerminalDisplay()
    finish_display(display,
        "## What changed\n"
        "- Rendered **Markdown headings** and **bold text** in the final summary."
    )

    output = capsys.readouterr().out
    assert "**Markdown headings**" not in output
    assert "**bold text**" not in output
    assert f"{BOLD_STYLE}Markdown headings{RESET_STYLE}" in output
    assert f"{BOLD_STYLE}bold text{RESET_STYLE}" in output


def test_final_message_with_markdown_sections_preserves_preamble(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    finish_display(display,
        "All tests pass now. Let me provide the final summary.\n"
        "## Files changed\n"
        "- `ui/terminal.py`\n"
        "## What changed\n"
        "- Polished display.\n"
        "## Verification\n"
        "- `pytest tests/test_terminal.py`\n"
        "## Remaining risks / notes\n"
        "- No known remaining risks; terminal display tests passed."
    )

    output = capsys.readouterr().out
    assert "All tests pass now" in output
    assert f"{FINAL_SUMMARY_INDENT}Files changed" in output
    assert f"{FINAL_SUMMARY_INDENT}• `ui/terminal.py`" in output
    assert f"{FINAL_SUMMARY_INDENT}Verification" in output
    assert f"{FINAL_SUMMARY_INDENT}• `pytest tests/test_terminal.py`" in output
    assert f"{FINAL_SUMMARY_INDENT}Remaining risks / notes" in output


def test_final_message_renders_unordered_bullet_markers_as_terminal_bullets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    finish_display(display,
        "- dash item\n"
        "* star item\n"
        "+ plus item"
    )

    output = capsys.readouterr().out
    assert f"{FINAL_SUMMARY_INDENT}• dash item" in output
    assert f"{FINAL_SUMMARY_INDENT}• star item" in output
    assert f"{FINAL_SUMMARY_INDENT}• plus item" in output
    assert f"{FINAL_SUMMARY_INDENT}- dash item" not in output
    assert f"{FINAL_SUMMARY_INDENT}* star item" not in output
    assert f"{FINAL_SUMMARY_INDENT}+ plus item" not in output


def test_final_summary_short_unordered_bullet_renders_on_one_line() -> None:
    formatted = TerminalDisplay()._format_final_summary("- item")

    assert formatted == f"{FINAL_SUMMARY_INDENT}• item"


def test_final_summary_long_unordered_bullet_does_not_orphan_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.ui.formatting.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((20, 24)),
    )

    formatted = TerminalDisplay()._format_final_summary("- `/long/path/file.py`")

    assert f"{FINAL_SUMMARY_INDENT}•" not in formatted.splitlines()
    assert formatted == f"{FINAL_SUMMARY_INDENT}• `/long/path/file.py`"


def test_final_summary_unordered_bullet_continuation_aligns_under_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.ui.formatting.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((18, 24)),
    )

    formatted = TerminalDisplay()._format_final_summary("- short words continue here")

    assert formatted.splitlines() == [
        f"{FINAL_SUMMARY_INDENT}• short words",
        f"{FINAL_SUMMARY_INDENT}  continue here",
    ]


def test_final_summary_separates_consecutive_top_level_bullets() -> None:
    formatted = TerminalDisplay()._format_final_summary(
        "## Files changed\n"
        "- `app.py`\n"
        "- `test_app.py`\n"
        "\n"
        "## Verification\n"
        "- `pytest`\n"
        "- `node --check app.js`"
    )

    assert (
        f"{FINAL_SUMMARY_INDENT}Files changed\n"
        f"{FINAL_SUMMARY_INDENT}• `app.py`\n"
        "\n"
        f"{FINAL_SUMMARY_INDENT}• `test_app.py`\n"
        "\n"
        f"{FINAL_SUMMARY_INDENT}Verification\n"
        f"{FINAL_SUMMARY_INDENT}• `pytest`\n"
        "\n"
        f"{FINAL_SUMMARY_INDENT}• `node --check app.js`"
    ) == formatted


def test_final_summary_first_top_level_bullet_has_no_leading_blank() -> None:
    formatted = TerminalDisplay()._format_final_summary(
        "- first item\n"
        "- second item"
    )

    assert formatted.startswith(f"{FINAL_SUMMARY_INDENT}• first item\n\n")


def test_final_summary_wrapped_bullet_continuation_is_not_spaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.ui.formatting.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((38, 24)),
    )

    formatted = TerminalDisplay()._format_final_summary(
        "- This bullet line should wrap with continuation text aligned beneath the item text.\n"
        "- second item"
    )

    assert (
        f"{FINAL_SUMMARY_INDENT}• This bullet line should wrap with\n"
        f"{FINAL_SUMMARY_INDENT}  continuation text aligned beneath\n"
        f"{FINAL_SUMMARY_INDENT}  the item text.\n"
        "\n"
        f"{FINAL_SUMMARY_INDENT}• second item"
    ) == formatted


def test_final_summary_indented_bullets_rendered_as_bullets_get_spacing() -> None:
    formatted = TerminalDisplay()._format_final_summary(
        "## What changed\n"
        "- Parent item:\n"
        "  - Child one\n"
        "  - Child two\n"
        "  - Child three"
    )

    assert (
        f"{FINAL_SUMMARY_INDENT}What changed\n"
        f"{FINAL_SUMMARY_INDENT}• Parent item:\n"
        "\n"
        f"{FINAL_SUMMARY_INDENT}• Child one\n"
        "\n"
        f"{FINAL_SUMMARY_INDENT}• Child two\n"
        "\n"
        f"{FINAL_SUMMARY_INDENT}• Child three"
    ) == formatted


def test_final_message_preserves_numbered_bullet_markers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    finish_display(display,
        "1. First item\n"
        "2. Second item"
    )

    output = capsys.readouterr().out
    assert f"{FINAL_SUMMARY_INDENT}1. First item" in output
    assert f"{FINAL_SUMMARY_INDENT}2. Second item" in output


def test_final_message_preserves_multiline_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()
    finish_display(display,
        "## Files changed\n"
        "- `ui/terminal.py`\n"
        "## What changed\n"
        "Polished display\n"
        "- grouped final files\n"
        "- sectioned summary\n"
        "## Verification\n"
        "- `pytest tests/test_terminal.py`\n"
        "## Remaining risks / notes\n"
        "- none"
    )

    output = capsys.readouterr().out
    assert f"{FINAL_SUMMARY_INDENT}What changed" in output
    assert f"{FINAL_SUMMARY_INDENT}Polished display" in output
    assert f"{FINAL_SUMMARY_INDENT}• grouped final files" in output
    assert f"{FINAL_SUMMARY_INDENT}• sectioned summary" in output


def test_final_message_wraps_body_lines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "code_squid.console.ui.formatting.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((44, 24)),
    )

    display = TerminalDisplay()
    finish_display(display,
        "## Files changed\n"
        "- `ui/terminal.py`\n"
        "## What changed\n"
        "This final summary body line should wrap neatly while keeping Markdown display readable.\n"
        "## Verification\n"
        "- `pytest tests/test_terminal.py`\n"
        "## Remaining risks / notes\n"
        "- none"
    )

    output = capsys.readouterr().out
    assert f"{FINAL_SUMMARY_INDENT}This final summary body line should" in output
    assert f"{FINAL_SUMMARY_INDENT}keeping Markdown display readable." in output
    assert all(_display_width(line) == RUN_PANEL_WIDTH for line in output.strip().splitlines())


def test_final_message_wraps_unordered_bullet_continuation_under_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "code_squid.console.ui.formatting.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((38, 24)),
    )

    display = TerminalDisplay()
    finish_display(display,
        "- This bullet line should wrap with continuation text aligned beneath the item text."
    )

    output = capsys.readouterr().out
    assert f"{FINAL_SUMMARY_INDENT}• This bullet line should wrap with continuation" in output
    assert f"{FINAL_SUMMARY_INDENT}  aligned beneath the item text." in output


def test_debug_assistant_message_preserves_raw_task_complete(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay(debug=True).assistant_message("TASK COMPLETE")

    output = capsys.readouterr().out
    assert f"│  {SQUID_GLYPH} TASK COMPLETE" in output
    assert output.endswith("╯\n\n")


def test_debug_loop_finished_does_not_print_transcript_by_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SimpleNamespace(
        files_read=set(),
        files_written=set(),
        messages=[{"role": "user", "content": "secret task"}],
    )

    TerminalDisplay(debug=True).loop_finished(session)

    output = capsys.readouterr().out
    assert "✅ Done" not in output
    assert "Changed files" not in output
    assert "Full transcript:" not in output
    assert "secret task" not in output


def test_show_transcript_prints_full_transcript(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SimpleNamespace(
        files_read=set(),
        files_written=set(),
        messages=[{"role": "user", "content": "secret task"}],
    )

    TerminalDisplay(debug=True, show_transcript=True).loop_finished(session)

    output = capsys.readouterr().out
    assert "Full transcript:" in output
    assert "[user]" in output
    assert "secret task" in output


def test_interrupted_completion_does_not_print_finished(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SimpleNamespace(files_read=set(), files_written=set(), messages=[])
    display = TerminalDisplay()

    display.interrupted()
    display.loop_finished(session)

    output = capsys.readouterr().out
    assert output.startswith(f"{RUN_DETAIL_INDENT}⏹️ Interrupted\n")
    assert "✅ Done" not in output


def test_tool_result_displays_action_denied(capsys: pytest.CaptureFixture[str]) -> None:
    TerminalDisplay().tool_result(
        {"tool": "read_file"},
        {"ok": False, "error": USER_DENIED_TOOL_ACTION},
    )

    assert capsys.readouterr().out == f"{RUN_DETAIL_INDENT}🚫 Action denied\n"


def test_denied_run_command_displays_action_denied(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().tool_result(
        {"tool": "run_command"},
        {"ok": False, "error": USER_DENIED_TOOL_ACTION},
    )

    output = capsys.readouterr().out
    assert output == f"{RUN_DETAIL_INDENT}🚫 Action denied\n"
    assert "🕵️ Review output" not in output

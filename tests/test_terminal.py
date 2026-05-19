import builtins

import pytest

from core.approval import USER_DENIED_TOOL_ACTION
from ui.terminal import TerminalDisplay


@pytest.mark.parametrize("response", ["y", "yes", "Y", "YES"])
def test_approve_action_accepts_y_and_yes(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    monkeypatch.setattr(builtins, "input", lambda prompt: response)

    assert TerminalDisplay().approve_action({"tool": "read_file"}) is True


@pytest.mark.parametrize("response", ["", "n", "no", "sure"])
def test_approve_action_denies_anything_else(
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    monkeypatch.setattr(builtins, "input", lambda prompt: response)

    assert TerminalDisplay().approve_action({"tool": "read_file"}) is False


def test_approve_action_uses_multiline_prompt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr(builtins, "input", fake_input)

    assert (
        TerminalDisplay().approve_action(
            {
                "tool": "run_command",
                "args": {"command": "python -m pytest -q"},
            }
        )
        is False
    )

    assert capsys.readouterr().out == (
        "Approve tool action?\n"
        "💿 Running: python -m pytest -q\n"
    )
    assert prompts == ["[y/N] "]


def test_tool_result_displays_action_denied(capsys: pytest.CaptureFixture[str]) -> None:
    TerminalDisplay().tool_result(
        {"tool": "read_file"},
        {"ok": False, "error": USER_DENIED_TOOL_ACTION},
    )

    assert capsys.readouterr().out == "🚫 Action denied\n"


def test_denied_run_command_displays_action_denied(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().tool_result(
        {"tool": "run_command"},
        {"ok": False, "error": USER_DENIED_TOOL_ACTION},
    )

    output = capsys.readouterr().out
    assert output == "🚫 Action denied\n"
    assert "🕵️ Review output" not in output

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.approval import USER_DENIED_TOOL_ACTION
from ui.terminal import CODE_SQUID_BANNER, RUN_STARTED_DIVIDER, TerminalDisplay


class FakeSpinner:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


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
        "💿 Run: python -m pytest\n"
    )
    assert prompts == ["[y/N] "]


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
    assert capsys.readouterr().out == "🔎 Listed files\n"

    display.thinking()
    display.thinking()

    assert spinner.starts == 2
    assert spinner.stops == 1
    assert capsys.readouterr().out == "\n"


def test_first_thinking_after_header_does_not_print_extra_blank(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.start()
    assert capsys.readouterr().out == f"{CODE_SQUID_BANNER}\n\n"

    display.thinking()

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == ""


def test_run_started_prints_starting_run_divider(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().run_started()

    assert capsys.readouterr().out == f"\n{RUN_STARTED_DIVIDER}\n\n"


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


def test_action_started_prints_in_debug_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay(debug=True).action_started(
        {"tool": "write_file", "args": {"path": "kanban_toy2/app.js"}}
    )

    assert capsys.readouterr().out == "📝 Write: kanban_toy2/app.js\n"


def test_approve_action_still_prints_requested_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")

    TerminalDisplay().approve_action(
        {"tool": "write_file", "args": {"path": "kanban_toy2/app.js"}}
    )

    assert capsys.readouterr().out == (
        "Approve tool action?\n"
        "📝 Write: kanban_toy2/app.js\n"
    )


def test_long_outside_path_uses_ellipsis(capsys: pytest.CaptureFixture[str]) -> None:
    TerminalDisplay().tool_result(
        {
            "tool": "read_file",
            "args": {
                "path": "/home/aaron/Desktop/coding_agent_eval_repos/01_single_bug/test_calculator.py",
            },
        },
        {"ok": True},
    )

    assert capsys.readouterr().out == "📖 Read: …/01_single_bug/test_calculator.py\n"


def test_repo_local_path_becomes_relative(capsys: pytest.CaptureFixture[str]) -> None:
    TerminalDisplay().tool_result(
        {
            "tool": "read_file",
            "args": {"path": str(Path.cwd() / "tests/test_terminal.py")},
        },
        {"ok": True},
    )

    assert capsys.readouterr().out == "📖 Read: tests/test_terminal.py\n"


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

    assert capsys.readouterr().out == expected


@pytest.mark.parametrize(
    ("command", "approval_label", "success_label"),
    [
        ("find . -name '*.py'", "🔎 Search files\n", "🔎 Searched files\n"),
        ("rg TODO", "🔎 Search files\n", "🔎 Searched files\n"),
        ("grep -R TODO .", "🔎 Search files\n", "🔎 Searched files\n"),
        ("ls tests", "🔎 List files\n", "🔎 Listed files\n"),
    ],
)
def test_search_and_list_commands_use_compact_labels(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    approval_label: str,
    success_label: str,
) -> None:
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")
    action = {"tool": "run_command", "args": {"command": command}}

    TerminalDisplay().approve_action(action)
    assert capsys.readouterr().out == f"Approve tool action?\n{approval_label}"

    TerminalDisplay().tool_result(action, {"ok": True, "output": ""})
    assert capsys.readouterr().out == success_label


def test_write_file_result_prints_one_success_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "write_file", "args": {"path": "kanban_toy2/app.js"}}
    display = TerminalDisplay()

    display.action_started(action)
    display.tool_result(action, {"ok": True})

    assert capsys.readouterr().out == "📝 Wrote: kanban_toy2/app.js\n"


def test_run_command_result_prints_one_success_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "run_command", "args": {"command": "node --check app.js"}}
    display = TerminalDisplay()

    display.action_started(action)
    display.tool_result(action, {"ok": True, "output": ""})

    assert capsys.readouterr().out == "💿 Ran: node --check app.js\n"


def test_tool_result_followed_by_assistant_message_has_one_blank_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()

    display.tool_result(
        {"tool": "run_command", "args": {"command": "ls tests"}},
        {"ok": True, "output": ""},
    )
    display.assistant_message("The directory doesn't exist yet.")

    assert capsys.readouterr().out == (
        "🔎 Listed files\n"
        "\n"
        "🦑 The directory doesn't exist yet.\n"
        "\n"
    )


def test_assistant_message_followed_by_tool_result_has_one_blank_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()

    display.assistant_message("Directory created.")
    display.tool_result(
        {"tool": "write_file", "args": {"path": "kanban_toy2/index.html"}},
        {"ok": True},
    )

    assert capsys.readouterr().out == (
        "🦑 Directory created.\n"
        "\n"
        "📝 Wrote: kanban_toy2/index.html\n"
    )


def test_first_visible_output_after_header_has_no_extra_leading_blank(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = TerminalDisplay()

    display.start()
    display.tool_result(
        {"tool": "run_command", "args": {"command": "ls tests"}},
        {"ok": True, "output": ""},
    )

    assert capsys.readouterr().out == (
        f"{CODE_SQUID_BANNER}\n"
        "\n"
        "🔎 Listed files\n"
    )


def test_run_command_result_prints_one_test_summary_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    action = {"tool": "run_command", "args": {"command": "pytest -q"}}
    display = TerminalDisplay()

    display.action_started(action)
    display.tool_result(action, {"ok": True, "output": "2 passed in 0.01s"})

    assert capsys.readouterr().out == "🧪 Tests passed: 2 passed\n"


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
    assert capsys.readouterr().out == "🦑 Thinking...\n\n"


def test_assistant_message_stops_spinner_before_printing_content(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.thinking()
    display.assistant_message("The directory doesn't exist yet.")

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == "🦑 The directory doesn't exist yet.\n\n"


def test_normal_assistant_message_uses_squid_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message("The directory doesn't exist yet.")

    assert capsys.readouterr().out == "🦑 The directory doesn't exist yet.\n\n"


def test_assistant_message_does_not_hide_fallback_like_narration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message("Using read_file.")

    assert capsys.readouterr().out == "🦑 Using read_file.\n\n"


def test_multiline_assistant_message_indents_continuation_lines(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message(
        "The directory doesn't exist yet.\n"
        "I need to create it and then build the Kanban board."
    )

    assert capsys.readouterr().out == (
        "🦑 The directory doesn't exist yet.\n"
        "   I need to create it and then build the Kanban board.\n"
        "\n"
    )


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
    assert capsys.readouterr().out == "📝 Wrote: kanban_toy2/index.html\n"


def test_approval_prompt_stops_spinner_before_asking(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")

    display.thinking()
    assert display.approve_action({"tool": "read_file"}) is False

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == "Approve tool action?\n📖 Read: \n"


def test_interrupted_stops_spinner_before_printing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spinner = FakeSpinner()
    display = TerminalDisplay(_spinner=spinner)

    display.thinking()
    display.interrupted()

    assert spinner.starts == 1
    assert spinner.stops == 1
    assert capsys.readouterr().out == "⏹️ Interrupted\n"


def test_generic_long_command_gets_middle_truncated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = "printf '" + ("x" * 140) + "'"
    action = {"tool": "run_command", "args": {"command": command}}

    TerminalDisplay().tool_result(action, {"ok": True, "output": ""})

    output = capsys.readouterr().out
    assert output.startswith("💿 Ran: printf '")
    assert "…" in output
    assert len(output.removesuffix("\n")) <= len("💿 Ran: ") + 80


def test_normal_completion_prints_session_complete(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SimpleNamespace(files_read=set(), files_written=set(), messages=[])

    TerminalDisplay().loop_finished(session)

    assert capsys.readouterr().out.endswith("✅ Session complete\n")


def test_normal_assistant_final_summary_uses_report_heading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message(
        "Files changed: ui/terminal.py\n"
        "What changed: polished display\n"
        "TASK COMPLETE"
    )

    output = capsys.readouterr().out
    assert output.startswith("📋 Final summary\n\n")
    assert "Files changed: ui/terminal.py" in output
    assert "What changed: polished display" in output
    assert "🦑" not in output
    assert "TASK COMPLETE" not in output


def test_normal_assistant_final_summary_hides_preamble(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message(
        "All tests pass now. Let me provide the final summary.\n"
        "Files changed: ui/terminal.py\n"
        "What changed: polished display\n"
        "Verification run: `pytest tests/test_terminal.py`\n"
        "Remaining risks: none\n"
        "TASK COMPLETE"
    )

    output = capsys.readouterr().out
    assert "All tests pass now" not in output
    assert "Files changed: ui/terminal.py" in output
    assert "Verification run: `pytest tests/test_terminal.py`" in output


def test_normal_assistant_message_with_only_task_complete_is_hidden(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay().assistant_message("TASK COMPLETE")

    assert capsys.readouterr().out == ""


def test_debug_assistant_message_preserves_raw_task_complete(
    capsys: pytest.CaptureFixture[str],
) -> None:
    TerminalDisplay(debug=True).assistant_message("TASK COMPLETE")

    assert capsys.readouterr().out == "-> model replied\nassistant: TASK COMPLETE\n"


def test_interrupted_completion_does_not_print_session_complete(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = SimpleNamespace(files_read=set(), files_written=set(), messages=[])
    display = TerminalDisplay()

    display.interrupted()
    display.loop_finished(session)

    output = capsys.readouterr().out
    assert output.startswith("⏹️ Interrupted\n")
    assert "✅ Session complete" not in output


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

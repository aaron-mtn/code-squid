"""Focused tests for CLI-owned streamed assistant narration."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_squid.console.cli import session_runner
from code_squid.console.ui.display import TerminalDisplay


class TtyBuffer(io.StringIO):
    """Capture terminal control output while advertising interactive support."""

    def isatty(self) -> bool:
        return True


class CountingSpinner:
    """Record ownership handoffs without starting a background thread."""

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.style = ""

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


def empty_session():
    """Return the session fields needed by the completion presentation."""
    return SimpleNamespace(files_read=set(), files_written=set(), messages=[])


def test_deltas_repaint_one_growing_narration_region(monkeypatch) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay()

    display.handle_event({"type": "assistant_message_started"})
    assert stream.getvalue() == ""

    display.handle_event({"type": "assistant_delta", "delta": "I inspected"})
    display.handle_event({"type": "assistant_delta", "delta": " the parser."})

    output = stream.getvalue()
    assert display.streaming_narration_active is True
    assert "I inspected the parser." in output
    assert "\033[" in output
    assert "\r\033[2K" in output


def test_first_visible_delta_takes_ownership_from_spinner(monkeypatch) -> None:
    stream = TtyBuffer()
    spinner = CountingSpinner()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay(_spinner=spinner)

    display.thinking()
    display.handle_event({"type": "assistant_message_started"})
    assert spinner.stops == 0

    display.handle_event({"type": "assistant_delta", "delta": "Visible"})
    display.handle_event({"type": "assistant_delta", "delta": " growth"})

    assert spinner.starts == 1
    assert spinner.stops == 1


def test_validated_message_replaces_and_settles_provisional_text(monkeypatch) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay()

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Provisional"})
    display.assistant_message("Validated complete narration.")
    settled_output = stream.getvalue()

    assert "Validated complete narration." in settled_output
    assert display.streaming_narration_active is False

    display.handle_event(
        {"type": "assistant_message", "message": "Validated complete narration."}
    )
    assert stream.getvalue() == settled_output


def test_message_without_deltas_uses_ordinary_static_panel(capsys) -> None:
    display = TerminalDisplay()

    display.handle_event({"type": "assistant_message_started"})
    display.assistant_message("Validated without streamed chunks.")

    output = capsys.readouterr().out
    assert output.count("Validated without streamed chunks.") == 1
    assert display.streaming_narration_active is False


def test_reply_rejection_erases_provisional_narration(monkeypatch) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay()

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Rejected draft"})
    display.reply_rejected("malformed_tool_call")

    assert display.streaming_narration_active is False
    assert "\r\033[2K" in stream.getvalue()
    assert "Reply rejected" in stream.getvalue()


def test_final_message_discards_stream_and_renders_only_report(monkeypatch) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay()

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Temporary final"})
    display.final_message("Authoritative report")
    display.handle_event({"type": "final_message", "message": "Authoritative report"})
    display.loop_finished(empty_session())

    output = stream.getvalue()
    assert display.streaming_narration_active is False
    assert output.count("Authoritative report") == 1
    assert "Temporary final" not in output[output.rfind("\r\033[2K") :]


def test_subsequent_assistant_turn_starts_with_fresh_buffer(monkeypatch) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay()

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "First draft"})
    display.assistant_message("First accepted")
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Second turn"})

    latest_panel = stream.getvalue()[stream.getvalue().rfind("╭") :]
    assert "Second turn" in latest_panel
    assert "First draft" not in latest_panel


def test_tool_output_follows_settled_narration_cleanly(monkeypatch) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay()

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Writing now."})
    display.assistant_message("Writing the file now.")
    display.tool_result(
        {"tool": "write_file", "args": {"path": "notes.txt"}},
        {"ok": True},
    )

    output = stream.getvalue()
    assert output.index("Writing the file now.") < output.index("Wrote: notes.txt")
    assert display.streaming_narration_active is False


@pytest.mark.parametrize("cleanup", ["interrupted", "failed", "finished"])
def test_terminal_exit_paths_clear_streaming_state(monkeypatch, cleanup: str) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay()
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "In progress"})

    if cleanup == "interrupted":
        display.interrupted()
    elif cleanup == "failed":
        display.model_request_failed(Path("latest.log"))
    else:
        display.loop_finished(empty_session())

    assert display.streaming_narration_active is False
    assert "\r\033[2K" in stream.getvalue()


def test_non_tty_streaming_keeps_existing_single_static_output(capsys) -> None:
    display = TerminalDisplay()
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "presentation only"})

    assert capsys.readouterr().out == ""
    display.assistant_message("Accepted narration")

    output = capsys.readouterr().out
    assert output.count("Accepted narration") == 1
    assert "presentation only" not in output


def test_cli_wires_display_event_handler_into_new_run(monkeypatch, tmp_path) -> None:
    captured = {}
    display = SimpleNamespace(
        run_started=lambda: None,
        handle_event=lambda event: None,
    )
    fake_run = SimpleNamespace(
        loop=object(),
        session=object(),
        session_store=SimpleNamespace(session_id="session-1"),
    )

    def fake_build(**kwargs):
        captured.update(kwargs)
        return fake_run

    monkeypatch.setattr(session_runner, "build_coding_task_run", fake_build)
    monkeypatch.setattr(session_runner, "_run_loop", lambda *args: 0)

    status, session_id = session_runner._run_new_session_task(
        tmp_path,
        "task",
        SimpleNamespace(),
        display,
    )

    assert (status, session_id) == (0, "session-1")
    assert captured["on_event"] == display.handle_event

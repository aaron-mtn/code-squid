"""Focused tests for CLI-owned streamed assistant narration."""

from __future__ import annotations

import io
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.output.vt100 import Vt100_Output

from code_squid.console.cli import session_runner
from code_squid.console.ui.display import TerminalDisplay
from code_squid.console.ui.formatting import SQUID_GLYPH
from code_squid.console.ui.streaming_narration import StreamingNarration


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
        self.labels: list[str] = []
        self.active = False

    def start(self, label: str = "Thinking...") -> None:
        self.starts += 1
        self.labels.append(label)
        self.active = True

    def stop(self) -> None:
        self.stops += 1
        self.active = False


def interactive_display(
    monkeypatch,
    *,
    spinner: CountingSpinner | None = None,
    size: list[Size] | None = None,
) -> tuple[TerminalDisplay, TtyBuffer]:
    """Build a display around a real prompt_toolkit VT100 Output test seam."""
    stream = TtyBuffer()
    current_size = size if size is not None else [Size(rows=30, columns=80)]
    output = Vt100_Output(stream, lambda: current_size[0])
    monkeypatch.setattr(sys, "stdout", stream)
    return (
        TerminalDisplay(
            _spinner=spinner,
            _output_stream=stream,
            _narration_output=output,
        ),
        stream,
    )


def empty_session():
    """Return the session fields needed by the completion presentation."""
    return SimpleNamespace(files_read=set(), files_written=set(), messages=[])


def test_deltas_repaint_one_growing_narration_region(monkeypatch) -> None:
    display, stream = interactive_display(monkeypatch)

    display.handle_event({"type": "assistant_message_started"})
    assert stream.getvalue() == ""

    display.handle_event({"type": "assistant_delta", "delta": "I inspected"})
    display.handle_event({"type": "assistant_delta", "delta": " the parser."})

    output = stream.getvalue()
    assert display.streaming_narration_active is True
    # Differential rendering writes only the changed suffix on the second frame.
    assert "I inspected" in output
    assert "parser." in output
    # The live ANSI-to-prompt_toolkit path must not detach or drop VS15.
    assert SQUID_GLYPH in output
    assert output.count("\U0001f991") == output.count(SQUID_GLYPH)
    assert output.count("╭") == 1
    # prompt_toolkit keeps the caret hidden for the lifetime of the region.
    assert "\033[?25l" in output
    display.handle_event({"type": "final_message"})


def test_first_visible_delta_takes_ownership_from_spinner(monkeypatch) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event({"type": "assistant_message_started"})
    assert spinner.stops == 0

    display.handle_event({"type": "assistant_delta", "delta": "Visible"})
    display.handle_event({"type": "assistant_delta", "delta": " growth"})

    assert spinner.starts == 1
    assert spinner.stops == 1
    display.handle_event({"type": "final_message"})


def test_validated_message_replaces_and_settles_provisional_text(monkeypatch) -> None:
    display, stream = interactive_display(monkeypatch)

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
    display, stream = interactive_display(monkeypatch)

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Rejected draft"})
    display.reply_rejected("malformed_tool_call")

    assert display.streaming_narration_active is False
    assert "\033[J" in stream.getvalue()
    assert "Reply rejected" in stream.getvalue()


def test_final_message_discards_stream_and_renders_only_report(monkeypatch) -> None:
    display, stream = interactive_display(monkeypatch)

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Temporary final"})
    display.final_message("Authoritative report")
    display.handle_event({"type": "final_message", "message": "Authoritative report"})
    display.loop_finished(empty_session())

    output = stream.getvalue()
    assert display.streaming_narration_active is False
    assert output.count("Authoritative report") == 1
    assert output.rfind("Temporary final") < output.index("Authoritative report")


def test_subsequent_assistant_turn_starts_with_fresh_buffer(monkeypatch) -> None:
    display, stream = interactive_display(monkeypatch)

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "First draft"})
    display.assistant_message("First accepted")
    display.tool_result(
        {"tool": "write_file", "args": {"path": "between.txt"}},
        {"ok": True},
    )
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Second turn"})

    latest_panel = stream.getvalue()[stream.getvalue().rfind("╭") :]
    assert "Second turn" in latest_panel
    assert "First draft" not in latest_panel
    display.handle_event({"type": "final_message"})


def test_tool_output_follows_settled_narration_cleanly(monkeypatch) -> None:
    display, stream = interactive_display(monkeypatch)

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Writing now."})
    display.assistant_message("Writing the file now.")
    assert display.streaming_narration_active is False
    display.tool_result(
        {"tool": "write_file", "args": {"path": "notes.txt"}},
        {"ok": True},
    )

    output = stream.getvalue()
    assert output.index("Writing the file now.") < output.index("Wrote: notes.txt")
    assert display.streaming_narration_active is False


def test_tool_preparing_retains_narration_and_starts_tool_pulse(monkeypatch) -> None:
    spinner = CountingSpinner()
    display, stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event(
        {"type": "assistant_message_started", "phase": "narration"}
    )
    display.handle_event(
        {"type": "assistant_delta", "phase": "narration", "delta": "Writing now."}
    )
    display.handle_event({"type": "tool_preparing", "tool": "write_file"})

    assert display.streaming_narration_active is True
    assert display._streaming_narration.visible is False
    assert "Writing now." in stream.getvalue()
    assert spinner.starts == 2
    assert spinner.stops == 1
    assert spinner.labels == ["Thinking...", "Writing..."]


@pytest.mark.parametrize(
    ("tool", "label"),
    [
        ("read_file", "Reading..."),
        ("write_file", "Writing..."),
        ("apply_patch", "Patching..."),
        ("run_command", "Running..."),
        ("custom_tool", "Using tool..."),
    ],
)
def test_tool_preparing_uses_tool_specific_pulse(
    monkeypatch, tool: str, label: str
) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event({"type": "tool_preparing", "tool": tool})

    assert spinner.labels == ["Thinking...", label]


def test_tool_started_preserves_active_tool_pulse(monkeypatch) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event({"type": "tool_preparing", "tool": "read_file"})
    display.handle_event({"type": "tool_started", "tool": "read_file"})

    assert spinner.labels == ["Thinking...", "Reading..."]
    assert spinner.stops == 0
    assert spinner.active is True


def test_compaction_narration_to_run_command_keeps_running_pulse(
    monkeypatch,
) -> None:
    """Protect the lifecycle that previously blanked during a long command."""
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.handle_event({"type": "compaction_started"})
    display.thinking()
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Running tests."})
    display.handle_event({"type": "tool_preparing", "tool": "run_command"})
    display.assistant_message("Running tests.")
    display.handle_event(
        {"type": "assistant_message", "message": "Running tests."}
    )
    action = {
        "tool": "run_command",
        "args": {"command": "python -m pytest -q"},
    }
    display.action_started(action)
    display.handle_event({"type": "tool_started", "tool": "run_command"})

    assert spinner.labels[-1] == "Running..."
    assert spinner.active is True

    display.tool_result(action, {"ok": True, "output": "1 passed"})

    assert spinner.active is False


def test_authoritative_narration_settles_without_duplicate_or_spinner_restart(
    monkeypatch,
) -> None:
    spinner = CountingSpinner()
    display, stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event(
        {"type": "assistant_message_started", "phase": "narration"}
    )
    display.handle_event(
        {"type": "assistant_delta", "phase": "narration", "delta": "Writing now."}
    )
    display.handle_event({"type": "tool_preparing", "tool": "write_file"})
    retained_output = stream.getvalue()

    display.handle_event(
        {
            "type": "assistant_message",
            "phase": "narration",
            "message": "Writing now.",
        }
    )

    assert stream.getvalue() == retained_output
    assert display.streaming_narration_active is False
    assert spinner.starts == 2
    assert spinner.stops == 1

    display.handle_event({"type": "tool_started", "tool": "write_file"})

    assert spinner.starts == 2
    assert spinner.stops == 1


def test_display_callback_consumes_retained_narration_without_stopping_thinking(
    monkeypatch,
) -> None:
    spinner = CountingSpinner()
    display, stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event(
        {"type": "assistant_message_started", "phase": "narration"}
    )
    display.handle_event(
        {"type": "assistant_delta", "phase": "narration", "delta": "Writing now."}
    )
    display.handle_event({"type": "tool_preparing", "tool": "write_file"})
    retained_output = stream.getvalue()

    # Core's normal display callback currently precedes its observer event.
    display.assistant_message("Writing now.")

    assert stream.getvalue() == retained_output
    assert display.streaming_narration_active is False
    assert spinner.starts == 2
    assert spinner.stops == 1


def test_tool_preparing_after_settled_narration_starts_tool_pulse(
    monkeypatch,
) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "Writing now."})
    display.assistant_message("Writing now.")
    display.handle_event({"type": "tool_preparing", "tool": "write_file"})

    assert spinner.starts == 2
    assert spinner.stops == 2


def test_repeated_model_and_tool_turns_leave_no_orphan_thinking(monkeypatch) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    for text in ("Reading now.", "Writing now."):
        action = {"tool": "read_file", "args": {"path": "app.py"}}
        display.thinking()
        display.handle_event({"type": "assistant_message_started"})
        display.handle_event({"type": "assistant_delta", "delta": text})
        display.handle_event({"type": "tool_preparing", "tool": "read_file"})
        display.assistant_message(text)
        display.action_started(action)
        display.handle_event({"type": "tool_started", "tool": "read_file"})
        display.tool_result(action, {"ok": True, "content": "contents"})

    assert spinner.starts == 6
    assert spinner.stops == 4
    assert spinner.active is False


def test_visible_tool_output_never_competes_with_thinking(monkeypatch) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.handle_event({"type": "tool_preparing", "tool": "read_file"})
    display.tool_result(
        {"tool": "read_file", "args": {"path": "app.py"}},
        {"ok": True},
    )

    assert spinner.starts == 1
    assert spinner.stops == 1


def test_final_reply_does_not_restart_thinking_after_narration(monkeypatch) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "All done."})
    display.final_message("All done.")
    display.handle_event({"type": "final_message", "message": "All done."})

    assert spinner.starts == 1
    assert spinner.stops == 3


@pytest.mark.parametrize(
    "event_type",
    ["tool_finished", "run_cancelled", "run_failed", "run_finished"],
)
def test_tool_completion_and_run_boundaries_stop_thinking(
    monkeypatch, event_type: str
) -> None:
    spinner = CountingSpinner()
    display, _stream = interactive_display(monkeypatch, spinner=spinner)

    display.thinking()
    display.handle_event({"type": event_type})

    assert spinner.starts == 1
    assert spinner.stops == 1


@pytest.mark.parametrize("cleanup", ["interrupted", "failed", "finished"])
def test_terminal_exit_paths_clear_streaming_state(monkeypatch, cleanup: str) -> None:
    display, stream = interactive_display(monkeypatch)
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "In progress"})

    if cleanup == "interrupted":
        display.interrupted()
    elif cleanup == "failed":
        display.model_request_failed(Path("latest.log"))
    else:
        display.loop_finished(empty_session())

    assert display.streaming_narration_active is False
    assert "\033[J" in stream.getvalue()


def test_live_layout_reads_real_output_size_on_each_redraw() -> None:
    stream = TtyBuffer()
    size = [Size(rows=30, columns=42)]
    widths: list[int] = []
    output = Vt100_Output(stream, lambda: size[0])
    narration = StreamingNarration(
        lambda text, width: widths.append(width) or [text],
        stream=stream,
        output=output,
    )

    narration.begin()
    narration.append("first")
    size[0] = Size(rows=30, columns=24)
    narration.append(" second")
    narration.discard()

    assert 42 in widths
    assert 24 in widths


def test_tiny_live_viewport_keeps_valid_panel_state(monkeypatch) -> None:
    size = [Size(rows=2, columns=1)]
    display, _stream = interactive_display(monkeypatch, size=size)

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "still retained"})

    assert display.streaming_narration_active is True
    display.handle_event({"type": "reply_rejected"})
    assert display.streaming_narration_active is False


def test_live_renderer_contains_no_code_owned_repaint_sequences() -> None:
    source = inspect.getsource(sys.modules[StreamingNarration.__module__])

    assert "_CURSOR_UP" not in source
    assert "_CLEAR_LINE" not in source
    assert "\\033[2K" not in source


def test_non_tty_streaming_keeps_existing_single_static_output(capsys) -> None:
    display = TerminalDisplay()
    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "presentation only"})

    assert capsys.readouterr().out == ""
    display.assistant_message("Accepted narration")

    output = capsys.readouterr().out
    assert output.count("Accepted narration") == 1
    assert "presentation only" not in output


def test_debug_streaming_keeps_existing_single_static_output(
    monkeypatch,
) -> None:
    stream = TtyBuffer()
    monkeypatch.setattr(sys, "stdout", stream)
    display = TerminalDisplay(debug=True, _output_stream=stream)

    display.handle_event({"type": "assistant_message_started"})
    display.handle_event({"type": "assistant_delta", "delta": "presentation only"})
    assert stream.getvalue() == ""

    display.assistant_message("Accepted narration")
    output = stream.getvalue()
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

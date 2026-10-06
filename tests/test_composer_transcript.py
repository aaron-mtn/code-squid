"""Verify composer painting and first-run/follow-up cursors in primary history."""

import asyncio
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.application import create_app_session
from prompt_toolkit.application.current import set_app
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import DummyInput
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from code_squid.console.cli.prompt_loop import _composer_prompt, _print_help
from code_squid.console.ui.display import TerminalDisplay
from code_squid.console.cli import session_runner
from code_squid.console.ui.formatting import ANSI_ESCAPE_PATTERN
from code_squid.console.ui.startup_application import wait_for_startup_application
from code_squid.settings import load_settings
from squid_core.agent_loop import RunResult
from code_squid.console.ui.prompt_input import (
    _configure_composer_frame,
    prompt_multiline_input,
)


class TranscriptOutput(DummyOutput):
    """Track relative cursor movement and overwrites without losing old history."""

    def __init__(self, columns=80, rows=40):
        self.size = Size(rows=rows, columns=columns)
        self.lines = ["older shell history"] * 100 + [""]
        self.row = 100
        self.column = 0
        self.peak_row = self.row

    def get_size(self):
        return self.size

    def isatty(self):
        return False

    def write(self, data):
        for character in data:
            if character == "\r":
                self.column = 0
            elif character == "\n":
                self.row += 1
                self.peak_row = max(self.peak_row, self.row)
                while len(self.lines) <= self.row:
                    self.lines.append("")
            else:
                line = self.lines[self.row].ljust(self.column)
                self.lines[self.row] = (
                    line[:self.column] + character + line[self.column + 1:]
                )
                self.column += 1

    def cursor_up(self, amount):
        self.row -= amount

    def cursor_forward(self, amount):
        self.column += amount

    def cursor_backward(self, amount):
        self.column -= amount

    def erase_down(self):
        self.lines[self.row] = self.lines[self.row][:self.column]
        del self.lines[self.row + 1:]

    def erase_end_of_line(self):
        self.lines[self.row] = self.lines[self.row][:self.column]

    def enter_alternate_screen(self):
        raise AssertionError("ordinary composer must remain in primary")

    def erase_screen(self):
        raise AssertionError("ordinary composer must preserve scrollback")


class StartupTranscriptOutput(TranscriptOutput):
    """Model saved primary cursors, alternate startup, and live panel writes."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.saved_primary = None
        self.switches = []

    def isatty(self):
        return True

    def write(self, data):
        # Python terminal streams translate LF; prompt_toolkit also writes CRLF.
        # Interpret spinner erasure instead of treating ANSI as visible cells.
        position = 0
        for match in ANSI_ESCAPE_PATTERN.finditer(data):
            super().write(data[position:match.start()].replace("\n", "\r\n"))
            if match.group() == "\x1b[K":
                self.erase_end_of_line()
            position = match.end()
        super().write(data[position:].replace("\n", "\r\n"))

    def write_raw(self, data):
        self.write(data)

    def enter_alternate_screen(self):
        assert self.saved_primary is None
        self.saved_primary = (self.lines, self.row, self.column, self.peak_row)
        self.lines, self.row, self.column, self.peak_row = [""], 0, 0, 0
        self.switches.append("enter")

    def quit_alternate_screen(self):
        assert self.saved_primary is not None
        self.lines, self.row, self.column, self.peak_row = self.saved_primary
        self.saved_primary = None
        self.switches.append("leave")

    def cursor_goto(self, row=0, column=0):
        assert self.saved_primary is not None, "primary output must append"
        self.row, self.column = row, column
        while len(self.lines) <= row:
            self.lines.append("")

    def erase_screen(self):
        assert self.saved_primary is not None, "primary history must survive"
        self.lines, self.row, self.column = [""], 0, 0


@pytest.mark.parametrize("show_reasoning", [False, True])
@pytest.mark.parametrize("fade_finished", [False, True], ids=["forced-fade", "natural-fade"])
@pytest.mark.parametrize("rows", [40, 80])
@pytest.mark.parametrize("text", ["task", "first\nsecond\nthird"])
def test_first_run_and_followup_have_same_terminal_handoff(
    monkeypatch, tmp_path, show_reasoning, fade_finished, rows, text,
):
    """Exercise real startup retention, both runners, spinner, and live panels."""
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("CODE_SQUID_HOME", str(tmp_path / "home"))
    settings = load_settings(tmp_path)
    output = StartupTranscriptOutput(rows=rows)
    display = TerminalDisplay(
        show_reasoning=show_reasoning, _output_stream=output,
        _narration_output=output,
    )
    # Keep the real status lifecycle and cursor erasure, without rapid ticks.
    display._spinner.stream = output
    display._spinner.interval = 10
    thinking_gaps = []
    live_gaps = []

    def build(**kwargs):
        store = kwargs.get("session_store")
        if store is None:
            store = kwargs["session_store_factory"](tmp_path, text)
        session = kwargs.get("session") or session_runner.Session(workspace_root=tmp_path)

        def run():
            display.thinking()
            composer_end = max(
                i for i, line in enumerate(output.lines) if line.startswith("╰")
            )
            thinking_gaps.append(output.row - composer_end - 1)
            display.handle_event({"type": "assistant_message_started"})
            display.handle_event({"type": "assistant_reasoning_delta", "delta": "reasoning marker"})
            if show_reasoning:
                assert display._streaming_reasoning.visible
                live_gaps.append(next(
                    i for i in range(composer_end + 1, len(output.lines))
                    if output.lines[i].strip()
                ) - composer_end - 1)
            display.handle_event({"type": "assistant_delta", "delta": "assistant marker"})
            assert display._streaming_narration.visible
            if not show_reasoning:
                live_gaps.append(next(
                    i for i in range(composer_end + 1, len(output.lines))
                    if output.lines[i].strip()
                ) - composer_end - 1)
            display.reasoning_message("reasoning marker")
            display.assistant_message("assistant marker")
            display.final_message("done")
            return RunResult(status="complete")

        return SimpleNamespace(
            session=session, session_store=store,
            loop=SimpleNamespace(run=run, agent=SimpleNamespace(
                follow_up_message=lambda task: {"role": "user", "content": task},
            )),
        )

    monkeypatch.setattr(session_runner, "build_coding_task_run", build)
    gaps = []
    with create_pipe_input() as pipe:
        with create_app_session(input=pipe, output=output), redirect_stdout(output):
            display.start()
            session_id = None
            for first in (True, False):
                start_row = output.row
                pipe.send_text(f"\x1b[200~{text}\x1b[201~\r")
                animator = display.header if first else None
                assert prompt_multiline_input(
                    _composer_prompt(animator), animator=animator, boxed=True,
                ) == text
                if first and fade_finished:
                    wait_for_startup_application(display.header)
                if first:
                    status, session_id = session_runner._run_new_session_task(
                        tmp_path, text, settings, display,
                    )
                else:
                    status, session_id = session_runner._run_follow_up_task(
                        tmp_path, session_id, text, settings, display,
                    )
                assert status == 0 and session_id is not None
                # Find the actual retained composer and the next visible row,
                # not Screen dimensions: copied fullscreen padding fails here.
                composer_end = next(
                    i for i in range(start_row, len(output.lines))
                    if output.lines[i].startswith("╰")
                )
                first_output = next(
                    i for i in range(composer_end + 1, len(output.lines))
                    if output.lines[i].strip()
                )
                gaps.append(first_output - composer_end - 1)
                marker = "Reasoning:" if show_reasoning else "assistant marker"
                assert marker in output.lines[first_output + 1]
            display.stop_header()
    assert gaps == [1, 1]
    assert thinking_gaps == [1, 1]
    assert live_gaps == [1, 1]
    assert output.lines[:100] == ["older shell history"] * 100
    assert output.switches == ["enter", "leave"]


@pytest.mark.parametrize("text,height", [
    ("/help", 4),
    ("first\nsecond\nthird", 6),
    ("\n".join(f"line {i}" for i in range(50)), 16),
    ("wrapped input " * 800, 16),
], ids=["short", "multiline", "capped-lines", "capped-wrapped"])
@pytest.mark.parametrize("writer", ["command", "run"])
def test_real_boxed_submission_retains_only_measured_rows(text, height, writer, monkeypatch):
    # CI's TERM=dumb selects PromptSession's separate unboxed fallback.
    monkeypatch.setenv("TERM", "xterm-256color")
    output = TranscriptOutput()
    with create_pipe_input() as pipe:
        with create_app_session(input=pipe, output=output):
            pipe.send_text(f"\x1b[200~{text}\x1b[201~\r")
            assert prompt_multiline_input(_composer_prompt(), boxed=True) == text
            assert output.row == 100 + height
            # A done redraw alone can hide an earlier oversized reservation.
            # Check the editing high-water cursor too: no blank canvas scroll.
            assert output.peak_row <= 100 + height
            assert output.lines[100].startswith("╭")
            assert output.lines[100 + height - 1].startswith("╰")
            assert output.lines[:100] == ["older shell history"] * 100
            with redirect_stdout(output):
                if writer == "command":
                    _print_help()
                else:
                    display = TerminalDisplay()
                    display.run_started()
                    display.assistant_message("ordinary agent output")
    marker = "Code Squid help" if writer == "command" else "ordinary agent output"
    assert any(marker in line for line in output.lines)
    first_output_row = next(
        i for i in range(100 + height, len(output.lines)) if output.lines[i].strip()
    )
    # Commands append directly; run presentation supplies its existing blank
    # separator. Neither path inherits blank rows from composer allocation.
    assert first_output_row - (100 + height) in (0, 1)


def test_boxed_resize_wrapping_and_deletion_remeasure_painted_height():
    output = TranscriptOutput(rows=40)
    session = PromptSession(input=DummyInput(), output=output)
    session.show_frame = True
    session.reserve_space_for_menu = 0
    session.message = _composer_prompt()
    session.multiline = True
    _configure_composer_frame(session)

    async def render(text, columns, rows):
        output.size = Size(rows=rows, columns=columns)
        session.default_buffer.text = text
        session.default_buffer.cursor_position = len(text)
        with set_app(session.app):
            session.app.render_counter += 1
            session.app.renderer.render(session.app, session.layout)
        screen = session.app.renderer._last_screen
        assert screen is not None
        rendered = [
            "".join(screen.data_buffer[y][x].char for x in range(columns))
            for y in range(screen.height)
        ]
        assert rendered[0].startswith("╭")
        assert rendered[-1].startswith("╰")
        assert "Window too small" not in "\n".join(rendered)
        assert session.default_buffer.text == text
        return screen.height

    async def exercise():
        text = "wrapped 漢🙂 input " * 12
        wide = await render(text, 80, 40)
        narrow = await render(text, 30, 40)
        assert 4 < wide < narrow <= 16
        assert await render(text * 100, 30, 8) == 8
        assert await render(text * 100, 80, 40) == 16
        assert await render("short", 80, 40) == 4
        session.app.renderer.reset()

    asyncio.run(exercise())

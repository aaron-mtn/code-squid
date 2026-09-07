"""Rendered-screen and input tests for follow-up and startup composers."""

import asyncio
from pathlib import Path
import random
import threading
import time

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import set_app
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import DummyInput
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.output import DummyOutput

from code_squid.console.startup_menu import StartupMenu
from code_squid.console.ui.banner import StartupInfo
from code_squid.console.ui.binary_header import BinaryRainHeader, TITLE
from code_squid.console.ui.composer_layout import (
    COMPOSER_MAX_CONTENT_ROWS,
    COMPOSER_MIN_CONTENT_ROWS,
)
from code_squid.console.ui.formatting import RUN_PANEL_WIDTH
from code_squid.console.ui.prompt_input import (
    COMPOSER_STYLE,
    _configure_composer_frame,
    multiline_key_bindings,
    prompt_multiline_input,
)
from code_squid.console.ui.startup_application import (
    STARTUP_SESSION_SELECTED,
    StartupApplication,
    wait_for_startup_application,
)
from code_squid.settings import load_settings


class SizedOutput(DummyOutput):
    """Dummy output with controllable physical dimensions."""

    def __init__(self, columns: int = 80, rows: int = 32) -> None:
        self.size = Size(rows=rows, columns=columns)

    def get_size(self) -> Size:
        return self.size


def _startup(*, columns: int = 80, rows: int = 32, menu=None, input=None):
    rain = BinaryRainHeader(
        rng=random.Random(7),
        startup_info=StartupInfo(
            directory=Path("/tmp/project"),
            provider="openai_compatible",
            model="model",
            approval_mode="balanced",
        ),
    )
    rain.set_startup_menu(menu)
    prompt = lambda: [("", "  @code-squid\n  "), ("", "  " if menu and menu.focused else "› ")]
    startup = StartupApplication(
        prompt,
        rain,
        multiline_key_bindings(rain),
        input=input or DummyInput(),
        output=SizedOutput(columns, rows),
    )
    return startup


def _render_startup(startup: StartupApplication, text: str = ""):
    async def render():
        startup.buffer.text = text
        startup.buffer.cursor_position = len(text)
        with set_app(startup.application):
            startup.rain.advance(startup.application.output.get_size().columns)
            # Manual renderer calls do not run Application.invalidate(), so
            # advance its render key just as the real redraw lifecycle does.
            startup.application.render_counter += 1
            startup.application.renderer.render(
                startup.application, startup.application.layout
            )
        return startup.application.renderer._last_screen

    screen = asyncio.run(render())
    assert screen is not None
    return screen


def _screen_rows(screen, columns: int = 80) -> list[str]:
    return [
        "".join(screen.data_buffer[y][x].char for x in range(columns))
        for y in range(screen.height)
    ]


def _composer_rows(screen) -> list[str]:
    rows = _screen_rows(screen, RUN_PANEL_WIDTH)
    top = next(index for index, row in enumerate(rows) if row.startswith("╭"))
    bottom = next(index for index, row in enumerate(rows[top:], top) if row.startswith("╰"))
    return rows[top : bottom + 1]


def _wait_for(predicate) -> None:
    """Wait for a renderer-thread condition in deterministic lifecycle tests."""
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "abcdefghij",
        "x" * 53,
        "word " * 40,
        "first\nsecond\nthird",
        "漢🙂" * 40,
    ],
)
def test_startup_composer_renders_one_buffer_inside_fixed_frame(text: str) -> None:
    startup = _startup()
    screen = _render_startup(startup, text)
    composer = _composer_rows(screen)
    buffers = [
        window
        for window in screen.visible_windows_to_write_positions
        if isinstance(getattr(window, "content", None), BufferControl)
    ]
    cursor = screen.get_cursor_position(startup.input_window)

    assert len(buffers) == 1
    assert len(composer[0]) == RUN_PANEL_WIDTH
    assert composer[0] == f"╭{'─' * (RUN_PANEL_WIDTH - 2)}╮"
    assert composer[-1] == f"╰{'─' * (RUN_PANEL_WIDTH - 2)}╯"
    assert all(row[0] == row[-1] == "│" for row in composer[1:-1])
    assert 0 < cursor.x < RUN_PANEL_WIDTH - 1
    assert composer[0].startswith("╭") and composer[-1].endswith("╯")
    assert "@code-squid" in "\n".join(composer)


def test_ten_slowly_typed_characters_are_all_visible() -> None:
    startup = _startup()
    for index, character in enumerate("abcdefghij", 1):
        startup.buffer.insert_text(character)
        rows = _composer_rows(_render_startup(startup, startup.buffer.text))
        assert "abcdefghij"[:index] in "\n".join(rows)


def test_wrapping_grows_then_deletion_shrinks_without_duplicate_border() -> None:
    startup = _startup()
    tall = _composer_rows(_render_startup(startup, "many rows " * 40))
    short = _composer_rows(_render_startup(startup, "short"))

    assert len(tall) > 6
    assert len(short) == 4
    assert sum(row.startswith("╭") for row in short) == 1
    assert sum(row.startswith("╰") for row in short) == 1


def test_startup_composer_stays_inside_physical_viewport_then_scrolls_internally() -> None:
    startup = _startup(rows=30)
    medium = _render_startup(startup, "wrapped input " * 80)
    maximum = _render_startup(startup, "wrapped input " * 800)
    position = maximum.visible_windows_to_write_positions[startup.input_window]
    cursor = maximum.get_cursor_position(startup.input_window)

    assert startup.application.output is startup.output
    assert startup.application.output.get_size() == Size(rows=30, columns=80)
    assert medium.height <= startup.application.output.get_size().rows
    assert TITLE in "\n".join(_screen_rows(medium))
    # The 23-row scene, separator, and frame leave four physical content rows.
    assert len(_composer_rows(maximum)) == 6
    assert position.height == 3
    assert position.ypos <= cursor.y < position.ypos + position.height
    assert startup.buffer.text == "wrapped input " * 800


def test_startup_and_followup_share_content_height_policy() -> None:
    startup = _startup()
    assert len(_composer_rows(_render_startup(startup))) == COMPOSER_MIN_CONTENT_ROWS + 2

    output = SizedOutput(rows=40)
    session = PromptSession(input=DummyInput(), output=output)
    session.show_frame = True
    session.style = COMPOSER_STYLE
    session.reserve_space_for_menu = 0
    _configure_composer_frame(session)
    session.message = [("", "  @code-squid\n  › ")]
    session.multiline = True
    session.wrap_lines = True

    async def render(text: str):
        session.default_buffer.text = text
        session.default_buffer.cursor_position = len(text)
        with set_app(session.app):
            session.app.renderer.render(session.app, session.layout)
        return session.app.renderer._last_screen

    short = asyncio.run(render(""))
    tall = asyncio.run(render("follow-up input " * 800))
    assert short is not None and tall is not None
    assert len(_composer_rows(short)) == COMPOSER_MIN_CONTENT_ROWS + 2
    assert len(_composer_rows(tall)) == COMPOSER_MAX_CONTENT_ROWS + 2

    output.size = Size(rows=8, columns=80)
    physically_bounded = asyncio.run(render(session.default_buffer.text))
    assert physically_bounded is not None
    assert physically_bounded.height <= 8
    assert len(_composer_rows(physically_bounded)) == 8
    assert session.default_buffer.text == "follow-up input " * 800


def test_large_input_scrolls_in_short_viewport_without_fallback() -> None:
    startup = _startup(rows=30)
    task = "first line\n" + ("large-paste " * 300) + "\nlast line"
    screen = _render_startup(startup, task)
    rows = _screen_rows(screen)
    cursor = screen.get_cursor_position(startup.input_window)
    position = screen.visible_windows_to_write_positions[startup.input_window]

    assert startup.buffer.text == task
    assert "Window too small" not in "\n".join(rows)
    assert position.ypos <= cursor.y < position.ypos + position.height
    assert _composer_rows(screen)[-1].startswith("╰")


def test_rain_changes_while_panel_and_composer_stay_stable() -> None:
    startup = _startup()
    first = _screen_rows(_render_startup(startup, "typing while rain moves"))
    later = first
    for _ in range(40):
        later = _screen_rows(_render_startup(startup, startup.buffer.text))
    assert first != later
    assert TITLE in "\n".join(first) and TITLE in "\n".join(later)
    assert _composer_rows(_render_startup(startup, startup.buffer.text))


def test_menu_focus_marker_and_composer_marker_update_on_render(tmp_path) -> None:
    menu = StartupMenu(tmp_path, load_settings(tmp_path))
    startup = _startup(menu=menu)
    unfocused = _screen_rows(_render_startup(startup))

    menu.focus_from_composer()
    focused = _screen_rows(_render_startup(startup))
    menu.move(-1)
    moved = _screen_rows(_render_startup(startup))

    assert "›" in "\n".join(unfocused)
    assert "›" not in "\n".join(focused)
    assert "Workspace" in next(row for row in focused if ">" in row)
    assert "Session" in next(row for row in moved if ">" in row)
    assert startup.buffer.text == ""


@pytest.mark.parametrize("columns,rows", [(40, 32), (80, 12), (80, 50)])
def test_resize_degrades_without_fallback_and_recovers(columns: int, rows: int) -> None:
    startup = _startup(columns=columns, rows=rows)
    first = _screen_rows(_render_startup(startup, "resizable input"), columns)
    assert "Window too small" not in "\n".join(first)

    startup.application.output.size = Size(rows=32, columns=80)
    recovered = _screen_rows(_render_startup(startup, startup.buffer.text))
    assert TITLE in "\n".join(recovered)
    assert "resizable input" in "\n".join(recovered)


def test_long_composer_tracks_shrink_and_enlarge_without_losing_buffer() -> None:
    startup = _startup(rows=50)
    task = "wrapped input " * 800
    large = _render_startup(startup, task)
    assert len(_composer_rows(large)) == COMPOSER_MAX_CONTENT_ROWS + 2

    startup.output.size = Size(rows=30, columns=80)
    small = _render_startup(startup, task)
    small_position = small.visible_windows_to_write_positions[startup.input_window]
    small_cursor = small.get_cursor_position(startup.input_window)
    assert small.height <= 30
    assert len(_composer_rows(small)) == 6
    assert small_position.ypos <= small_cursor.y < small_position.ypos + small_position.height

    startup.output.size = Size(rows=50, columns=80)
    recovered = _render_startup(startup, task)
    assert len(_composer_rows(recovered)) == COMPOSER_MAX_CONTENT_ROWS + 2
    assert startup.buffer.text == task


def _run_input(terminal_input: str, *, startup: bool = False) -> str:
    result: list[str] = []
    errors: list[BaseException] = []
    with create_pipe_input() as pipe_input:
        if startup:
            app = _startup(input=pipe_input)
            target = app.run
        else:
            session = PromptSession(input=pipe_input, output=DummyOutput())
            target = lambda: session.prompt(
                "› ", multiline=True, key_bindings=multiline_key_bindings()
            )

        def run() -> None:
            try:
                result.append(target())
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        pipe_input.send_text(terminal_input)
        thread.join(timeout=10)
        assert not thread.is_alive()
        if startup:
            # The production display owns this handoff. Tests must release the
            # asynchronous startup renderer before closing their private pipe.
            app.finish_fade()
    assert not errors
    return result[0]


def test_plain_enter_submits_and_modified_enter_inserts_newlines() -> None:
    assert _run_input("task\r") == "task"
    for sequence in (
        "\x1b[27;2;13~",
        "\x1b[13;2u",
        "\x1b[27;3;13~",
        "\x1b[13;3u",
        "\x1b\r",
    ):
        assert _run_input(sequence + "next\r") == "\nnext"
    assert ANSI_SEQUENCES["\x1b[13;2u"] == Keys.ControlJ


def test_startup_large_bracketed_paste_and_deletion_preserve_buffer() -> None:
    task = "first\n" + ("x" * 20_000) + "\nlast"
    pasted = f"\x1b[200~{task}\x1b[201~"
    assert _run_input(pasted + ("\x7f" * 4) + "\r", startup=True) == task[:-4]


def test_startup_fast_vertical_navigation_uses_prompt_toolkit_bindings() -> None:
    task = "\n".join(f"line {index}" for index in range(100))
    with create_pipe_input() as pipe_input:
        startup = _startup(rows=30, input=pipe_input)
        result: list[str] = []
        thread = threading.Thread(target=lambda: result.append(startup.run()))
        thread.start()

        def wait_for(predicate) -> None:
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert predicate()

        try:
            pipe_input.send_text(f"\x1b[200~{task}\x1b[201~")
            wait_for(
                lambda: startup.buffer.text == task
                and startup.input_window.render_info is not None
            )

            pipe_input.send_text("\x1b[1;5H")  # Ctrl+Home.
            wait_for(lambda: startup.buffer.cursor_position == 0)
            pipe_input.send_text("\x1b[6~")  # PageDown.
            wait_for(lambda: startup.buffer.cursor_position > 0)
            page_down_position = startup.buffer.cursor_position

            pipe_input.send_text("\x1b[1;5B")  # Ctrl+Down.
            wait_for(lambda: startup.buffer.cursor_position > page_down_position)
            control_down_position = startup.buffer.cursor_position
            pipe_input.send_text("\x1b[1;5A")  # Ctrl+Up.
            wait_for(lambda: startup.buffer.cursor_position < control_down_position)

            pipe_input.send_text("\x1b[5~")  # PageUp.
            wait_for(lambda: startup.buffer.cursor_position < page_down_position)
            pipe_input.send_text("\x1b[1;5F")  # Ctrl+End.
            wait_for(lambda: startup.buffer.cursor_position == len(task))
            pipe_input.send_text("\r")
            thread.join(timeout=5)
            startup.finish_fade()
        finally:
            if thread.is_alive():
                pipe_input.send_bytes(b"\x03")
                thread.join(timeout=5)

    assert result == [task]


def test_startup_ctrl_c_raises_shutdown_interrupt() -> None:
    with create_pipe_input() as pipe_input:
        startup = _startup(input=pipe_input)
        errors: list[BaseException] = []
        thread = threading.Thread(
            target=lambda: _capture_error(startup.run, errors)
        )
        thread.start()
        pipe_input.send_bytes(b"\x03")
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], KeyboardInterrupt)
    assert startup.application.is_running is False
    assert all(thread.name != "code-squid-binary-rain" for thread in threading.enumerate())
    assert all(
        thread.name != "code-squid-startup-renderer"
        for thread in threading.enumerate()
    )


def test_startup_submit_returns_before_fade_and_retains_clean_composer() -> None:
    with create_pipe_input() as pipe_input:
        startup = _startup(input=pipe_input)
        result: list[str] = []
        caller = threading.Thread(target=lambda: result.append(startup.run()))
        caller.start()
        started = time.monotonic()
        pipe_input.send_text("submitted task\r")
        caller.join(timeout=0.2)
        elapsed = time.monotonic() - started

        assert not caller.is_alive()
        assert result == ["submitted task"]
        assert elapsed < 0.2
        assert startup.application.is_running is True
        assert startup.buffer.read_only() is True
        assert startup.buffer.text == "submitted task"

        assert startup._thread is not None
        startup._thread.join(timeout=2)
        assert not startup._thread.is_alive()

    screen = startup.final_screen
    assert screen is not None
    rows = "\n".join(_screen_rows(screen))
    assert "submitted task" in rows
    assert TITLE in rows
    assert startup.rain.fade_complete is True
    assert startup.rain._drops == []
    assert startup.application.is_running is False


def test_saved_session_handoff_hides_composer_and_waits_for_natural_fade(
    monkeypatch,
) -> None:
    with create_pipe_input() as pipe_input:
        startup = _startup(input=pipe_input)
        result: list[object] = []
        caller = threading.Thread(target=lambda: result.append(startup.run()))
        caller.start()
        _wait_for(lambda: startup.application.is_running)

        forced_fades = 0
        complete_fade = startup.rain.complete_fade

        def track_forced_fade() -> None:
            nonlocal forced_fades
            forced_fades += 1
            complete_fade()

        monkeypatch.setattr(startup.rain, "complete_fade", track_forced_fade)
        startup.select_saved_session()
        caller.join(timeout=0.2)

        assert result == [STARTUP_SESSION_SELECTED]
        assert startup.rain.fade_active is True
        assert startup.composer.filter() is False
        assert startup.application.is_running is True

        wait_for_startup_application(startup.rain)

    assert forced_fades == 0
    assert startup.rain.fade_complete is True
    assert startup.application.is_running is False
    assert startup._thread is not None and not startup._thread.is_alive()
    assert startup.final_screen is not None
    final_rows = "\n".join(_screen_rows(startup.final_screen))
    assert "@code-squid" not in final_rows
    assert TITLE in final_rows


def test_early_narration_forces_and_joins_startup_fade() -> None:
    from code_squid.console.ui.display import TerminalDisplay

    with create_pipe_input() as pipe_input:
        startup = _startup(input=pipe_input)
        result: list[str] = []
        caller = threading.Thread(target=lambda: result.append(startup.run()))
        caller.start()
        pipe_input.send_text("task\r")
        caller.join(timeout=0.2)
        assert result == ["task"]

        display = TerminalDisplay(_header=startup.rain)
        display.run_started()
        assert startup.application.is_running is True
        display.assistant_message("Early narration")

        assert startup.rain.fade_complete is True
        assert startup.application.is_running is False
        assert startup._thread is not None and not startup._thread.is_alive()
        assert not any(
            thread.name == "code-squid-startup-renderer" and thread.is_alive()
            for thread in threading.enumerate()
        )


def _capture_error(callback, errors: list[BaseException]) -> None:
    try:
        callback()
    except BaseException as error:
        errors.append(error)


def test_followup_boxed_prompt_keeps_existing_prompt_session_path(monkeypatch) -> None:
    calls = []

    class FakePromptSession:
        def __init__(self) -> None:
            self.show_frame = False
            self.style = None
            self.reserve_space_for_menu = 0
            self.layout = type("Layout", (), {"container": type("Root", (), {"children": []})()})()

        def prompt(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "follow-up"

    monkeypatch.setattr("code_squid.console.ui.prompt_input.PromptSession", FakePromptSession)
    assert prompt_multiline_input("› ") == "follow-up"
    assert calls[0][1]["multiline"] is True

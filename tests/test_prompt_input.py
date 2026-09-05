"""Rendered-screen and input tests for follow-up and startup composers."""

import asyncio
from pathlib import Path
import random
import threading

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
from code_squid.console.ui.formatting import RUN_PANEL_WIDTH
from code_squid.console.ui.prompt_input import (
    COMPOSER_STYLE,
    _configure_composer_frame,
    multiline_key_bindings,
    prompt_multiline_input,
)
from code_squid.console.ui.startup_application import StartupApplication
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
    assert "Mod" in next(row for row in moved if ">" in row)
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

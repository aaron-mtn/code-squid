import asyncio
import os
import threading

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.output import DummyOutput

from code_squid.console.ui.prompt_input import (
    COMPOSER_STYLE,
    _configure_composer_frame,
    _sync_live_composer_geometry,
    multiline_key_bindings,
    prompt_multiline_input,
)
from code_squid.console.ui.binary_header import BinaryRainHeader, HIDE_CURSOR
from code_squid.console.ui.formatting import RUN_PANEL_WIDTH


def _render_boxed_composer(text: str) -> list[list[str]]:
    """Render the real composer layout into prompt_toolkit's cell screen."""

    async def render() -> list[list[str]]:
        session = PromptSession(input=DummyInput(), output=DummyOutput())
        session.show_frame = True
        session.style = COMPOSER_STYLE
        session.reserve_space_for_menu = 0
        _configure_composer_frame(session)
        session.message = [("", "  @code-squid\n  › ")]
        session.multiline = True
        session.wrap_lines = True
        with set_app(session.app):
            session.default_buffer.text = text
            session.default_buffer.cursor_position = len(text)
            session.app.renderer.render(session.app, session.layout)
        screen = session.app.renderer._last_screen
        assert screen is not None
        return [
            [screen.data_buffer[row][column].char for column in range(RUN_PANEL_WIDTH)]
            for row in range(screen.height)
        ]

    return asyncio.run(render())


def _render_boxed_composer_geometry(text: str) -> tuple[int, int]:
    """Return prompt_toolkit's physical height and absolute cursor row."""

    async def render() -> tuple[int, int]:
        session = PromptSession(input=DummyInput(), output=DummyOutput())
        session.show_frame = True
        session.style = COMPOSER_STYLE
        session.reserve_space_for_menu = 0
        composer_bottom = _configure_composer_frame(session)
        session.message = [("", "  @code-squid\n  > ")]
        session.multiline = True
        session.wrap_lines = True
        with set_app(session.app):
            session.default_buffer.text = text
            session.default_buffer.cursor_position = len(text)
            session.app.renderer.render(session.app, session.layout)
        screen = session.app.renderer._last_screen
        assert screen is not None
        cursor = screen.get_cursor_position(session.layout.current_window)
        bottom = screen.visible_windows_to_write_positions[
            composer_bottom
        ]
        return bottom.ypos + bottom.height, cursor.y

    return asyncio.run(render())


def _assert_fixed_composer_edges(rows: list[list[str]]) -> None:
    assert rows[0][0] == "╭"
    assert rows[0][-1] == "╮"
    assert rows[-1][0] == "╰"
    assert rows[-1][-1] == "╯"
    assert all(len(row) == RUN_PANEL_WIDTH for row in rows)
    assert all(row[0] == row[-1] == "│" for row in rows[1:-1])


def test_boxed_composer_empty_and_short_geometry_is_fixed() -> None:
    empty_rows = _render_boxed_composer("")
    short_rows = _render_boxed_composer("hello")

    _assert_fixed_composer_edges(empty_rows)
    _assert_fixed_composer_edges(short_rows)
    assert len(empty_rows) == len(short_rows) == 4
    assert "".join(empty_rows[1]).startswith("│  @code-squid")
    assert "".join(empty_rows[2]).startswith("│  › ")


def test_boxed_composer_wraps_and_indents_continuations() -> None:
    rows = _render_boxed_composer("word " * 40)

    _assert_fixed_composer_edges(rows)
    assert len(rows) > 4
    assert "".join(rows[2]).startswith("│  › ")
    assert all("".join(row).startswith("│    ") for row in rows[3:-1])


def test_boxed_composer_explicit_newlines_grow_downward() -> None:
    rows = _render_boxed_composer("first\nsecond\nthird")

    _assert_fixed_composer_edges(rows)
    assert len(rows) == 6
    assert all("".join(row).startswith("│    ") for row in rows[3:-1])


def test_boxed_composer_wide_unicode_keeps_stationary_edges() -> None:
    rows = _render_boxed_composer("漢🙂" * 40)

    _assert_fixed_composer_edges(rows)
    assert len(rows) > 4


def test_active_buffer_window_stays_inside_box_at_full_interior_width() -> None:
    async def render_sequence():
        session = PromptSession(input=DummyInput(), output=DummyOutput())
        session.show_frame = True
        session.style = COMPOSER_STYLE
        session.reserve_space_for_menu = 0
        bottom_border = _configure_composer_frame(session)
        session.message = [("", "  @code-squid\n  > ")]
        session.multiline = True
        session.wrap_lines = True
        states = []

        with set_app(session.app):
            for text in (
                "x",
                "abcdefghij",
                "n" * 53,
                "first-part " * 10,
                "many rows " * 30,
                "short",
            ):
                session.default_buffer.text = text
                session.default_buffer.cursor_position = len(text)
                session.app.renderer.render(session.app, session.layout)
                screen = session.app.renderer._last_screen
                assert screen is not None
                buffers = [
                    (window, position)
                    for window, position in screen.visible_windows_to_write_positions.items()
                    if isinstance(getattr(window, "content", None), BufferControl)
                ]
                bottom = screen.visible_windows_to_write_positions[bottom_border].ypos
                cursor = screen.get_cursor_position(session.layout.current_window)
                rows = [
                    "".join(screen.data_buffer[y][x].char for x in range(RUN_PANEL_WIDTH))
                    for y in range(bottom + 1)
                ]
                states.append((text, buffers, bottom, cursor, rows))
        return states

    states = asyncio.run(render_sequence())

    for text, buffers, bottom, cursor, rows in states:
        assert len(buffers) == 1
        _, position = buffers[0]
        assert (position.xpos, position.width) == (1, 58)
        assert 0 < cursor.x < RUN_PANEL_WIDTH - 1
        assert 0 < cursor.y < bottom
        assert rows[0][0] == "╭" and rows[0][-1] == "╮"
        assert rows[bottom][0] == "╰" and rows[bottom][-1] == "╯"
        assert all(row[0] == row[-1] == "│" for row in rows[1:bottom])
        if text == "abcdefghij":
                assert "> abcdefghij" in rows[2]

    wrapped_rows = states[3][4]
    assert "first-part" in wrapped_rows[2]
    assert any("first-part" in row for row in wrapped_rows[3:-1])
    assert states[4][2] > states[3][2]
    assert states[-1][2] == 3


def _submit_terminal_input(monkeypatch, terminal_input: str) -> str:
    """Run the real prompt against deterministic terminal input."""

    result: list[str] = []
    errors: list[BaseException] = []

    with create_pipe_input() as pipe_input:
        monkeypatch.setattr(
            "code_squid.console.ui.prompt_input.PromptSession",
            lambda: PromptSession(input=pipe_input, output=DummyOutput()),
        )

        def prompt() -> None:
            try:
                result.append(prompt_multiline_input("› "))
            except BaseException as error:  # Preserve thread failures for the test.
                errors.append(error)

        prompt_thread = threading.Thread(target=prompt)
        prompt_thread.start()
        pipe_input.send_text(terminal_input)
        # Large paste processing can be slower under a loaded Windows test
        # runner; this is a ceiling, not an intentional test delay.
        prompt_thread.join(timeout=10)

        assert not prompt_thread.is_alive()

    assert not errors
    return result[0]


def test_prompt_multiline_input_uses_shared_multiline_bindings(monkeypatch) -> None:
    prompt_calls = []
    prefaces = []

    class FakePromptSession:
        def prompt(self, *args, **kwargs) -> str:
            prompt_calls.append((args, kwargs))
            return "line one\nline two"

    monkeypatch.setattr("code_squid.console.ui.prompt_input.PromptSession", FakePromptSession)
    monkeypatch.setattr(
        "code_squid.console.ui.prompt_input.print_formatted_text",
        lambda text: prefaces.append(text),
    )

    result = prompt_multiline_input("› ", preface="@code-squid")

    assert result == "line one\nline two"
    assert prefaces == ["@code-squid"]
    args, kwargs = prompt_calls[0]
    assert args == ("› ",)
    assert kwargs["multiline"] is True
    assert kwargs["key_bindings"] is not None
    assert ANSI_SEQUENCES["\x1b[27;2;13~"] == Keys.ControlJ
    assert ANSI_SEQUENCES["\x1b[13;2u"] == Keys.ControlJ


def test_menu_escape_binding_is_eager() -> None:
    class Menu:
        focused = True

    animator = type("Animator", (), {"startup_menu": Menu()})()
    bindings = multiline_key_bindings(animator)
    escape_bindings = [
        binding
        for binding in bindings.bindings
        if binding.keys == (Keys.Escape,)
    ]

    assert len(escape_bindings) == 1
    assert escape_bindings[0].eager() is True


def test_prompt_redraws_header_without_erasing_stable_composer(monkeypatch) -> None:
    events = []

    class EventHook:
        def __init__(self) -> None:
            self.handler = None

        def __iadd__(self, handler):
            self.handler = handler
            return self

        def fire(self, app) -> None:
            assert self.handler is not None
            self.handler(app)

    screen = type(
        "Screen",
        (),
        {
            "height": 4,
            "get_cursor_position": lambda self, window: type(
                "Point", (), {"y": 2}
            )(),
        },
    )()
    app = type(
        "FakeApp",
        (),
        {
            "loop": object(),
            "after_render": EventHook(),
            "renderer": type("Renderer", (), {"_last_screen": screen})(),
            "layout": type("Layout", (), {"current_window": object()})(),
        },
    )()

    class FakeAnimator:
        has_animator = True

        def resume(self, redraw) -> None:
            events.append("resume")
            redraw("frame-1")
            redraw("frame-2")

        def pause(self) -> None:
            events.append("pause")

        def write_live_frame(self, frame: str) -> None:
            events.append(f"draw:{frame}")

        def set_live_prompt_geometry(self, **geometry) -> None:
            events.append(("geometry", geometry))

    class FakePromptSession:
        def __init__(self) -> None:
            self.app = app

        def prompt(self, *args, **kwargs) -> str:
            assert "pre_run" not in kwargs
            app.after_render.fire(app)
            events.append("prompt")
            return "task"

    monkeypatch.setattr("code_squid.console.ui.prompt_input.PromptSession", FakePromptSession)
    monkeypatch.setattr(
        "code_squid.console.ui.prompt_input.get_app",
        lambda: type("FakeApp", (), {"loop": object()})(),
    )

    class CompletedFuture:
        def __init__(self, coroutine) -> None:
            self.coroutine = coroutine

        def result(self) -> None:
            import asyncio

            asyncio.run(self.coroutine)

    monkeypatch.setattr(
        "code_squid.console.ui.prompt_input.asyncio.run_coroutine_threadsafe",
        lambda coroutine, loop: CompletedFuture(coroutine),
    )

    assert prompt_multiline_input("› ", animator=FakeAnimator()) == "task"
    assert events == [
        (
            "geometry",
            {"prompt_height": 4, "cursor_row": 2, "separator_rows": 1},
        ),
        "resume",
        "draw:frame-1",
        "draw:frame-2",
        "prompt",
        "pause",
    ]


def test_real_prompt_session_emits_multiple_live_frames_when_constrained(
    monkeypatch,
) -> None:
    class RecordingStream:
        def __init__(self) -> None:
            self.writes: list[str] = []
            self.live_frame = threading.Event()

        def isatty(self) -> bool:
            return True

        def write(self, value: str) -> None:
            self.writes.append(value)
            if value.startswith(HIDE_CURSOR):
                self.live_frame.set()

        def flush(self) -> None:
            pass

    stream = RecordingStream()
    animator = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((80, 27)),
        ansi_supported=lambda output: True,
        frame_interval=10,
    )
    assert animator.start() is True
    result: list[str] = []

    with create_pipe_input() as pipe_input:
        monkeypatch.setattr(
            "code_squid.console.ui.prompt_input.PromptSession",
            lambda: PromptSession(input=pipe_input, output=DummyOutput()),
        )
        thread = threading.Thread(
            target=lambda: result.append(
                prompt_multiline_input("> ", animator=animator, boxed=True)
            )
        )
        thread.start()
        assert stream.live_frame.wait(timeout=1)

        for _ in range(10):
            live_writes = [value for value in stream.writes if value.startswith(HIDE_CURSOR)]
            if len(set(live_writes)) >= 2:
                break
            stream.live_frame.clear()
            animator.request_redraw()
            assert stream.live_frame.wait(timeout=1)

        pipe_input.send_text("task\r")
        thread.join(timeout=5)
        assert not thread.is_alive()

    live_writes = [value for value in stream.writes if value.startswith(HIDE_CURSOR)]
    assert result == ["task"]
    assert len(live_writes) >= 2
    assert len(set(live_writes)) >= 2
    animator.stop()


def test_live_composer_geometry_uses_real_rendered_growth_and_shrink() -> None:
    class Animator:
        geometry = None

        def set_live_prompt_geometry(self, **geometry) -> None:
            self.geometry = geometry

    heights = []
    states = ("", "word " * 40, "first\nsecond\nthird", "short", "")
    for text in states:
        height, cursor_row = _render_boxed_composer_geometry(text)
        heights.append(height)
        animator = Animator()
        screen = type(
            "Screen",
            (),
            {
                "height": height,
                "get_cursor_position": lambda self, window, row=cursor_row: type(
                    "Point", (), {"y": row}
                )(),
            },
        )()
        app = type(
            "App",
            (),
            {
                "renderer": type("Renderer", (), {"_last_screen": screen})(),
                "layout": type("Layout", (), {"current_window": object()})(),
            },
        )()

        assert _sync_live_composer_geometry(app, animator) is True
        assert animator.geometry == {
            "prompt_height": height,
            "cursor_row": cursor_row,
            "separator_rows": 1,
        }

    assert heights[0] == heights[-1] == 4
    assert heights[1] > heights[0]
    assert heights[2] == 6
    assert heights[3] == 4


def test_live_geometry_follows_visible_border_not_retained_cleanup_screen() -> None:
    async def render_sequence() -> tuple[list[int], list[int]]:
        session = PromptSession(input=DummyInput(), output=DummyOutput())
        session.show_frame = True
        session.style = COMPOSER_STYLE
        session.reserve_space_for_menu = 0
        composer_bottom = _configure_composer_frame(session)
        session.message = [("", "  @code-squid\n  > ")]
        session.multiline = True
        session.wrap_lines = True
        published_heights = []
        backing_heights = []

        class Animator:
            def set_live_prompt_geometry(self, **geometry) -> None:
                published_heights.append(geometry["prompt_height"])

        with set_app(session.app):
            for text in ("", "word " * 40, "first\nsecond\nthird", "short", ""):
                session.default_buffer.text = text
                session.default_buffer.cursor_position = len(text)
                session.app.renderer.render(session.app, session.layout)
                assert (
                    _sync_live_composer_geometry(
                        session.app,
                        Animator(),
                        composer_bottom=composer_bottom,
                    )
                    is True
                )
                backing_heights.append(session.app.renderer._last_screen.height)

        return published_heights, backing_heights

    published, backing = asyncio.run(render_sequence())

    assert published[0] == published[-1] == 4
    assert published[1] > published[0]
    assert published[2:] == [6, 4, 4]
    # prompt_toolkit retains the largest backing screen for row cleanup, while
    # the visible bottom border and animator geometry shrink immediately.
    assert backing[1:] == [published[1]] * 4


def test_prompt_multiline_input_preserves_long_single_line_input(monkeypatch) -> None:
    task = "x" * 20_000

    assert _submit_terminal_input(monkeypatch, task + "\r") == task


def test_shift_and_alt_enter_sequences_insert_newlines(monkeypatch) -> None:
    modified_enters = (
        "\x1b[27;2;13~",  # Shift+Enter, legacy modifyOtherKeys.
        "\x1b[13;2u",  # Shift+Enter, CSI-u.
        "\x1b[27;3;13~",  # Alt+Enter, legacy modifyOtherKeys.
        "\x1b[13;3u",  # Alt+Enter, CSI-u.
        "\x1b\r",  # Alt+Enter without enhanced keyboard reporting.
    )

    for sequence in modified_enters:
        assert _submit_terminal_input(monkeypatch, sequence + "next\r") == "\nnext"


def test_plain_enter_still_submits(monkeypatch) -> None:
    assert _submit_terminal_input(monkeypatch, "task\r") == "task"


def test_prompt_multiline_input_preserves_long_bracketed_paste(monkeypatch) -> None:
    task = "first line\n" + ("x" * 20_000) + "\nlast line"
    bracketed_paste = f"\x1b[200~{task}\x1b[201~"

    assert _submit_terminal_input(monkeypatch, bracketed_paste + "\r") == task


def test_prompt_multiline_input_buffers_long_paste_before_submission(
    monkeypatch,
) -> None:
    task = "first line\n" + ("x" * 20_000) + "\nlast line"
    buffer_updated = threading.Event()
    errors: list[BaseException] = []

    with create_pipe_input() as pipe_input:
        session = PromptSession(input=pipe_input, output=DummyOutput())
        session.default_buffer.on_text_changed += (
            lambda buffer: buffer_updated.set() if buffer.text == task else None
        )
        monkeypatch.setattr(
            "code_squid.console.ui.prompt_input.PromptSession",
            lambda: session,
        )

        def prompt() -> None:
            try:
                prompt_multiline_input("› ")
            except KeyboardInterrupt:
                pass
            except BaseException as error:  # Preserve thread failures for the test.
                errors.append(error)

        prompt_thread = threading.Thread(target=prompt)
        prompt_thread.start()
        try:
            pipe_input.send_text(f"\x1b[200~{task}\x1b[201~")

            assert buffer_updated.wait(timeout=5)
            assert prompt_thread.is_alive()
            assert session.default_buffer.text == task
            assert session.default_buffer.cursor_position == len(task)
        finally:
            pipe_input.send_bytes(b"\x03")
            prompt_thread.join(timeout=5)

        assert not prompt_thread.is_alive()

    assert not errors

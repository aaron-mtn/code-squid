import asyncio
import threading

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import set_app
from prompt_toolkit.input import DummyInput
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.keys import Keys
from prompt_toolkit.output import DummyOutput

from code_squid.console.ui.prompt_input import (
    COMPOSER_STYLE,
    _configure_composer_frame,
    multiline_key_bindings,
    prompt_multiline_input,
)
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


def test_prompt_resumes_animator_with_output_safe_redraw(monkeypatch) -> None:
    events = []

    class FakeAnimator:
        has_animator = True

        def resume(self, redraw) -> None:
            events.append("resume")
            redraw("frame")

        def pause(self) -> None:
            events.append("pause")

        def write_live_frame(self, frame: str) -> None:
            events.append(f"draw:{frame}")

    class FakePromptSession:
        def prompt(self, *args, **kwargs) -> str:
            kwargs["pre_run"]()
            events.append("prompt")
            return "task"

    monkeypatch.setattr("code_squid.console.ui.prompt_input.PromptSession", FakePromptSession)
    monkeypatch.setattr(
        "code_squid.console.ui.prompt_input.get_app",
        lambda: type("FakeApp", (), {"loop": object()})(),
    )

    async def fake_run_in_terminal(callback):
        events.append("safe-output")
        callback()

    class CompletedFuture:
        def __init__(self, coroutine) -> None:
            self.coroutine = coroutine

        def result(self) -> None:
            import asyncio

            asyncio.run(self.coroutine)

    monkeypatch.setattr(
        "code_squid.console.ui.prompt_input.run_in_terminal",
        fake_run_in_terminal,
    )
    monkeypatch.setattr(
        "code_squid.console.ui.prompt_input.asyncio.run_coroutine_threadsafe",
        lambda coroutine, loop: CompletedFuture(coroutine),
    )

    assert prompt_multiline_input("› ", animator=FakeAnimator()) == "task"
    assert events == [
        "resume",
        "safe-output",
        "draw:frame",
        "prompt",
        "pause",
    ]


def test_prompt_multiline_input_preserves_long_single_line_input(monkeypatch) -> None:
    task = "x" * 20_000

    assert _submit_terminal_input(monkeypatch, task + "\r") == task


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

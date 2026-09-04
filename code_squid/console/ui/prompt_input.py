"""Shared terminal input helpers."""

import asyncio

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import get_app, run_in_terminal
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from code_squid.console.ui.binary_header import BinaryRainHeader


def _install_alt_enter_ansi_sequences() -> None:
    ANSI_SEQUENCES["\x1b[27;2;13~"] = Keys.ControlJ
    ANSI_SEQUENCES["\x1b[13;2u"] = Keys.ControlJ


def multiline_key_bindings() -> KeyBindings:
    _install_alt_enter_ansi_sequences()

    bindings = KeyBindings()

    @bindings.add("enter")
    def _(event) -> None:
        event.app.exit(result=event.current_buffer.text)

    @bindings.add("c-j")
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("escape", "enter")
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    return bindings


def prompt_multiline_input(
    prompt: AnyFormattedText,
    *,
    preface: AnyFormattedText | None = None,
    animator: BinaryRainHeader | None = None,
) -> str:
    session = PromptSession()

    if animator is None or not animator.has_animator:
        if preface is not None:
            print_formatted_text(preface)
        return session.prompt(
            prompt,
            multiline=True,
            key_bindings=multiline_key_bindings(),
        )

    if preface is not None:
        print_formatted_text(preface)

    def start_animator() -> None:
        app = get_app()

        def redraw(frame: str) -> None:
            async def draw() -> None:
                await run_in_terminal(lambda: animator.write_live_frame(frame))

            # Waiting here provides backpressure: pause/stop cannot return
            # while prompt_toolkit still has an animation redraw queued.
            asyncio.run_coroutine_threadsafe(draw(), app.loop).result()

        animator.resume(redraw)

    try:
        return session.prompt(
            prompt,
            multiline=True,
            key_bindings=multiline_key_bindings(),
            pre_run=start_animator,
        )
    finally:
        animator.pause()

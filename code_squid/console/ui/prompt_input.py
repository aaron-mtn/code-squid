"""Shared terminal input helpers."""

import asyncio

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import get_app, run_in_terminal
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.keys import Keys
from code_squid.console.ui.binary_header import BinaryRainHeader


def _install_alt_enter_ansi_sequences() -> None:
    ANSI_SEQUENCES["\x1b[27;2;13~"] = Keys.ControlJ
    ANSI_SEQUENCES["\x1b[13;2u"] = Keys.ControlJ


def multiline_key_bindings(
    animator: BinaryRainHeader | None = None,
    *,
    resume_animator=None,
) -> KeyBindings:
    _install_alt_enter_ansi_sequences()

    bindings = KeyBindings()
    menu = getattr(animator, "startup_menu", None)
    menu_focused = Condition(lambda: menu is not None and menu.focused)
    empty_composer = Condition(
        lambda: menu is not None
        and not menu.focused
        and get_app().current_buffer.text == ""
    )

    @bindings.add("up", filter=menu_focused | empty_composer)
    def _(event) -> None:
        if menu.focused:
            menu.move(-1)
        else:
            menu.focus_from_composer()
        event.app.invalidate()

    @bindings.add("down", filter=menu_focused)
    def _(event) -> None:
        menu.move(1)
        event.app.invalidate()

    @bindings.add("enter", filter=menu_focused)
    async def _(event) -> None:
        # Model discovery is intentionally entered from a key action, never a
        # frame render. Pause from another thread so the application event loop
        # remains available to finish any in-flight output-safe redraw.
        await asyncio.to_thread(animator.pause)
        await asyncio.to_thread(menu.activate)
        if resume_animator is not None:
            resume_animator()
        event.app.invalidate()

    @bindings.add("escape", filter=menu_focused, eager=True)
    def _(event) -> None:
        # Escape prefixes Alt/meta sequences, so eager matching avoids
        # prompt_toolkit's standalone-Escape disambiguation delay in the menu.
        menu.back()
        event.app.invalidate()

    @bindings.add(Keys.Any, filter=menu_focused)
    def _(event) -> None:
        # Menu focus owns ordinary keys, so text cannot leak into the composer.
        event.app.invalidate()

    @bindings.add(Keys.BracketedPaste, filter=menu_focused)
    def _(event) -> None:
        event.app.invalidate()

    @bindings.add("enter", filter=~menu_focused)
    def _(event) -> None:
        event.app.exit(result=event.current_buffer.text)

    @bindings.add("c-j", filter=~menu_focused)
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("escape", "enter", filter=~menu_focused)
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
            key_bindings=multiline_key_bindings(animator),
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
            key_bindings=multiline_key_bindings(
                animator,
                resume_animator=start_animator,
            ),
            pre_run=start_animator,
        )
    finally:
        animator.pause()

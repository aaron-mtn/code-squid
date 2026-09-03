"""Shared terminal input helpers."""

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


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
) -> str:
    if preface is not None:
        print_formatted_text(preface)

    session = PromptSession()
    return session.prompt(
        prompt,
        multiline=True,
        key_bindings=multiline_key_bindings(),
    )

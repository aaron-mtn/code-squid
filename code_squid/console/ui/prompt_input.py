"""Shared terminal input helpers and startup-application dispatch."""

import asyncio

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import get_app
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.scroll import (
    scroll_half_page_down,
    scroll_half_page_up,
    scroll_page_down,
    scroll_page_up,
)
from prompt_toolkit.filters import Condition
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Dimension, HSplit, Window
from prompt_toolkit.layout.containers import ScrollOffsets, VSplit
from prompt_toolkit.styles import Style

from code_squid.console.ui.binary_header import BinaryRainHeader
from code_squid.console.ui.composer_layout import (
    COMPOSER_FRAME_ROWS,
    desired_composer_content_height,
)
from code_squid.console.ui.formatting import RUN_PANEL_WIDTH
from code_squid.console.ui.startup_application import StartupApplication


COMPOSER_RIGHT_PADDING = 1
COMPOSER_STYLE = Style.from_dict({"frame.border": "dim"})


def _configure_composer_frame(session: PromptSession) -> Window:
    """Give a normal PromptSession one exact-width, padded frame.

    PromptSession owns the application and its ordinary non-fullscreen render
    lifecycle. Its public ``show_frame`` option does not expose frame width or
    right padding, so this deliberately narrow seam replaces only that frame
    after PromptSession has built its standard layout.
    """
    root = session.layout.container
    framed_input = root.children[0]
    main_input = framed_input.alternative_content
    # PromptSession's focused Buffer Window is nested inside ``main_input``.
    # A one-row offset keeps its cursor away from the frame when room permits.
    session.layout.current_window.scroll_offsets = ScrollOffsets(top=1, bottom=1)

    def composer_width_cells() -> int:
        return max(min(RUN_PANEL_WIDTH, get_app().output.get_size().columns), 1)

    def safe_content_rows() -> int:
        return max(
            get_app().output.get_size().rows - COMPOSER_FRAME_ROWS,
            0,
        )

    def border(character: str, **kwargs) -> Window:
        return Window(
            char=character,
            style="class:frame.border",
            **kwargs,
        )

    bottom_left = border("╰", width=1)
    input_row = VSplit(
        [
            border("│", width=1),
            main_input,
            Window(width=Dimension.exact(COMPOSER_RIGHT_PADDING)),
            border("│", width=1),
        ],
        height=lambda: desired_composer_content_height(
            main_input,
            max(composer_width_cells() - 2 - COMPOSER_RIGHT_PADDING, 1),
            safe_content_rows(),
        ),
        padding=0,
    )
    composer = HSplit(
        [
            VSplit(
                [
                    border("╭", width=1),
                    border("─"),
                    border("╮", width=1),
                ],
                height=1,
            ),
            input_row,
            VSplit(
                [
                    bottom_left,
                    border("─"),
                    border("╯", width=1),
                ],
                height=1,
            ),
        ],
        width=lambda: Dimension.exact(composer_width_cells()),
    )
    # The root receives the terminal width. A sibling absorbs unused columns
    # so the composer stays at its product width whenever the viewport permits.
    framed_input.content = VSplit(
        [composer, Window()],
        padding=0,
    )
    return bottom_left


def _install_modified_enter_ansi_sequences() -> None:
    # Windows Terminal can encode modified Enter through either the legacy
    # modifyOtherKeys form or the CSI-u form. Modifier 2 is Shift; modifier 3
    # is Alt. Normalize both to the existing multiline-only Ctrl+J binding.
    ANSI_SEQUENCES["\x1b[27;2;13~"] = Keys.ControlJ
    ANSI_SEQUENCES["\x1b[13;2u"] = Keys.ControlJ
    ANSI_SEQUENCES["\x1b[27;3;13~"] = Keys.ControlJ
    ANSI_SEQUENCES["\x1b[13;3u"] = Keys.ControlJ


def multiline_key_bindings(
    animator: BinaryRainHeader | None = None,
) -> KeyBindings:
    _install_modified_enter_ansi_sequences()

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
        # frame render. The Application refresh timer can keep invalidating the
        # rain while blocking provider discovery runs outside its event loop.
        await asyncio.to_thread(menu.activate)
        if menu.workspace_handoff_pending:
            release_startup = getattr(
                event.app,
                "code_squid_workspace_selected",
                None,
            )
            if release_startup is not None:
                release_startup()
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
        startup_submit = getattr(event.app, "code_squid_submit", None)
        if startup_submit is not None:
            startup_submit(event.current_buffer.text)
            return
        event.app.exit(result=event.current_buffer.text)

    @bindings.add("c-c", eager=True)
    def _(event) -> None:
        # Ctrl+C is Code Squid shutdown, including while the startup menu owns
        # ordinary keys. Application cleanup restores terminal cursor state.
        if animator is not None and animator.fade_active:
            animator.complete_fade()
            event.app.invalidate()
            return
        event.app.exit(exception=KeyboardInterrupt)

    @bindings.add("c-j", filter=~menu_focused)
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("pageup", filter=~menu_focused)
    def _(event) -> None:
        scroll_page_up(event)

    @bindings.add("pagedown", filter=~menu_focused)
    def _(event) -> None:
        scroll_page_down(event)

    @bindings.add("c-up", filter=~menu_focused)
    def _(event) -> None:
        scroll_half_page_up(event)

    @bindings.add("c-down", filter=~menu_focused)
    def _(event) -> None:
        scroll_half_page_down(event)

    @bindings.add("escape", "enter", filter=~menu_focused)
    def _(event) -> None:
        event.current_buffer.insert_text("\n")

    return bindings


def prompt_multiline_input(
    prompt: AnyFormattedText,
    *,
    preface: AnyFormattedText | None = None,
    animator: BinaryRainHeader | None = None,
    boxed: bool = False,
) -> str | object:
    if animator is None:
        session = PromptSession()
        if boxed:
            session.show_frame = True
            session.style = COMPOSER_STYLE
            session.reserve_space_for_menu = 0
            _configure_composer_frame(session)
        if preface is not None:
            print_formatted_text(preface)
        return session.prompt(
            prompt,
            multiline=True,
            key_bindings=multiline_key_bindings(animator),
        )

    # Startup is the only composite live UI. Its result lets the caller join it
    # before ordinary output; follow-up prompts keep using PromptSession.
    startup = StartupApplication(
        prompt,
        animator,
        multiline_key_bindings(animator),
    )
    return startup.run()

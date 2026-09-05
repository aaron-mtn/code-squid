"""Shared terminal input helpers, including the transient boxed composer."""

import asyncio

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.application import get_app
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Dimension, HSplit, Window
from prompt_toolkit.layout.containers import VSplit
from prompt_toolkit.styles import Style

from code_squid.console.ui.binary_header import BinaryRainHeader
from code_squid.console.ui.formatting import RUN_PANEL_WIDTH
from code_squid.console.ui.header_layout import STARTUP_SEPARATOR_ROWS


COMPOSER_RIGHT_PADDING = 1
COMPOSER_INPUT_WIDTH = RUN_PANEL_WIDTH - 2 - COMPOSER_RIGHT_PADDING
COMPOSER_STYLE = Style.from_dict({"frame.border": "dim"})


def _sync_live_composer_geometry(
    app,
    animator: BinaryRainHeader,
    *,
    composer_bottom: Window | None = None,
) -> bool:
    """Publish prompt_toolkit's last physical composer geometry to the header.

    The screen and cursor position are render results, so they account for
    wrapping, explicit newlines, wide characters, and later shrinkage.  Reading
    them after a render avoids duplicating prompt_toolkit's width calculations.
    """
    screen = app.renderer._last_screen
    if screen is None:
        return False
    cursor = screen.get_cursor_position(app.layout.current_window)
    write_positions = getattr(screen, "visible_windows_to_write_positions", {})
    bottom_position = write_positions.get(composer_bottom)
    # prompt_toolkit keeps a prior maximum Screen height so it can erase rows
    # after shrinkage. The bottom border, however, marks the visible composer.
    prompt_height = (
        bottom_position.ypos + bottom_position.height
        if bottom_position is not None
        else screen.height
    )
    animator.set_live_prompt_geometry(
        prompt_height=prompt_height,
        cursor_row=cursor.y,
        cursor_column=cursor.x,
        separator_rows=STARTUP_SEPARATOR_ROWS,
    )
    return True


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
        padding=0,
        # Cap only the middle row using the normal PromptSession content's
        # natural height. This is not self-referential, and it leaves the
        # BufferControl's horizontal allocation entirely untouched.
        height=lambda: Dimension.exact(
            main_input.preferred_height(
                COMPOSER_INPUT_WIDTH,
                session.app.output.get_size().rows,
            ).preferred
        ),
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
        width=Dimension.exact(RUN_PANEL_WIDTH),
    )
    # The root receives the terminal width. A sibling absorbs unused columns
    # so the composer itself remains exactly RUN_PANEL_WIDTH cells wide.
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
    *,
    resume_animator=None,
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
        animator.request_redraw()
        event.app.invalidate()

    @bindings.add("down", filter=menu_focused)
    def _(event) -> None:
        menu.move(1)
        animator.request_redraw()
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
        animator.request_redraw()
        event.app.invalidate()

    @bindings.add("escape", filter=menu_focused, eager=True)
    def _(event) -> None:
        # Escape prefixes Alt/meta sequences, so eager matching avoids
        # prompt_toolkit's standalone-Escape disambiguation delay in the menu.
        menu.back()
        animator.request_redraw()
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
    boxed: bool = False,
) -> str:
    session = PromptSession()
    composer_bottom = None
    if boxed:
        session.show_frame = True
        session.style = COMPOSER_STYLE
        session.reserve_space_for_menu = 0
        composer_bottom = _configure_composer_frame(session)

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

    animation_started = False

    def start_animator() -> None:
        app = get_app()

        def redraw(frame: str) -> None:
            async def draw() -> None:
                # This coroutine runs on the PromptSession loop, serialized
                # with input redraws. The header writer restores the exact
                # prompt cursor position, so prompt_toolkit's renderer remains
                # authoritative and does not need to erase/repaint the box.
                animator.write_live_frame(frame)

            # Waiting here provides backpressure: pause/stop cannot return
            # while prompt_toolkit still has an animation redraw queued.
            asyncio.run_coroutine_threadsafe(draw(), app.loop).result()

        animator.resume(redraw)

    def after_render(app) -> None:
        nonlocal animation_started
        if not _sync_live_composer_geometry(
            app,
            animator,
            composer_bottom=composer_bottom,
        ):
            return
        if not animation_started:
            # Wait for the first real render: before it, neither composer
            # height nor its cursor row exists as authoritative geometry.
            animation_started = True
            start_animator()

    session.app.after_render += after_render

    try:
        return session.prompt(
            prompt,
            multiline=True,
            key_bindings=multiline_key_bindings(
                animator,
                resume_animator=start_animator,
            ),
        )
    finally:
        animator.pause()

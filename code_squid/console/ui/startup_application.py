"""Temporary single-renderer application for the interactive startup scene."""

from __future__ import annotations

import contextvars
import threading

from prompt_toolkit import print_formatted_text
from prompt_toolkit.application import Application, get_app_session
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import AnyFormattedText, FormattedText, to_formatted_text
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.filters import Condition
from prompt_toolkit.input.base import Input
from prompt_toolkit.key_binding import KeyBindingsBase
from prompt_toolkit.layout import Dimension, HSplit, Layout, Window
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    ScrollOffsets,
    VSplit,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.output.base import Output
from prompt_toolkit.styles import Style

from code_squid.console.ui.binary_header import BinaryRainHeader, FRAME_INTERVAL
from code_squid.console.ui.composer_layout import (
    COMPOSER_FRAME_ROWS,
    COMPOSER_MIN_CONTENT_ROWS,
    desired_composer_content_height,
)
from code_squid.console.ui.formatting import RUN_PANEL_WIDTH
from code_squid.console.ui.header_layout import STARTUP_SEPARATOR_ROWS
from code_squid.console.ui.terminal_session import StartupOutput, startup_terminal


COMPOSER_RIGHT_PADDING = 1


# Workspace reconstruction releases the renderer without committing a startup
# snapshot. The replacement Application continues the same transient cycle.
STARTUP_WORKSPACE_SELECTED = object()


_active_startups: dict[int, "StartupApplication"] = {}
_active_startups_lock = threading.Lock()


def finish_startup_application(rain: BinaryRainHeader) -> None:
    """Join startup before another writer; retain only a submitted scene."""
    with _active_startups_lock:
        startup = _active_startups.get(id(rain))
    if startup is not None:
        startup.finish_fade()


def wait_for_startup_application(rain: BinaryRainHeader) -> None:
    """Join a naturally finishing startup renderer without forcing its fade."""
    with _active_startups_lock:
        startup = _active_startups.get(id(rain))
    if startup is not None:
        startup.wait_for_exit()


def startup_application_active(rain: BinaryRainHeader) -> bool:
    """Return whether the rain model still has a live startup renderer."""
    with _active_startups_lock:
        return id(rain) in _active_startups


class StartupApplication:
    """Own rain, panel, menu presentation, and composer until handoff.

    This scene owns the temporary alternate buffer; the CLI transcript stays
    on primary. Task submission or workspace reconstruction releases the caller
    while this same renderer briefly fades its rain. Ordinary run output can
    force and join it; workspace rebuilds join without retaining a snapshot.
    Only submission commits a clean scene to primary. This boundary avoids
    recreating a persistent transcript/composer UI.
    """

    def __init__(
        self,
        prompt: AnyFormattedText,
        rain: BinaryRainHeader,
        key_bindings: KeyBindingsBase,
        *,
        input: Input | None = None,
        output: Output | None = None,
    ) -> None:
        self.rain = rain
        self.prompt = prompt
        self._submitted = threading.Event()
        self._result: str | object = ""
        self._menu_handoff = False
        self._retain_on_exit = False
        self._frame_retained = False
        self._failure: BaseException | None = None
        self._thread: threading.Thread | None = None
        self.final_screen = None
        # Keep the real Output as the sole source of terminal geometry. In
        # particular, resize reconciliation must describe this viewport.
        self.output = output or get_app_session().output
        # Read-only state takes effect in the same key event that publishes the
        # task, so no input can mutate the retained composer during the fade.
        self.buffer = Buffer(
            multiline=True,
            read_only=Condition(self._submitted.is_set),
        )
        self.buffer_control = BufferControl(
            buffer=self.buffer,
            input_processors=[BeforeInput(self._prompt_marker)],
        )
        self.input_window = Window(
            self.buffer_control,
            wrap_lines=True,
            dont_extend_height=True,
            scroll_offsets=ScrollOffsets(top=1, bottom=1),
            get_line_prefix=self._continuation_prefix,
        )
        self.scene_control = FormattedTextControl(self._scene_fragments)
        self.scene_window = Window(
            self.scene_control,
            height=self._scene_height,
            wrap_lines=False,
            always_hide_cursor=True,
        )
        self.composer = ConditionalContainer(
            self._composer_container(),
            filter=Condition(lambda: not self._menu_handoff),
        )
        root = HSplit(
            [
                self.scene_window,
                Window(height=self._separator_height),
                # The width sink must not claim vertical space from the
                # deliberately bounded startup surface.
                VSplit(
                    [self.composer, Window(dont_extend_height=True)],
                    padding=0,
                ),
            ],
            padding=0,
        )
        self.application: Application[object] = Application(
            layout=Layout(root, focused_element=self.buffer_control),
            key_bindings=key_bindings,
            style=Style.from_dict({"frame.border": "dim"}),
            # The scene boundary owns buffer entry/exit around all renderer
            # cleanup. This delegate only prepares the fullscreen canvas.
            full_screen=True,
            # Do not perform the inline "done" redraw: its final newline can
            # scroll a full-height alternate canvas during screen restoration.
            erase_when_done=True,
            refresh_interval=FRAME_INTERVAL,
            before_render=self._advance_rain,
            after_render=self._exit_after_clean_frame,
            input=input,
            output=StartupOutput(self.output),
        )
        # The shared key bindings use this narrow product callback only for the
        # startup Application; ordinary PromptSession submission is unchanged.
        self.application.code_squid_submit = self.submit  # type: ignore[attr-defined]
        self.application.code_squid_workspace_selected = (  # type: ignore[attr-defined]
            self.select_workspace
        )
        # `/new` constructs a new temporary Application around the same display
        # model, so reset drops here to make every session scene genuinely fresh.
        self.rain.reset(self.application.output.get_size().columns)

    def run(self) -> str | object:
        """Return on handoff while the existing Application finishes its fade."""
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run,
            args=(self._run_application,),
            name="code-squid-startup-renderer",
        )
        with _active_startups_lock:
            _active_startups[id(self.rain)] = self
        try:
            self._thread.start()
            self._submitted.wait()
        except BaseException:
            # A process SIGINT can interrupt the caller's wait rather than the
            # input Application. Join its renderer before cancellation prints.
            if self._thread.ident is not None:
                self.finish_fade()
            else:
                with _active_startups_lock:
                    _active_startups.pop(id(self.rain), None)
            raise
        self._raise_failure()
        return self._result

    def submit(self, task: str) -> None:
        """Publish the immutable composer value and start the short fade."""
        if self._submitted.is_set():
            return
        self._result = task
        # Only composer submission leaves startup for normal CLI interaction.
        # Rebuilds and forced cleanup must not commit intermediate menu state.
        self._retain_on_exit = True
        self.rain.begin_fade()
        self._submitted.set()
        self.application.invalidate()

    def select_workspace(self) -> None:
        """Release startup so the CLI can rebuild around another root."""
        if self._submitted.is_set():
            return
        self._result = STARTUP_WORKSPACE_SELECTED
        self._menu_handoff = True
        self.rain.begin_fade()
        self._submitted.set()
        self.application.invalidate()

    def wait_for_exit(self) -> None:
        """Wait for the existing fade lifecycle to release the terminal."""
        if (
            self._thread is not None
            and self._thread is not threading.current_thread()
        ):
            self._thread.join()
        self._raise_failure()

    def finish_fade(self) -> None:
        """Force and join the clean frame, committing only after submission."""
        if self.application.is_running and self.application.loop is not None:
            # Mutate render state on its owning event loop. This prevents a
            # force request from landing between composition and after_render.
            self.application.loop.call_soon_threadsafe(self._force_fade)
        else:
            self.rain.complete_fade()
        if (
            self._thread is not None
            and self._thread is not threading.current_thread()
        ):
            self._thread.join()
        self._raise_failure()

    def _force_fade(self) -> None:
        self.rain.complete_fade()
        self.application.invalidate()

    def _run_application(self) -> None:
        try:
            with startup_terminal(self.output):
                self.application.run()
            self._retain_clean_frame()
        except BaseException as error:
            self._failure = error
        finally:
            self._submitted.set()
            with _active_startups_lock:
                if _active_startups.get(id(self.rain)) is self:
                    del _active_startups[id(self.rain)]

    def _retain_clean_frame(self) -> None:
        """Append the clean scene to primary after restoring the startup buffer."""
        if (
            not self._retain_on_exit
            or self._frame_retained
            or self.final_screen is None
            or not self.rain.fade_complete
        ):
            return
        # Both separator and projection belong to the final handoff. Even blank
        # newlines would mutate primary history during an internal rebuild.
        self._frame_retained = True
        # Primary restoration preserves its append cursor. Advance off any
        # unfinished transcript line, then leave one blank line; ordinary
        # sequential printing scrolls naturally without erasing prior output.
        # Keep separation fixed so /new never adds a viewport-sized void.
        self.output.write_raw("\r\n\r\n")
        self.output.flush()
        fragments = []
        size = self._output_size()
        for row in range(min(self.final_screen.height, size.rows)):
            cells = self.final_screen.data_buffer[row]
            # Screen contains continuation cells for wide glyphs. Print only
            # their leading cell, and omit padding beyond the visible content.
            last_column = max(
                (column for column, cell in cells.items() if cell.char != " "),
                default=-1,
            )
            for column in range(min(last_column + 1, size.columns)):
                cell = cells[column]
                if cell.width:
                    fragments.append((cell.style, cell.char))
            fragments.append(("", "\n"))
        print_formatted_text(
            FormattedText(fragments), output=self.output,
            style=self.application.style, end="",
        )

    def _raise_failure(self) -> None:
        if self._failure is not None:
            raise self._failure

    def _output_size(self):
        return self.output.get_size()

    def _composer_width(self) -> int:
        # Sixty-one cells is the product design. On narrower terminals the
        # frame contracts instead of making VSplit display its fallback text.
        return max(min(RUN_PANEL_WIDTH, self._output_size().columns), 1)

    def _scene_height(self) -> Dimension:
        size = self._output_size()
        # Reserve the composer first. Geometry contracts both rain margins
        # before an exceptionally short viewport clips the central block.
        available = max(
            size.rows - COMPOSER_FRAME_ROWS - COMPOSER_MIN_CONTENT_ROWS,
            0,
        )
        if available <= STARTUP_SEPARATOR_ROWS:
            return Dimension.exact(0)
        return Dimension.exact(self.rain.layout_for(
            size.columns, max_height=available - STARTUP_SEPARATOR_ROWS,
        ).height)

    def _separator_height(self) -> Dimension:
        return Dimension.exact(
            STARTUP_SEPARATOR_ROWS if self._scene_height().preferred else 0
        )

    def _safe_composer_content_rows(self) -> int:
        """Return content rows left inside the real terminal viewport."""
        return max(
            self._output_size().rows
            - self._scene_height().preferred
            - self._separator_height().preferred
            - COMPOSER_FRAME_ROWS,
            0,
        )

    def _scene_fragments(self):
        return self.rain.formatted_frame(
            self._output_size().columns, max_height=self._scene_height().preferred,
        )

    def _prompt_lines(self):
        return list(split_lines(to_formatted_text(self.prompt)))

    def _identity_fragments(self):
        lines = self._prompt_lines()
        fragments = []
        for index, line in enumerate(lines[:-1]):
            fragments.extend(line)
            if index + 1 < len(lines) - 1:
                fragments.append(("", "\n"))
        return fragments

    def _prompt_marker(self):
        return self._prompt_lines()[-1]

    def _advance_rain(self, app: Application[object]) -> None:
        self.rain.advance(app.output.get_size().columns)

    def _exit_after_clean_frame(self, app: Application[object]) -> None:
        # after_render is the crucial ordering boundary: the no-rain scene has
        # reached Output before terminal ownership is released.
        if not self.rain.fade_complete:
            return
        if app.renderer._last_screen is not None:
            self.final_screen = app.renderer._last_screen
        if (
            app.is_running
            and app.future is not None
            and not app.future.done()
        ):
            app.exit(result=self._result)

    @staticmethod
    def _continuation_prefix(line_number: int, wrap_count: int):
        if line_number or wrap_count:
            return [("", "    ")]
        return []

    def _composer_container(self) -> HSplit:
        def border(character: str, **kwargs) -> Window:
            return Window(char=character, style="class:frame.border", **kwargs)

        def composer_width() -> Dimension:
            return Dimension.exact(self._composer_width())

        top = VSplit(
            [border("╭", width=1), border("─"), border("╮", width=1)],
            height=1,
        )
        identity_row = VSplit(
            [
                border("│", width=1),
                Window(FormattedTextControl(self._identity_fragments), height=1),
                border("│", width=1),
            ],
            height=1,
            padding=0,
        )
        input_row = VSplit(
            [
                border("│", width=1),
                self.input_window,
                Window(width=Dimension.exact(COMPOSER_RIGHT_PADDING)),
                border("│", width=1),
            ],
            padding=0,
        )
        bottom = VSplit(
            [border("╰", width=1), border("─"), border("╯", width=1)],
            height=1,
        )
        natural_content = HSplit([identity_row, input_row], padding=0)
        bounded_content = HSplit(
            [natural_content],
            height=lambda: desired_composer_content_height(
                natural_content,
                self._composer_width(),
                self._safe_composer_content_rows(),
            ),
            padding=0,
        )
        return HSplit(
            [top, bounded_content, bottom],
            width=composer_width,
            padding=0,
        )

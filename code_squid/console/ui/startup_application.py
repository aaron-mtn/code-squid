"""Temporary single-renderer application for the interactive startup scene."""

from __future__ import annotations

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import AnyFormattedText, to_formatted_text
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.input.base import Input
from prompt_toolkit.key_binding import KeyBindingsBase
from prompt_toolkit.layout import Dimension, HSplit, Layout, Window
from prompt_toolkit.layout.containers import ScrollOffsets, VSplit
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.output.base import Output
from prompt_toolkit.styles import Style

from code_squid.console.ui.binary_header import BinaryRainHeader, FRAME_INTERVAL
from code_squid.console.ui.formatting import RUN_PANEL_WIDTH
from code_squid.console.ui.header_layout import STARTUP_SEPARATOR_ROWS


COMPOSER_RIGHT_PADDING = 1
COMPOSER_MIN_CONTENT_ROWS = 2


class StartupApplication:
    """Own rain, panel, menu presentation, and composer until submission.

    This Application is intentionally temporary and non-full-screen. It exits
    before any agent/run output is printed; normal terminal scrollback resumes
    immediately afterward. Keeping that boundary strict avoids recreating the
    rejected persistent transcript/composer UI.
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
        self.buffer = Buffer(multiline=True)
        self.buffer_control = BufferControl(
            buffer=self.buffer,
            input_processors=[BeforeInput(self._prompt_marker)],
        )
        self.input_window = Window(
            self.buffer_control,
            wrap_lines=True,
            dont_extend_height=True,
            scroll_offsets=ScrollOffsets(top=0, bottom=0),
            get_line_prefix=self._continuation_prefix,
        )
        self.scene_control = FormattedTextControl(self._scene_fragments)
        self.scene_window = Window(
            self.scene_control,
            height=self._scene_height,
            wrap_lines=False,
            always_hide_cursor=True,
        )
        self.composer = self._composer_container()
        root = HSplit(
            [
                self.scene_window,
                Window(height=self._separator_height),
                VSplit([self.composer, Window()], padding=0),
                # A retained non-full-screen Screen can be taller after input
                # shrinks. This neutral sink receives cleanup rows so the box
                # itself always ends at its natural bottom border.
                Window(),
            ],
            padding=0,
        )
        self.application: Application[str] = Application(
            layout=Layout(root, focused_element=self.buffer_control),
            key_bindings=key_bindings,
            style=Style.from_dict({"frame.border": "dim"}),
            full_screen=False,
            erase_when_done=False,
            refresh_interval=FRAME_INTERVAL,
            before_render=self._advance_rain,
            input=input,
            output=output,
        )
        # `/new` constructs a new temporary Application around the same display
        # model, so reset drops here to make every session scene genuinely fresh.
        self.rain.reset(self.application.output.get_size().columns)

    def run(self) -> str:
        """Run until submit or interruption, leaving no live renderer behind."""
        return self.application.run()

    def _output_size(self):
        return self.application.output.get_size()

    def _composer_width(self) -> int:
        # Sixty-one cells is the product design. On narrower terminals the
        # frame contracts instead of making VSplit display its fallback text.
        return max(min(RUN_PANEL_WIDTH, self._output_size().columns), 1)

    def _scene_height(self) -> Dimension:
        size = self._output_size()
        full_height = self.rain.layout_for(size.columns).height
        composer_rows = COMPOSER_MIN_CONTENT_ROWS + 2
        available = max(size.rows - composer_rows, 0)
        if available <= STARTUP_SEPARATOR_ROWS:
            return Dimension.exact(0)
        return Dimension.exact(min(full_height, available - STARTUP_SEPARATOR_ROWS))

    def _separator_height(self) -> Dimension:
        return Dimension.exact(
            STARTUP_SEPARATOR_ROWS if self._scene_height().preferred else 0
        )

    def _scene_fragments(self):
        return self.rain.formatted_frame(self._output_size().columns)

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

    def _advance_rain(self, app: Application[str]) -> None:
        self.rain.advance(app.output.get_size().columns)

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
        return HSplit(
            [top, identity_row, input_row, bottom],
            width=composer_width,
            padding=0,
        )

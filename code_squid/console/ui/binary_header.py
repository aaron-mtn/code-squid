"""Binary-rain state and semantic composition for the startup scene."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random
from typing import TYPE_CHECKING, Sequence

from prompt_toolkit.formatted_text import StyleAndTextTuples

from code_squid.console.ui.banner import StartupInfo, startup_panel_lines
from code_squid.console.ui.header_layout import (
    TITLE,
    TITLE_ROW,
    StartupSceneLayout,
    startup_scene_layout,
)

if TYPE_CHECKING:
    from code_squid.console.startup_menu import StartupMenu

# Kept as the default-scene height for callers that build deterministic frames.
HEADER_HEIGHT = startup_scene_layout(80).height

# This scales each drop's independently randomized movement per frame. Keeping
# it in one obvious place makes presentation tuning possible without a CLI API.
RAIN_SPEED = 0.7
FRAME_INTERVAL = 0.05
DROP_DENSITY = 0.24
# Entry staggering is animation timing, independent of title/margin geometry.
DROP_ENTRY_ROWS = 2
# Eight fade frames (the first is invalidated immediately, followed by seven
# refresh ticks) retain the submitted scene for a nominal 350 ms. Another
# terminal writer may force the state directly to the final frame sooner.
FADE_FRAME_COUNT = 8

# The paired values preserve the head/trail distinction while assigning every
# visible rain cell to the same global intensity step. Restrained neutral grays
# degrade predictably in Windows Terminal without terminal-specific repaint
# behavior.
FADE_RAIN_STYLES: tuple[tuple[str, str], ...] = (
    ("bold", "dim"),
    ("fg:#c0c0c0", "fg:#858585"),
    ("fg:#969696", "fg:#686868"),
    ("fg:#747474", "fg:#505050"),
    ("fg:#595959", "fg:#3e3e3e"),
    ("fg:#454545", "fg:#303030"),
    ("fg:#363636", "fg:#252525"),
    ("fg:#292929", "fg:#1d1d1d"),
)

EMPTY = 0
TRAIL_BIT = 1
HEAD_BIT = 2
TITLE_TEXT = 3
PANEL_TEXT = 4

BRIGHT_STYLE = "\033[1m"
DIM_STYLE = "\033[2m"
RESET_STYLE = "\033[0m"


@dataclass
class Drop:
    """One independently moving column in a binary-rain grid."""

    column: int
    head: float
    speed: float
    bits: list[str]

    @classmethod
    def create(
        cls,
        column: int,
        rng: random.Random,
        *,
        scene_height: int = HEADER_HEIGHT,
    ) -> "Drop":
        """Create a drop initially staggered through the taller rain field."""
        drop = cls(column=column, head=0, speed=0, bits=[])
        drop.reset(rng, initial_scene_height=scene_height)
        return drop

    def reset(
        self,
        rng: random.Random,
        *,
        initial_scene_height: int | None = None,
    ) -> None:
        """Give a drop a new position, sparse trail, and varied speed."""
        if initial_scene_height is None:
            # Later generations enter naturally from above the scene.
            self.head = rng.randint(-DROP_ENTRY_ROWS, 0)
        else:
            # Only initial construction is spread vertically so the first
            # frame already identifies this as a full-height rain field.
            self.head = rng.randint(-DROP_ENTRY_ROWS, max(initial_scene_height - 1, 0))
        self.speed = rng.uniform(0.3, 1.2) * RAIN_SPEED
        trail_length = rng.randint(2, 5)
        self.bits = [rng.choice("01") for _ in range(trail_length + 1)]

    def advance(self, rng: random.Random, *, scene_height: int = HEADER_HEIGHT) -> None:
        """Advance one frame, resetting only after the complete trail has left."""
        self.head += self.speed
        if self.head - len(self.bits) >= scene_height:
            self.reset(rng)

    def advance_without_reset(self) -> None:
        """Advance one fade frame without replacing a drop that leaves."""
        self.head += self.speed

    def bit_at(self, row: int) -> str | None:
        """Return the trail bit visible at ``row``, if this drop covers it."""
        distance = self.head - row
        if distance <= 0 or distance >= len(self.bits):
            return None
        return self.bits[min(int(distance), len(self.bits) - 1)]

    def is_head_at(self, row: int) -> bool:
        """Return whether the rounded drop head occupies ``row``."""
        return int(round(self.head)) == row


def create_drops(
    width: int,
    rng: random.Random,
    density: float = DROP_DENSITY,
    *,
    scene_height: int = HEADER_HEIGHT,
) -> list[Drop]:
    """Create a sparse column subset staggered through the initial scene."""
    return [
        Drop.create(column, rng, scene_height=scene_height)
        for column in range(width)
        if rng.random() < density
    ]


def compose_cells(
    layout: StartupSceneLayout,
    drops: Sequence[Drop],
    panel_lines: Sequence[str],
) -> tuple[list[list[int]], list[list[str]]]:
    """Compose rain and fixed scene elements into semantic cells."""
    cells = [[EMPTY for _ in range(layout.width)] for _ in range(layout.height)]
    bits = [[" " for _ in range(layout.width)] for _ in range(layout.height)]

    for drop in drops:
        if not 0 <= drop.column < layout.width:
            continue
        for row in range(layout.height):
            # The panel owns its complete rectangle. Excluding cells here keeps
            # rain state from ever existing behind its border or content.
            if not layout.cell_allows_rain(row, drop.column):
                continue
            if drop.is_head_at(row):
                cells[row][drop.column] = HEAD_BIT
                bits[row][drop.column] = drop.bits[0]
                continue

            bit = drop.bit_at(row)
            # Multiple drops may share a column in supplied/test state. A later
            # trail must never dim a head already placed by an earlier drop.
            if bit is not None and cells[row][drop.column] != HEAD_BIT:
                cells[row][drop.column] = TRAIL_BIT
                bits[row][drop.column] = bit

    overlay_title(cells, bits, layout)
    overlay_panel(cells, bits, layout, panel_lines)
    return cells, bits


def overlay_title(
    cells: list[list[int]],
    bits: list[list[str]],
    layout: StartupSceneLayout,
) -> None:
    """Center and clip the fixed title over the rain grid."""
    if layout.title_row >= layout.height:
        return
    for offset, character in enumerate(TITLE):
        column = layout.title_column + offset
        if 0 <= column < layout.width:
            cells[layout.title_row][column] = TITLE_TEXT
            bits[layout.title_row][column] = character


def overlay_panel(
    cells: list[list[int]],
    bits: list[list[str]],
    layout: StartupSceneLayout,
    panel_lines: Sequence[str],
) -> None:
    """Place panel-owned text into its reserved rectangle."""
    for row_offset, line in enumerate(panel_lines[: layout.panel.height]):
        row = layout.panel.top + row_offset
        if row >= layout.height:
            break
        for column_offset, character in enumerate(line[: layout.panel.width]):
            column = layout.panel.left + column_offset
            cells[row][column] = PANEL_TEXT
            bits[row][column] = character


def render_cells(
    cells: Sequence[Sequence[int]],
    bits: Sequence[Sequence[str]],
    *,
    ansi: bool = True,
) -> str:
    """Render semantic cells with bright heads, dim trails, and a plain title."""
    lines: list[str] = []
    for row_cells, row_bits in zip(cells, bits):
        line: list[str] = []
        for cell, bit in zip(row_cells, row_bits):
            # Equality is intentional: callers may use equivalent semantic cell
            # values rather than the exact constant objects exported here.
            if cell == HEAD_BIT and ansi:
                line.append(f"{BRIGHT_STYLE}{bit}{RESET_STYLE}")
            elif cell == TRAIL_BIT and ansi:
                line.append(f"{DIM_STYLE}{bit}{RESET_STYLE}")
            elif cell == TITLE_TEXT:
                line.append(bit)
            elif cell in (HEAD_BIT, TRAIL_BIT, PANEL_TEXT):
                line.append(bit)
            else:
                line.append(" ")
        lines.append("".join(line))
    return "\n".join(lines)


def static_title(width: int) -> str:
    """Return a quiet centered title, clipped when the terminal is very narrow."""
    if width <= 0:
        return ""
    if width < len(TITLE):
        trim = len(TITLE) - width
        left = trim // 2
        return TITLE[left : left + width]
    return TITLE.center(width)


class BinaryRainHeader:
    """Hold reusable rain state for the temporary startup application.

    This object deliberately does not write to the terminal or own a worker.
    ``StartupApplication`` advances it and prompt_toolkit renders its cells, so
    every live startup cell belongs to one renderer and coordinate system.
    """

    def __init__(
        self,
        *,
        rng: random.Random | None = None,
        startup_info: StartupInfo | None = None,
    ) -> None:
        self.rng = rng if rng is not None else random.Random()
        self.startup_info = startup_info
        self._width = 0
        self._drops: list[Drop] = []
        self._fade_started = False
        self._fade_step = 0
        self.startup_menu: StartupMenu | None = None

    @property
    def fade_active(self) -> bool:
        """Return whether submitted rain is currently moving and fading."""
        return self._fade_started and self._fade_step < FADE_FRAME_COUNT

    @property
    def fade_complete(self) -> bool:
        """Return whether the final, rain-free startup frame is ready."""
        return self._fade_started and self._fade_step >= FADE_FRAME_COUNT

    def begin_fade(self) -> None:
        """Freeze the current population and begin its global intensity fade."""
        if self._fade_started:
            return
        self._fade_started = True
        self._fade_step = 0

    def advance_fade(self) -> None:
        """Move and dim existing drops, clearing them all at the final step."""
        if not self._fade_started or self.fade_complete:
            return
        # Fade motion deliberately bypasses normal recycling: existing drops
        # may fall out of view, but replacements must not enter after submit.
        for drop in self._drops:
            drop.advance_without_reset()
        self._fade_step += 1
        if self.fade_complete:
            # The last visible step still owns the complete original drop
            # population; the following clean frame removes it atomically.
            self._drops.clear()

    def complete_fade(self) -> None:
        """Advance immediately to the required clean no-rain frame."""
        if not self._fade_started:
            self.begin_fade()
        self._fade_step = FADE_FRAME_COUNT
        self._drops.clear()

    def set_startup_info(self, startup_info: StartupInfo | None) -> None:
        """Set the application-owned values used by subsequent scene frames."""
        self.startup_info = startup_info

    def set_startup_menu(self, startup_menu: StartupMenu | None) -> None:
        """Attach menu state read whenever the Application composes a frame."""
        self.startup_menu = startup_menu

    def reset(self, terminal_columns: int) -> None:
        """Create one fresh deterministic scene for a startup boundary."""
        layout = self.layout_for(terminal_columns)
        self._width = layout.width
        self._fade_started = False
        self._fade_step = 0
        self._drops = create_drops(
            layout.width,
            self.rng,
            scene_height=layout.height,
        )

    def advance(self, terminal_columns: int) -> None:
        """Advance rain state; the owning Application decides when to repaint."""
        layout = self.layout_for(terminal_columns)
        if self._fade_started:
            self.advance_fade()
            return
        if layout.width != self._width or not self._drops:
            self.reset(terminal_columns)
            layout = self.layout_for(terminal_columns)
        for drop in self._drops:
            drop.advance(self.rng, scene_height=layout.height)

    def formatted_frame(
        self, terminal_columns: int, *, max_height: int | None = None,
    ) -> StyleAndTextTuples:
        """Return the current scene as prompt_toolkit-owned styled fragments."""
        layout = self.layout_for(terminal_columns, max_height=max_height)
        if not self._fade_started and (
            layout.width != self._width or not self._drops
        ):
            self.reset(terminal_columns)
        cells, bits = compose_cells(
            layout,
            self._drops,
            self._panel_lines(layout),
        )
        fragments: StyleAndTextTuples = []
        head_style, trail_style = FADE_RAIN_STYLES[
            min(self._fade_step, len(FADE_RAIN_STYLES) - 1)
        ]
        for row_index, (row_cells, row_bits) in enumerate(zip(cells, bits)):
            current_style: str | None = None
            current_text: list[str] = []
            for cell, bit in zip(row_cells, row_bits):
                style = (
                    head_style
                    if cell == HEAD_BIT
                    else trail_style
                    if cell == TRAIL_BIT
                    else ""
                )
                character = bit if cell != EMPTY else " "
                if style != current_style:
                    if current_text:
                        fragments.append((current_style or "", "".join(current_text)))
                    current_style = style
                    current_text = []
                current_text.append(character)
            if current_text:
                fragments.append((current_style or "", "".join(current_text)))
            if row_index + 1 < layout.height:
                fragments.append(("", "\n"))
        return fragments

    def plain_frame(self, terminal_columns: int) -> str:
        """Return a style-free frame for diagnostics and deterministic tests."""
        layout = self.layout_for(terminal_columns)
        if not self._fade_started and (
            layout.width != self._width or not self._drops
        ):
            self.reset(terminal_columns)
        cells, bits = compose_cells(layout, self._drops, self._panel_lines(layout))
        return render_cells(cells, bits, ansi=False)

    def layout_for(
        self, terminal_columns: int, *, max_height: int | None = None,
    ) -> StartupSceneLayout:
        """Return geometry matching the current optional Skill row."""
        show_skill = (
            self.startup_menu is None
            and self.startup_info is not None
            and self.startup_info.skill_name is not None
            and self.startup_info.mod_name is None
        )
        return startup_scene_layout(
            terminal_columns, show_skill=show_skill, max_height=max_height,
        )

    def _panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        """Return panel text without giving the rain layer content ownership."""
        if self.startup_menu is not None:
            return self.startup_menu.panel_lines(layout)
        if self.startup_info is None:
            empty_info = StartupInfo(Path("."), "none", "none", "none")
            return startup_panel_lines(empty_info, layout)
        return startup_panel_lines(self.startup_info, layout)

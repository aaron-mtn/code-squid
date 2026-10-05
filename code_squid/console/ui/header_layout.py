"""Geometry for the composed Code Squid startup scene."""

from __future__ import annotations

from dataclasses import dataclass
import os


TITLE = "c o d e   s q u i d"
TITLE_ROW = 7
TITLE_PANEL_GAP = 2
PANEL_TOP = TITLE_ROW + TITLE_PANEL_GAP + 1
PANEL_MAX_WIDTH = 40
PANEL_MIN_WIDTH = len(TITLE) + 4
# Equal outer margins center the title/menu block without enlarging the panel.
# Short viewports reduce these margins before clipping central content.
RAIN_ROWS_BELOW_PANEL = TITLE_ROW
BASE_PANEL_HEIGHT = 13
SKILL_PANEL_HEIGHT = 15
STARTUP_SEPARATOR_ROWS = 1
# The transient composer contributes top/header/input/bottom rows. Keeping this
# reservation accurate prevents the startup animator from entering its region.
PROMPT_PREFACE_ROWS = 2
PROMPT_INPUT_ROWS = 2


@dataclass(frozen=True)
class Rectangle:
    """A zero-based terminal-cell rectangle."""

    top: int
    left: int
    width: int
    height: int

    @property
    def bottom(self) -> int:
        """Return the inclusive bottom row."""
        return self.top + self.height - 1

    def contains(self, row: int, column: int) -> bool:
        """Return whether a cell belongs to this rectangle."""
        return (
            self.top <= row <= self.bottom
            and self.left <= column < self.left + self.width
        )


@dataclass(frozen=True)
class StartupSceneLayout:
    """All fixed geometry owned by one startup-scene frame."""

    width: int
    height: int
    title_row: int
    title_column: int
    panel: Rectangle
    rain_bottom_row: int

    def cell_is_inside_panel(self, row: int, column: int) -> bool:
        """Return whether the panel, rather than rain, owns a cell."""
        return self.panel.contains(row, column)

    def cell_allows_rain(self, row: int, column: int) -> bool:
        """Return whether rain may occupy a scene cell."""
        return (
            0 <= row <= self.rain_bottom_row
            and 0 <= column < self.width
            and not self.cell_is_inside_panel(row, column)
        )


def terminal_draw_width(size: os.terminal_size) -> int:
    """Return the safe scene width without using the final terminal column."""
    # Writing the final physical column can trigger an eager terminal wrap and
    # corrupt the relative cursor geometry used by live animation.
    return max(size.columns - 1, 0)


def initial_viewport_height(layout: StartupSceneLayout) -> int:
    """Return rows needed to show the scene and initial composer together."""
    return (
        layout.height
        + STARTUP_SEPARATOR_ROWS
        + PROMPT_PREFACE_ROWS
        + PROMPT_INPUT_ROWS
    )


def startup_scene_layout(
    terminal_columns: int,
    *,
    show_skill: bool = False,
    max_height: int | None = None,
) -> StartupSceneLayout:
    """Build centered geometry, reducing decorative margins on short viewports."""
    width = max(terminal_columns - 1, 0)
    panel_width = min(PANEL_MAX_WIDTH, width)
    panel_left = max((width - panel_width) // 2, 0)
    panel_height = SKILL_PANEL_HEIGHT if show_skill else BASE_PANEL_HEIGHT
    block_height = 1 + TITLE_PANEL_GAP + panel_height
    height = block_height + TITLE_ROW + RAIN_ROWS_BELOW_PANEL
    if max_height is not None:
        height = min(height, max(max_height, 0))
    margin_rows = max(height - block_height, 0)
    title_row = margin_rows // 2
    panel = Rectangle(
        title_row + TITLE_PANEL_GAP + 1, panel_left, panel_width, panel_height,
    )
    rain_bottom_row = height - 1
    if width < len(TITLE):
        title_column = -((len(TITLE) - width) // 2)
    else:
        title_column = (width - len(TITLE)) // 2
    return StartupSceneLayout(
        width=width,
        height=rain_bottom_row + 1,
        title_row=title_row,
        title_column=title_column,
        panel=panel,
        rain_bottom_row=rain_bottom_row,
    )

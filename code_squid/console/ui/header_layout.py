"""Geometry for the composed Code Squid startup scene."""

from __future__ import annotations

from dataclasses import dataclass
import os


TITLE = "c o d e   s q u i d"
TITLE_ROW = 2
TITLE_PANEL_GAP = 2
PANEL_TOP = TITLE_ROW + TITLE_PANEL_GAP + 1
PANEL_MAX_WIDTH = 40
PANEL_MIN_WIDTH = len(TITLE) + 4
RAIN_ROWS_BELOW_PANEL = 3
BASE_PANEL_HEIGHT = 13
SKILL_PANEL_HEIGHT = 15
STARTUP_SEPARATOR_ROWS = 1
PROMPT_PREFACE_ROWS = 1
PROMPT_INPUT_ROWS = 1


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
    divider_row: int

    def cell_is_inside_panel(self, row: int, column: int) -> bool:
        """Return whether the panel, rather than rain, owns a cell."""
        return self.panel.contains(row, column)

    def cell_allows_rain(self, row: int, column: int) -> bool:
        """Return whether rain may occupy a scene cell."""
        return (
            0 <= row < self.divider_row
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
) -> StartupSceneLayout:
    """Build the compact centered startup geometry for a terminal width."""
    width = max(terminal_columns - 1, 0)
    panel_width = min(PANEL_MAX_WIDTH, width)
    panel_left = max((width - panel_width) // 2, 0)
    panel_height = SKILL_PANEL_HEIGHT if show_skill else BASE_PANEL_HEIGHT
    panel = Rectangle(PANEL_TOP, panel_left, panel_width, panel_height)
    divider_row = panel.bottom + RAIN_ROWS_BELOW_PANEL + 1
    if width < len(TITLE):
        title_column = -((len(TITLE) - width) // 2)
    else:
        title_column = (width - len(TITLE)) // 2
    return StartupSceneLayout(
        width=width,
        height=divider_row + 1,
        title_row=TITLE_ROW,
        title_column=title_column,
        panel=panel,
        divider_row=divider_row,
    )

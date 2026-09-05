"""Focused tests for reusable binary-rain state and scene composition."""

from pathlib import Path
import random

import pytest

from code_squid.console.ui.banner import StartupInfo, startup_panel_lines
from code_squid.console.ui.binary_header import (
    BRIGHT_STYLE,
    DIM_STYLE,
    EMPTY,
    HEAD_BIT,
    RAIN_SPEED,
    RESET_STYLE,
    PANEL_TEXT,
    TITLE,
    TITLE_ROW,
    TITLE_TEXT,
    TRAIL_BIT,
    BinaryRainHeader,
    Drop,
    compose_cells,
    create_drops,
    overlay_title,
    render_cells,
    static_title,
)
from code_squid.console.ui.header_layout import (
    RAIN_ROWS_BELOW_PANEL,
    TITLE_PANEL_GAP,
    startup_scene_layout,
)


def _startup_info() -> StartupInfo:
    return StartupInfo(
        directory=Path("/tmp/project"),
        provider="openai_compatible",
        model="qwen3.5-9b",
        approval_mode="yolo",
    )


def _empty_grid(width: int):
    layout = startup_scene_layout(width + 1)
    return (
        [[EMPTY for _ in range(width)] for _ in range(layout.height)],
        [[" " for _ in range(width)] for _ in range(layout.height)],
    )


def test_composition_distinguishes_rain_then_overlays_title_and_panel() -> None:
    layout = startup_scene_layout(80)
    panel = startup_panel_lines(_startup_info(), layout)
    drops = [
        Drop(column=layout.panel.left - 1, head=6.0, speed=0.1, bits=["1"] * 8),
        Drop(column=layout.panel.left, head=6.0, speed=0.1, bits=["0"] * 8),
    ]

    cells, bits = compose_cells(layout, drops, panel)

    assert cells[5][layout.panel.left - 1] in (HEAD_BIT, TRAIL_BIT)
    assert cells[layout.panel.top][layout.panel.left] == PANEL_TEXT
    title_slice = cells[TITLE_ROW][
        layout.title_column : layout.title_column + len(TITLE)
    ]
    assert title_slice == [TITLE_TEXT] * len(TITLE)
    assert TITLE in "".join(bits[TITLE_ROW])


def test_head_wins_over_a_later_trail_in_the_same_cell() -> None:
    layout = startup_scene_layout(len(TITLE) + 5)
    head = Drop(column=0, head=2.0, speed=0.1, bits=["1", "0"])
    trail = Drop(column=0, head=3.5, speed=0.1, bits=["0", "0", "0"])

    cells, bits = compose_cells(
        layout, [head, trail], startup_panel_lines(_startup_info(), layout)
    )

    assert (cells[2][0], bits[2][0]) == (HEAD_BIT, "1")


def test_title_is_centered_and_clipped_semantically() -> None:
    layout = startup_scene_layout(8)
    cells, bits = _empty_grid(7)
    overlay_title(cells, bits, layout)

    assert cells[TITLE_ROW] == [TITLE_TEXT] * 7
    assert "".join(bits[TITLE_ROW]) == TITLE[6:13]
    assert static_title(7) == TITLE[6:13]


@pytest.mark.parametrize("columns", [24, 40, 80])
def test_scene_layout_stays_in_bounds(columns: int) -> None:
    layout = startup_scene_layout(columns)

    assert layout.panel.left >= 0
    assert layout.panel.left + layout.panel.width <= layout.width
    assert layout.title_row < layout.panel.top
    assert layout.panel.top - layout.title_row - 1 == TITLE_PANEL_GAP
    assert layout.rain_bottom_row - layout.panel.bottom == RAIN_ROWS_BELOW_PANEL


def test_rendering_uses_expected_semantic_styles() -> None:
    rendered = render_cells(
        [[HEAD_BIT, TRAIL_BIT, TITLE_TEXT, EMPTY]],
        [["1", "0", "x", " "]],
    )

    assert rendered == f"{BRIGHT_STYLE}1{RESET_STYLE}{DIM_STYLE}0{RESET_STYLE}x "


def test_seeded_model_produces_distinct_frames_without_terminal_writes() -> None:
    rain = BinaryRainHeader(rng=random.Random(7), startup_info=_startup_info())
    first = rain.plain_frame(80)
    frames = []
    for _ in range(12):
        rain.advance(80)
        frames.append(rain.plain_frame(80))

    assert any(frame != first for frame in frames)
    assert all(TITLE in frame for frame in frames)
    layout = startup_scene_layout(80)
    panel_rows = range(layout.panel.top, layout.panel.bottom + 1)
    panel = layout.panel
    first_panel = [
        first.splitlines()[row][panel.left : panel.left + panel.width]
        for row in panel_rows
    ]
    assert all(
        [
            frame.splitlines()[row][panel.left : panel.left + panel.width]
            for row in panel_rows
        ]
        == first_panel
        for frame in frames
    )


def test_resize_rebuilds_drops_for_the_new_prompt_toolkit_width() -> None:
    rain = BinaryRainHeader(rng=random.Random(3), startup_info=_startup_info())
    rain.advance(80)
    old_drops = rain._drops

    rain.advance(40)

    assert rain._drops is not old_drops
    assert rain._width == startup_scene_layout(40).width
    assert all(drop.column < rain._width for drop in rain._drops)


def test_rain_speed_remains_the_designed_factor() -> None:
    assert RAIN_SPEED == 0.7
    drops = create_drops(80, random.Random(1), density=1.0)
    assert len({drop.speed for drop in drops}) > 1

"""Focused tests for reusable binary-rain state and scene composition."""

from pathlib import Path
import random

import pytest

from code_squid.console.ui.banner import StartupInfo, startup_panel_lines
from code_squid.console.ui.binary_header import (
    BRIGHT_STYLE,
    DIM_STYLE,
    DROP_ENTRY_ROWS,
    EMPTY,
    FADE_FRAME_COUNT,
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


def _rain_positions(rain: BinaryRainHeader, columns: int) -> set[tuple[int, int]]:
    layout = rain.layout_for(columns)
    cells, _ = compose_cells(layout, rain._drops, rain._panel_lines(layout))
    return {
        (row, column)
        for row, line in enumerate(cells)
        for column, cell in enumerate(line)
        if cell in (HEAD_BIT, TRAIL_BIT)
    }


def _rain_styles(rain: BinaryRainHeader, columns: int) -> set[str]:
    return {
        style
        for style, text in rain.formatted_frame(columns)
        if style and any(bit in text for bit in "01")
    }


def _fixed_scene_content(
    rain: BinaryRainHeader,
    columns: int,
) -> tuple[str, tuple[str, ...]]:
    layout = rain.layout_for(columns)
    _, bits = compose_cells(layout, rain._drops, rain._panel_lines(layout))
    title = "".join(
        bits[layout.title_row][
            layout.title_column : layout.title_column + len(TITLE)
        ]
    )
    panel = tuple(
        "".join(
            bits[row][layout.panel.left : layout.panel.left + layout.panel.width]
        )
        for row in range(layout.panel.top, layout.panel.bottom + 1)
    )
    return title, panel


def test_fade_moves_existing_drops_until_the_final_clean_step() -> None:
    rain = BinaryRainHeader(rng=random.Random(5), startup_info=_startup_info())
    rain.reset(80)
    original_drops = [
        (id(drop), drop.column, drop.speed, tuple(drop.bits))
        for drop in rain._drops
    ]
    original_heads = [drop.head for drop in rain._drops]
    fixed_content = _fixed_scene_content(rain, 80)
    style_steps = []

    rain.begin_fade()
    assert [
        (id(drop), drop.column, drop.speed, tuple(drop.bits))
        for drop in rain._drops
    ] == original_drops
    style_steps.append(_rain_styles(rain, 80))
    for frame in range(1, FADE_FRAME_COUNT):
        rain.advance(40)  # Resizing must not rebuild frozen fade state either.
        assert [
            (id(drop), drop.column, drop.speed, tuple(drop.bits))
            for drop in rain._drops
        ] == original_drops
        assert [drop.head for drop in rain._drops] == pytest.approx(
            [
                head + (drop.speed * frame)
                for head, drop in zip(original_heads, rain._drops)
            ]
        )
        assert _fixed_scene_content(rain, 80) == fixed_content
        style_steps.append(_rain_styles(rain, 80))

    assert len(set(map(frozenset, style_steps))) == FADE_FRAME_COUNT
    assert len(rain._drops) == len(original_drops)
    assert _rain_positions(rain, 80)
    assert rain.fade_complete is False

    rain.advance(40)

    assert rain.fade_complete is True
    assert rain._drops == []
    assert all(style not in {"bold", "dim"} for style, _ in rain.formatted_frame(40))
    final_plain_frame = rain.plain_frame(80)
    assert "0" not in final_plain_frame
    assert "1" not in final_plain_frame


def test_drop_that_leaves_during_fade_is_not_reset_or_replaced() -> None:
    rain = BinaryRainHeader(rng=random.Random(6), startup_info=_startup_info())
    layout = rain.layout_for(80)
    departing = Drop(
        column=0,
        head=float(layout.height + 3),
        speed=0.5,
        bits=["1", "0"],
    )
    rain._width = layout.width
    rain._drops = [departing]

    rain.begin_fade()
    rain.advance(80)

    assert rain._drops == [departing]
    assert departing.head == layout.height + 3.5
    assert departing.speed == 0.5
    assert departing.bits == ["1", "0"]


def test_normal_rain_still_resets_a_completed_drop() -> None:
    scene_height = 10
    drop = Drop(column=0, head=13.0, speed=0.5, bits=["1", "0"])

    drop.advance(random.Random(9), scene_height=scene_height)

    assert -DROP_ENTRY_ROWS <= drop.head <= 0
    assert 0.3 * RAIN_SPEED <= drop.speed <= 1.2 * RAIN_SPEED
    assert 3 <= len(drop.bits) <= 6


def test_forced_fade_completion_never_repopulates_rain() -> None:
    rain = BinaryRainHeader(rng=random.Random(8), startup_info=_startup_info())
    rain.reset(80)

    rain.begin_fade()
    rain.complete_fade()
    rain.advance(120)
    rain.plain_frame(120)

    assert rain.fade_complete is True
    assert rain._drops == []


@pytest.mark.parametrize("show_skill", [False, True])
@pytest.mark.parametrize("height", [0, 4, 12, 19, 24, 27, 30, 50])
def test_height_budget_centers_block_and_reduces_margins_before_clipping(
    height: int, show_skill: bool,
) -> None:
    layout = startup_scene_layout(80, show_skill=show_skill, max_height=height)
    assert layout.height <= height
    assert layout.panel.height == (15 if show_skill else 13)
    block_height = 1 + TITLE_PANEL_GAP + layout.panel.height
    if height >= block_height:
        top_margin = layout.title_row
        bottom_margin = layout.height - layout.panel.bottom - 1
        assert 0 <= bottom_margin - top_margin <= 1
    else:
        assert layout.title_row == 0
    info = _startup_info()
    if show_skill:
        from dataclasses import replace
        info = replace(info, skill_name="test-skill")
    cells, bits = compose_cells(layout, [], startup_panel_lines(info, layout))
    assert len(cells) == len(bits) == layout.height


def test_default_rain_has_seven_rows_above_and_below_central_block() -> None:
    layout = startup_scene_layout(80)
    assert layout.title_row == 7
    assert layout.height - layout.panel.bottom - 1 == 7
    assert layout.panel.height == 13

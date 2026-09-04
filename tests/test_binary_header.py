"""Focused tests for the bounded binary-rain console header."""

from __future__ import annotations

import os
import random

import pytest

from code_squid.console.ui.binary_header import (
    BRIGHT_STYLE,
    DIM_STYLE,
    EMPTY,
    FRAME_INTERVAL,
    HEAD_BIT,
    HEADER_HEIGHT,
    HIDE_CURSOR,
    RAIN_SPEED,
    RESET_STYLE,
    SHOW_CURSOR,
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


class FakeStream:
    def __init__(self, tty: bool) -> None:
        self.tty = tty
        self.writes: list[str] = []
        self.flushes = 0

    def isatty(self) -> bool:
        return self.tty

    def write(self, value: str) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        self.flushes += 1


def _empty_grid(width: int) -> tuple[list[list[int]], list[list[str]]]:
    return (
        [[EMPTY for _ in range(width)] for _ in range(HEADER_HEIGHT)],
        [[" " for _ in range(width)] for _ in range(HEADER_HEIGHT)],
    )


def test_composition_distinguishes_head_and_trail_then_overlays_title() -> None:
    drop = Drop(column=0, head=2.0, speed=0.1, bits=["1", "0", "1"])

    cells, bits = compose_cells(len(TITLE) + 4, [drop])

    assert (cells[2][0], bits[2][0]) == (HEAD_BIT, "1")
    assert (cells[1][0], bits[1][0]) == (TRAIL_BIT, "0")
    assert cells[TITLE_ROW][2 : 2 + len(TITLE)] == [TITLE_TEXT] * len(TITLE)
    assert "".join(bits[TITLE_ROW][2 : 2 + len(TITLE)]) == TITLE


def test_head_wins_when_a_later_drop_places_a_trail_in_same_cell() -> None:
    head = Drop(column=0, head=2.0, speed=0.1, bits=["1", "0"])
    trail = Drop(column=0, head=3.5, speed=0.1, bits=["0", "0", "0"])

    cells, bits = compose_cells(1, [head, trail])

    assert (cells[2][0], bits[2][0]) == (HEAD_BIT, "1")


def test_title_is_centered_and_clipped_semantically() -> None:
    cells, bits = _empty_grid(7)

    overlay_title(cells, bits, 7)

    assert cells[TITLE_ROW] == [TITLE_TEXT] * 7
    assert "".join(bits[TITLE_ROW]) == TITLE[6:13]
    assert static_title(7) == TITLE[6:13]
    assert static_title(len(TITLE) + 4) == f"  {TITLE}  "


def test_title_overlay_replaces_rain_cells() -> None:
    width = len(TITLE) + 4
    cells, bits = _empty_grid(width)
    cells[TITLE_ROW] = [HEAD_BIT] * width
    bits[TITLE_ROW] = ["1"] * width

    overlay_title(cells, bits, width)

    assert cells[TITLE_ROW][2 : 2 + len(TITLE)] == [TITLE_TEXT] * len(TITLE)
    assert "".join(bits[TITLE_ROW][2 : 2 + len(TITLE)]) == TITLE


class EqualHead:
    def __eq__(self, other: object) -> bool:
        return other == HEAD_BIT


def test_rendering_uses_semantic_equality_and_expected_styles() -> None:
    rendered = render_cells(
        [[EqualHead(), TRAIL_BIT, TITLE_TEXT, EMPTY]],
        [["1", "0", "x", " "]],
    )

    assert rendered == (
        f"{BRIGHT_STYLE}1{RESET_STYLE}"
        f"{DIM_STYLE}0{RESET_STYLE}"
        "x "
    )


def test_configured_speed_matches_preferred_prototype_factor() -> None:
    assert RAIN_SPEED == 0.2


def test_seeded_drops_have_varied_speeds_and_reset_to_a_new_speed() -> None:
    rng = random.Random(7)
    drops = create_drops(80, rng, density=1.0)
    speeds = {drop.speed for drop in drops}
    drop = drops[0]
    old_speed = drop.speed
    drop.head = HEADER_HEIGHT + len(drop.bits)

    drop.advance(rng)

    assert len(speeds) > 1
    assert 0.3 * RAIN_SPEED <= drop.speed <= 1.2 * RAIN_SPEED
    assert drop.speed != old_speed


def test_non_tty_uses_static_fallback_without_ansi() -> None:
    stream = FakeStream(tty=False)
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((40, 20)),
    )

    assert header.show() is False
    assert stream.writes == [f"{TITLE.center(40)}\n"]


def test_narrow_tty_uses_clipped_static_fallback() -> None:
    stream = FakeStream(tty=True)
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((7, 20)),
        ansi_supported=lambda stream: True,
    )

    assert header.show() is False
    assert stream.writes == [f"{TITLE[6:13]}\n"]


def test_bounded_animation_restores_cursor_and_leaves_output_below_header() -> None:
    stream = FakeStream(tty=True)
    sleeps: list[float] = []
    header = BinaryRainHeader(
        stream=stream,
        frame_count=2,
        rng=random.Random(2),
        sleeper=sleeps.append,
        terminal_size=lambda: os.terminal_size((40, 20)),
        ansi_supported=lambda stream: True,
    )

    assert header.show() is True

    assert stream.writes[0] == HIDE_CURSOR
    assert stream.writes[-1] == SHOW_CURSOR
    assert stream.writes[1].endswith("\r\n")
    assert stream.writes[2].startswith(f"\033[{HEADER_HEIGHT}A")
    assert sleeps == [FRAME_INTERVAL]


def test_cursor_is_restored_when_animation_raises() -> None:
    stream = FakeStream(tty=True)

    def fail_sleep(_: float) -> None:
        raise RuntimeError("test failure")

    header = BinaryRainHeader(
        stream=stream,
        frame_count=2,
        sleeper=fail_sleep,
        terminal_size=lambda: os.terminal_size((40, 20)),
        ansi_supported=lambda stream: True,
    )

    with pytest.raises(RuntimeError, match="test failure"):
        header.show()

    assert stream.writes[-1] == SHOW_CURSOR


def test_cursor_is_restored_when_initial_flush_fails() -> None:
    class FailingFlushStream(FakeStream):
        def flush(self) -> None:
            self.flushes += 1
            if self.flushes == 1:
                raise OSError("closed")

    stream = FailingFlushStream(tty=True)
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((40, 20)),
        ansi_supported=lambda stream: True,
    )

    assert header.show() is False
    assert stream.writes == [HIDE_CURSOR, SHOW_CURSOR]


def test_zero_frame_configuration_uses_static_fallback() -> None:
    stream = FakeStream(tty=True)
    header = BinaryRainHeader(
        stream=stream,
        frame_count=0,
        terminal_size=lambda: os.terminal_size((40, 20)),
        ansi_supported=lambda stream: True,
    )

    assert header.show() is False
    assert stream.writes == [f"{TITLE.center(40)}\n"]


def test_terminal_width_change_rebuilds_without_using_last_physical_column() -> None:
    stream = FakeStream(tty=True)
    sizes = iter(
        [
            os.terminal_size((40, 20)),
            os.terminal_size((40, 20)),
            os.terminal_size((32, 20)),
        ]
    )
    header = BinaryRainHeader(
        stream=stream,
        frame_count=2,
        rng=random.Random(3),
        sleeper=lambda _: None,
        terminal_size=lambda: next(sizes),
        ansi_supported=lambda stream: True,
    )

    assert header.show() is True

    final_frame_rows = stream.writes[2].split("\033[2K\r")[1:]
    visible_rows = [row.removesuffix("\r\n") for row in final_frame_rows]
    assert len(visible_rows) == HEADER_HEIGHT
    assert all(len(_strip_ansi(row)) == 31 for row in visible_rows)


def _strip_ansi(value: str) -> str:
    for sequence in (BRIGHT_STYLE, DIM_STYLE, RESET_STYLE):
        value = value.replace(sequence, "")
    return value

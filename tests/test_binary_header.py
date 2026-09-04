"""Focused tests for the bounded binary-rain console header."""

from __future__ import annotations

import os
from pathlib import Path
import random
import threading

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
    DIVIDER_TEXT,
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
from code_squid.console.ui.banner import StartupInfo, startup_panel_lines
from code_squid.console.ui.header_layout import (
    BASE_PANEL_HEIGHT,
    RAIN_ROWS_BELOW_PANEL,
    TITLE_PANEL_GAP,
    initial_viewport_height,
    startup_scene_layout,
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


class SignalingStream(FakeStream):
    """Expose worker redraws without relying on timing sleeps."""

    def __init__(self) -> None:
        super().__init__(tty=True)
        self.worker_write = threading.Event()

    def write(self, value: str) -> int:
        result = super().write(value)
        if threading.current_thread().name == "code-squid-binary-rain":
            self.worker_write.set()
        return result


class MutableTerminalSize:
    """Provide deterministic resize control to lifecycle tests."""

    def __init__(self, columns: int = 40, lines: int = 30) -> None:
        self.size = os.terminal_size((columns, lines))

    def __call__(self) -> os.terminal_size:
        return self.size


def _empty_grid(width: int) -> tuple[list[list[int]], list[list[str]]]:
    layout = startup_scene_layout(width + 1)
    return (
        [[EMPTY for _ in range(width)] for _ in range(layout.height)],
        [[" " for _ in range(width)] for _ in range(layout.height)],
    )


def _startup_info(*, skill_name: str | None = None) -> StartupInfo:
    return StartupInfo(
        directory=Path("/tmp/project"),
        provider="openai_compatible",
        model="qwen3.5-9b",
        approval_mode="yolo",
        skill_name=skill_name,
    )


def test_composition_distinguishes_head_and_trail_then_overlays_title() -> None:
    layout = startup_scene_layout(len(TITLE) + 5)
    drop = Drop(column=0, head=2.0, speed=0.1, bits=["1", "0", "1"])

    cells, bits = compose_cells(
        layout,
        [drop],
        startup_panel_lines(_startup_info(), layout),
    )

    assert (cells[2][0], bits[2][0]) == (HEAD_BIT, "1")
    assert (cells[1][0], bits[1][0]) == (TRAIL_BIT, "0")
    assert cells[TITLE_ROW][layout.title_column : layout.title_column + len(TITLE)] == [
        TITLE_TEXT
    ] * len(TITLE)
    assert "".join(
        bits[TITLE_ROW][layout.title_column : layout.title_column + len(TITLE)]
    ) == TITLE


def test_head_wins_when_a_later_drop_places_a_trail_in_same_cell() -> None:
    layout = startup_scene_layout(len(TITLE) + 5)
    head = Drop(column=0, head=2.0, speed=0.1, bits=["1", "0"])
    trail = Drop(column=0, head=3.5, speed=0.1, bits=["0", "0", "0"])

    cells, bits = compose_cells(
        layout,
        [head, trail],
        startup_panel_lines(_startup_info(), layout),
    )

    assert (cells[2][0], bits[2][0]) == (HEAD_BIT, "1")


def test_title_is_centered_and_clipped_semantically() -> None:
    layout = startup_scene_layout(8)
    cells, bits = _empty_grid(7)

    overlay_title(cells, bits, layout)

    assert cells[TITLE_ROW] == [TITLE_TEXT] * 7
    assert "".join(bits[TITLE_ROW]) == TITLE[6:13]
    assert static_title(7) == TITLE[6:13]
    assert static_title(len(TITLE) + 4) == f"  {TITLE}  "


def test_title_overlay_replaces_rain_cells() -> None:
    width = len(TITLE) + 4
    layout = startup_scene_layout(width + 1)
    cells, bits = _empty_grid(width)
    cells[TITLE_ROW] = [HEAD_BIT] * width
    bits[TITLE_ROW] = ["1"] * width

    overlay_title(cells, bits, layout)

    assert cells[TITLE_ROW][2 : 2 + len(TITLE)] == [TITLE_TEXT] * len(TITLE)
    assert "".join(bits[TITLE_ROW][2 : 2 + len(TITLE)]) == TITLE


@pytest.mark.parametrize("columns", [24, 40, 80])
def test_scene_layout_centers_panel_and_keeps_all_geometry_in_bounds(
    columns: int,
) -> None:
    layout = startup_scene_layout(columns)

    assert abs(layout.panel.left - (layout.width - layout.panel.width) / 2) <= 0.5
    assert layout.panel.left >= 0
    assert layout.panel.left + layout.panel.width <= layout.width
    assert layout.title_column == (layout.width - len(TITLE)) // 2
    assert layout.title_row < layout.panel.top
    assert layout.divider_row == layout.height - 1
    assert layout.divider_row - layout.panel.bottom - 1 == RAIN_ROWS_BELOW_PANEL


def test_composition_reserves_panel_and_allows_rain_around_and_below_it() -> None:
    layout = startup_scene_layout(80)
    panel = startup_panel_lines(_startup_info(), layout)
    columns = [
        layout.panel.left - 1,
        layout.panel.left,
        layout.panel.left + layout.panel.width,
    ]
    drops = [
        Drop(column=column, head=float(layout.divider_row), speed=0.1, bits=["1"] * 30)
        for column in columns
    ]

    cells, _ = compose_cells(layout, drops, panel)

    for row in range(layout.panel.top, layout.panel.bottom + 1):
        assert all(
            cells[row][column] == PANEL_TEXT
            for column in range(layout.panel.left, layout.panel.left + layout.panel.width)
        )
    assert cells[layout.panel.top][layout.panel.left - 1] in (HEAD_BIT, TRAIL_BIT)
    assert cells[layout.panel.bottom + 1][layout.panel.left] in (HEAD_BIT, TRAIL_BIT)
    assert all(cell == DIVIDER_TEXT for cell in cells[layout.divider_row])


def test_scene_render_height_title_and_dim_divider_are_deterministic() -> None:
    layout = startup_scene_layout(80)
    cells, bits = compose_cells(layout, [], startup_panel_lines(_startup_info(), layout))

    rendered = render_cells(cells, bits)
    lines = rendered.splitlines()

    assert len(lines) == layout.height
    assert TITLE in lines[layout.title_row]
    assert lines[layout.divider_row] == f"{DIM_STYLE}{'─' * layout.width}{RESET_STYLE}"


def test_initial_drop_generation_populates_rain_above_beside_and_below_panel() -> None:
    layout = startup_scene_layout(80)
    rng = random.Random(1)
    drops = create_drops(
        layout.width,
        rng,
        scene_height=layout.divider_row,
    )
    for drop in drops:
        drop.advance(rng, scene_height=layout.divider_row)

    cells, _ = compose_cells(
        layout,
        drops,
        startup_panel_lines(_startup_info(), layout),
    )
    rain = (HEAD_BIT, TRAIL_BIT)

    assert any(cell in rain for row in cells[: layout.panel.top] for cell in row)
    assert any(
        cells[row][column] in rain
        for row in range(layout.panel.top, layout.panel.bottom + 1)
        for column in range(layout.width)
        if not layout.cell_is_inside_panel(row, column)
    )
    assert any(
        cell in rain
        for row in cells[layout.panel.bottom + 1 : layout.divider_row]
        for cell in row
    )
    assert all(
        cells[row][column] == PANEL_TEXT
        for row in range(layout.panel.top, layout.panel.bottom + 1)
        for column in range(layout.panel.left, layout.panel.left + layout.panel.width)
    )


def test_initial_drop_heads_are_distributed_across_composed_scene_height() -> None:
    layout = startup_scene_layout(80)
    drops = create_drops(
        layout.width,
        random.Random(7),
        density=1.0,
        scene_height=layout.divider_row,
    )

    assert min(drop.head for drop in drops) <= layout.title_row
    assert max(drop.head for drop in drops) > layout.panel.bottom
    assert len({int(drop.head) for drop in drops}) > layout.divider_row // 2


def test_roomy_scene_geometry_keeps_two_rows_between_title_and_panel() -> None:
    layout = startup_scene_layout(80)

    assert layout.panel.height == BASE_PANEL_HEIGHT
    assert layout.panel.top - layout.title_row - 1 == TITLE_PANEL_GAP
    assert layout.divider_row - layout.panel.bottom - 1 == RAIN_ROWS_BELOW_PANEL


def test_initial_viewport_reservation_matches_scene_and_prompt_height() -> None:
    size = os.terminal_size((80, 30))
    stream = FakeStream(tty=True)
    header = BinaryRainHeader(
        stream=stream,
        rng=random.Random(1),
        terminal_size=lambda: size,
        ansi_supported=lambda stream: True,
        startup_info=_startup_info(),
    )
    layout = startup_scene_layout(size.columns)

    assert header.start() is True

    reserved_rows = initial_viewport_height(layout) - 1
    assert stream.writes[0] == (
        ("\r\n" * reserved_rows) + f"\033[{reserved_rows}A\r"
    )
    assert len(stream.writes) == 2
    header.stop()


def test_short_terminal_fallback_does_not_use_viewport_cursor_movement() -> None:
    stream = FakeStream(tty=True)
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((80, 20)),
        ansi_supported=lambda stream: True,
        startup_info=_startup_info(),
    )

    assert header.start() is False
    assert len(stream.writes) == 1
    assert TITLE in stream.writes[0]
    assert "\033[" not in stream.writes[0]


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
    assert RAIN_SPEED == 0.7


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
    rendered = stream.writes[0]
    assert TITLE in rendered
    assert "Provider  none" in rendered
    assert rendered.splitlines()[-1] == "─" * 39
    assert "\033[" not in rendered


def test_non_tty_start_never_creates_animator() -> None:
    stream = FakeStream(tty=False)
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((40, 20)),
    )

    assert header.start() is False
    assert header.has_animator is False
    assert header.start() is False
    assert len(stream.writes) == 1
    assert TITLE in stream.writes[0]


def test_lifecycle_owns_one_worker_and_preserves_state_across_pause_resume() -> None:
    stream = SignalingStream()
    header = BinaryRainHeader(
        stream=stream,
        rng=random.Random(9),
        frame_interval=10,
        terminal_size=lambda: os.terminal_size((40, 30)),
        ansi_supported=lambda stream: True,
    )

    assert header.start() is True
    worker = header._thread
    assert worker is not None
    assert header.start() is True
    assert header._thread is worker

    drops = header._drops
    stream.worker_write.clear()
    header.resume()
    assert stream.worker_write.wait(timeout=1)
    header.pause()
    writes_after_pause = len(stream.writes)
    assert header._drops is drops

    assert header.reanchor() is True
    assert len(stream.writes) == writes_after_pause + 1
    assert header._drops is drops

    stream.worker_write.clear()
    header.resume()
    assert stream.worker_write.wait(timeout=1)
    header.pause()
    assert len(stream.writes) > writes_after_pause
    assert header._drops is drops

    header.stop()
    assert not worker.is_alive()
    assert header.has_animator is False
    assert stream.writes[-1] == SHOW_CURSOR


@pytest.mark.parametrize(
    "resized",
    [os.terminal_size((32, 30)), os.terminal_size((40, 20))],
    ids=["width", "height"],
)
def test_live_resize_invalidates_anchor_without_writing_stale_frame(
    resized: os.terminal_size,
) -> None:
    stream = FakeStream(tty=True)
    terminal_size = MutableTerminalSize()
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=terminal_size,
        ansi_supported=lambda stream: True,
    )
    assert header.start() is True
    writes_before_resize = len(stream.writes)

    terminal_size.size = resized
    assert header._render_next_frame(anchored=True) is False

    assert len(stream.writes) == writes_before_resize
    assert header.needs_reanchor is True
    assert header._paused is True
    header.stop()


def test_write_live_frame_rechecks_size_before_relative_cursor_output() -> None:
    stream = FakeStream(tty=True)
    terminal_size = MutableTerminalSize()
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=terminal_size,
        ansi_supported=lambda stream: True,
    )
    assert header.start() is True
    writes_before_resize = len(stream.writes)

    terminal_size.size = os.terminal_size((41, 30))
    assert header.write_live_frame("\n".join(["0"] * HEADER_HEIGHT)) is False

    assert len(stream.writes) == writes_before_resize
    assert header.needs_reanchor is True
    header.stop()


def test_live_anchor_counts_wrapped_startup_content_rows() -> None:
    stream = FakeStream(tty=True)
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((40, 40)),
        ansi_supported=lambda stream: True,
    )
    assert header.start() is True
    header.set_live_content_below_header("x" * 41 + "\n\nshort", extra_rows=2)

    frame = "\n".join(["0"] * HEADER_HEIGHT)
    assert header.write_live_frame(frame) is True

    # Wrapped content uses two rows, then one blank and one short row, plus the
    # separator and prompt identity: six rows beneath the composed scene.
    assert stream.writes[-1].startswith(f"{HIDE_CURSOR}\033[{HEADER_HEIGHT + 6}A")
    header.stop()


def test_next_prompt_boundary_reanchors_and_reuses_the_only_worker() -> None:
    stream = SignalingStream()
    terminal_size = MutableTerminalSize()
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=terminal_size,
        ansi_supported=lambda stream: True,
        frame_interval=10,
    )
    assert header.start() is True
    worker = header._thread
    terminal_size.size = os.terminal_size((34, 30))
    assert header._render_next_frame(anchored=True) is False

    assert header.reanchor() is True
    assert header.needs_reanchor is False
    assert header._thread is worker
    stream.worker_write.clear()
    header.resume()
    assert stream.worker_write.wait(timeout=1)
    header.pause()
    assert header._thread is worker
    header.stop()


def test_too_small_resize_stays_paused_until_a_safe_prompt_boundary() -> None:
    stream = FakeStream(tty=True)
    terminal_size = MutableTerminalSize()
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=terminal_size,
        ansi_supported=lambda stream: True,
    )
    assert header.start() is True
    worker = header._thread

    # The header alone fits, but the anchored header plus prompt region does not.
    terminal_size.size = os.terminal_size((40, HEADER_HEIGHT + 2))
    assert header._render_next_frame(anchored=True) is False
    assert header.reanchor() is False
    header.resume()
    assert header.needs_reanchor is True
    assert header._thread is worker

    # Exit cleanup remains safe even though no suitable re-anchor was possible.
    header.stop()
    header.stop()
    assert worker is not None and not worker.is_alive()
    assert header.has_animator is False


def test_narrow_tty_uses_clipped_static_fallback() -> None:
    stream = FakeStream(tty=True)
    header = BinaryRainHeader(
        stream=stream,
        terminal_size=lambda: os.terminal_size((7, 20)),
        ansi_supported=lambda stream: True,
    )

    assert header.show() is False
    rendered = stream.writes[0]
    assert static_title(6) in rendered
    assert all(len(line) == 6 for line in rendered.splitlines())


def test_bounded_animation_restores_cursor_and_leaves_output_below_header() -> None:
    stream = FakeStream(tty=True)
    sleeps: list[float] = []
    header = BinaryRainHeader(
        stream=stream,
        frame_count=2,
        rng=random.Random(2),
        sleeper=sleeps.append,
        terminal_size=lambda: os.terminal_size((40, 30)),
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
        terminal_size=lambda: os.terminal_size((40, 30)),
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
        terminal_size=lambda: os.terminal_size((40, 30)),
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
    assert TITLE in stream.writes[0]
    assert "\033[" not in stream.writes[0]


def test_terminal_width_change_rebuilds_without_using_last_physical_column() -> None:
    stream = FakeStream(tty=True)
    sizes = iter(
        [
            os.terminal_size((40, 30)),
            os.terminal_size((40, 30)),
            os.terminal_size((32, 30)),
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

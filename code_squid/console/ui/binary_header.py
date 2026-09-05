"""Binary-rain state, composition, and lifecycle for the startup scene."""

from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import math
import os
from pathlib import Path
import random
import re
import shutil
import sys
import threading
import time
from typing import TYPE_CHECKING, Callable, Sequence, TextIO

from code_squid.console.ui.banner import StartupInfo, startup_panel_lines
from code_squid.console.ui.header_layout import (
    PANEL_MIN_WIDTH,
    TITLE,
    TITLE_ROW,
    StartupSceneLayout,
    initial_viewport_height,
    startup_scene_layout,
    terminal_draw_width,
)

if TYPE_CHECKING:
    from code_squid.console.startup_menu import StartupMenu

# Kept as the default-scene height for callers that build deterministic frames.
HEADER_HEIGHT = startup_scene_layout(80).height
MIN_WIDTH = len(TITLE) + 4
MIN_HEIGHT = HEADER_HEIGHT + 3

# This scales each drop's independently randomized movement per frame. Keeping
# it in one obvious place makes presentation tuning possible without a CLI API.
RAIN_SPEED = 0.7
FRAME_INTERVAL = 0.05
STARTUP_FRAME_COUNT = 24
DROP_DENSITY = 0.24
# One blank separator and the prompt identity sit between the composed scene
# and prompt_toolkit's input layout. The display may replace this count when
# another caller introduces physical content at that boundary.
DEFAULT_LIVE_ROWS_BELOW_HEADER = 2
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

EMPTY = 0
TRAIL_BIT = 1
HEAD_BIT = 2
TITLE_TEXT = 3
PANEL_TEXT = 4

HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_LINE = "\033[2K"
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
            self.head = rng.randint(-TITLE_ROW, 0)
        else:
            # Only initial construction is spread vertically so the first
            # frame already identifies this as a full-height rain field.
            self.head = rng.randint(-TITLE_ROW, max(initial_scene_height - 1, 0))
        self.speed = rng.uniform(0.3, 1.2) * RAIN_SPEED
        trail_length = rng.randint(2, 5)
        self.bits = [rng.choice("01") for _ in range(trail_length + 1)]

    def advance(self, rng: random.Random, *, scene_height: int = HEADER_HEIGHT) -> None:
        """Advance one frame, resetting only after the complete trail has left."""
        self.head += self.speed
        if self.head - len(self.bits) >= scene_height:
            self.reset(rng)

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
    """Own the composed startup scene and its idle-time animation worker."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        frame_count: int = STARTUP_FRAME_COUNT,
        rng: random.Random | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        terminal_size: Callable[[], os.terminal_size] | None = None,
        ansi_supported: Callable[[TextIO], bool] | None = None,
        frame_interval: float = FRAME_INTERVAL,
        startup_info: StartupInfo | None = None,
    ) -> None:
        # With no explicit stream, resolve stdout per frame so prompt_toolkit's
        # output proxy can serialize worker writes with its input redraws.
        self.stream = stream
        self.frame_count = max(frame_count, 0)
        self.rng = rng if rng is not None else random.Random()
        self.sleeper = sleeper
        self.frame_interval = max(frame_interval, 0)
        self.startup_info = startup_info
        self.terminal_size = terminal_size or (
            lambda: shutil.get_terminal_size(fallback=(80, 24))
        )
        self.ansi_supported = ansi_supported or _enable_ansi
        self._condition = threading.Condition()
        self._render_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False
        self._paused = True
        self._stopping = False
        self._animation_available = False
        self._size: os.terminal_size | None = None
        self._anchor_valid = False
        self._draw_width_value = 0
        self._live_rows_below_header = DEFAULT_LIVE_ROWS_BELOW_HEADER
        self._live_prompt_height = 0
        self._live_separator_rows = DEFAULT_LIVE_ROWS_BELOW_HEADER
        # test addition
        self._live_cursor_column = 0
        self._drops: list[Drop] = []
        self._live_redraw: Callable[[str], None] | None = None
        self._redraw_requested = False
        self.startup_menu: StartupMenu | None = None

    def set_startup_info(self, startup_info: StartupInfo | None) -> None:
        """Set the application-owned values used by subsequent scene frames."""
        with self._condition:
            self.startup_info = startup_info

    def set_startup_menu(self, startup_menu: StartupMenu | None) -> None:
        """Attach application menu state read by the existing frame worker."""
        with self._condition:
            self.startup_menu = startup_menu

    def start(self) -> bool:
        """Render the first frame and create at most one paused animator."""
        with self._condition:
            if self._started:
                return self._animation_available
            self._started = True

            stream = self._output_stream()
            size = self.terminal_size()
            if not self._can_animate(size, stream):
                self._write_static(size.columns, stream)
                return False

            self._size = size
            layout = self._layout_for(size)
            self._draw_width_value = layout.width
            self._drops = create_drops(
                self._draw_width_value,
                self.rng,
                scene_height=layout.height,
            )
            self._animation_available = True
            self._stopping = False
            self._paused = True
            try:
                self._reserve_initial_viewport(layout, size, stream)
                rendered = self._render_next_frame(anchored=False)
            except (OSError, ValueError):
                self._animation_available = False
                return False
            if not rendered:
                self._animation_available = False
                return False
            self._anchor_valid = True
            self._thread = threading.Thread(
                target=self._animate,
                name="code-squid-binary-rain",
                daemon=True,
            )
            self._thread.start()
            return True

    def pause(self) -> None:
        """Pause live redraws and wait for an in-flight frame to finish."""
        with self._condition:
            self._paused = True
        # Output may begin as soon as this returns, so do not leave a worker
        # frame racing ordinary console rendering.
        with self._render_lock:
            pass
        with self._condition:
            self._live_redraw = None
            self._redraw_requested = False

    def resume(self, redraw: Callable[[str], None] | None = None) -> None:
        """Resume the existing animator without creating another worker."""
        with self._condition:
            if self._thread is None or self._stopping:
                return
            try:
                current_size = self.terminal_size()
            except (OSError, ValueError):
                self._invalidate_anchor_locked()
                return
            if (
                not self._anchor_valid
                or self._size is None
                or current_size != self._size
                or not self._live_size_is_suitable(current_size)
            ):
                self._invalidate_anchor_locked()
                return
            self._live_redraw = redraw
            self._paused = False
            self._condition.notify_all()

    def request_redraw(self) -> None:
        """Wake the one animator so changed menu state is painted promptly."""
        with self._condition:
            if self._thread is None or self._paused or self._stopping:
                return
            self._redraw_requested = True
            self._condition.notify_all()

    def reanchor(self) -> bool:
        """Render preserved state at the current cursor for the next prompt."""
        self.pause()
        with self._condition:
            if self._thread is None or self._stopping:
                return False
            # This prompt boundary supersedes the previous cursor origin even
            # when probing or rendering the replacement anchor later fails.
            self._anchor_valid = False
            try:
                current_size = self.terminal_size()
            except (OSError, ValueError):
                return False
            if not self._live_size_is_suitable(current_size):
                return False
        with self._render_lock:
            try:
                rendered = self._render_next_frame(anchored=False)
            except (OSError, ValueError):
                return False
        if not rendered:
            return False
        with self._condition:
            self._anchor_valid = True
        return True

    def set_live_content_below_header(self, content: str, *, extra_rows: int) -> None:
        """Record the physical rows between the header and input layout."""
        columns = max(self.terminal_size().columns, 1)
        content_rows = sum(
            max(math.ceil(len(ANSI_ESCAPE_PATTERN.sub("", line)) / columns), 1)
            for line in content.splitlines()
        )
        with self._condition:
            self._live_rows_below_header = content_rows + max(extra_rows, 0)
            self._live_prompt_height = 0
            self._live_separator_rows = self._live_rows_below_header

    def set_live_prompt_geometry(
        self,
        *,
        prompt_height: int,
        cursor_row: int,
        cursor_column: int,
        separator_rows: int,
    ) -> None:
        """Record the active prompt's rendered height and cursor anchor.

        The frame writer starts at prompt_toolkit's current cursor, not at the
        composer bottom. Keep that cursor-relative offset separate from the
        total height used to decide whether the whole live layout still fits.
        """
        prompt_height = max(prompt_height, 1)
        cursor_row = min(max(cursor_row, 0), prompt_height - 1)
        cursor_column = max(cursor_column, 0)
        separator_rows = max(separator_rows, 0)
        with self._condition:
            self._live_rows_below_header = separator_rows + cursor_row
            self._live_prompt_height = prompt_height
            self._live_separator_rows = separator_rows
            self._live_cursor_column = cursor_column

    def stop(self) -> None:
        """Terminate the animator and restore a visible cursor."""
        with self._condition:
            thread = self._thread
            if thread is None and not self._started:
                return
            self._stopping = True
            self._paused = False
            self._condition.notify_all()
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        with self._condition:
            self._thread = None
            self._animation_available = False
            self._started = False
            self._anchor_valid = False
        if thread is not None:
            self._restore_cursor(self._output_stream())

    @property
    def has_animator(self) -> bool:
        """Return whether this header owns a live animation worker."""
        with self._condition:
            return self._thread is not None and not self._stopping

    @property
    def needs_reanchor(self) -> bool:
        """Return whether resize invalidated the live prompt anchor."""
        with self._condition:
            return self._thread is not None and not self._anchor_valid

    def _animate(self) -> None:
        """Advance frames only while prompt input has explicitly resumed us."""
        while True:
            with self._condition:
                while self._paused and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return
                # A request already pending at this boundary is satisfied by
                # the frame this iteration is about to compose.
                self._redraw_requested = False

            with self._render_lock:
                with self._condition:
                    if self._paused or self._stopping:
                        continue
                try:
                    self._render_next_frame(anchored=True)
                except (CancelledError, OSError, RuntimeError, ValueError):
                    # Decoration failure must never take down the prompt.
                    with self._condition:
                        self._invalidate_anchor_locked()

            with self._condition:
                if not self._paused and not self._stopping:
                    if not self._redraw_requested:
                        self._condition.wait(timeout=self.frame_interval)

    def _render_next_frame(self, *, anchored: bool) -> bool:
        current_size = self.terminal_size()
        if anchored and (
            not self._anchor_valid
            or self._size is None
            or current_size != self._size
            or not self._live_size_is_suitable(current_size)
        ):
            # Terminal reflow makes every relative cursor offset stale. Freeze
            # before writing and let the next clean prompt boundary re-anchor.
            with self._condition:
                self._invalidate_anchor_locked()
            return False
        if not self._size_is_suitable(current_size):
            return False
        layout = self._layout_for(current_size)
        previous_size = self._size
        if previous_size is None or current_size != previous_size:
            self._size = current_size
            self._draw_width_value = self._draw_width(current_size)
            if previous_size is None or current_size.columns != previous_size.columns:
                self._drops = create_drops(
                    self._draw_width_value,
                    self.rng,
                    scene_height=layout.height,
                )

        for drop in self._drops:
            drop.advance(self.rng, scene_height=layout.height)
        panel = self._panel_lines(layout)
        cells, bits = compose_cells(layout, self._drops, panel)
        frame = render_cells(cells, bits)
        if anchored:
            redraw = self._live_redraw
            if redraw is None:
                return self.write_live_frame(frame)
            else:
                redraw(frame)
        else:
            self._write_frame(frame, False, self._output_stream())
        return True

    def write_live_frame(self, frame: str) -> bool:
        """Redraw header-owned rows and restore prompt_toolkit's exact cursor."""
        try:
            current_size = self.terminal_size()
        except (OSError, ValueError):
            current_size = None

        with self._condition:
            if (
                current_size is None
                or not self._anchor_valid
                or self._size is None
                or current_size != self._size
                or not self._live_size_is_suitable(current_size)
            ):
                self._invalidate_anchor_locked()
                return False

            rows_below_header = self._live_rows_below_header
            scene_height = self._layout_for(current_size).height

            # prompt_toolkit owns the logical input cursor. The rain renderer
            # temporarily moves the physical terminal cursor to repaint the header,
            # so restore both axes before returning control to prompt_toolkit.
            cursor_column = min(
                self._live_cursor_column,
                max(current_size.columns - 1, 0),
            )

        stream = self._output_stream()
        rows_up = scene_height + rows_below_header
        rows_down = rows_below_header

        rows = frame.splitlines()
        body = "\r\n".join(f"{CLEAR_LINE}\r{row}" for row in rows)

        # CSI n B moves down relative rows. CSI n G restores an absolute terminal
        # column; ANSI columns are 1-based while prompt_toolkit cursor.x is 0-based.
        move_down = f"\033[{rows_down}B" if rows_down else ""
        restore_column = f"\033[{cursor_column + 1}G"

        stream.write(
            f"{HIDE_CURSOR}"
            f"\033[{rows_up}A"
            f"{body}\r\n"
            f"{move_down}"
            f"{restore_column}"
            f"{SHOW_CURSOR}"
        )
        stream.flush()
        return True

    def _invalidate_anchor_locked(self) -> None:
        """Freeze redraws after reflow; caller must hold ``_condition``."""
        self._anchor_valid = False
        self._paused = True
        self._live_redraw = None

    def show(self) -> bool:
        """Show the bounded header; return whether animation was available."""
        stream = self._output_stream()
        size = self.terminal_size()
        if self.frame_count == 0 or not self._can_animate(size, stream):
            self._write_static(size.columns, stream)
            return False

        draw_width = self._draw_width(size)
        layout = self._layout_for(size)
        drops = create_drops(
            draw_width,
            self.rng,
            scene_height=layout.height,
        )
        rendered_frames = 0
        cursor_hidden = False
        try:
            stream.write(HIDE_CURSOR)
            cursor_hidden = True
            stream.flush()

            for frame_index in range(self.frame_count):
                current_size = self.terminal_size()
                if not self._size_is_suitable(current_size):
                    break
                if current_size.columns != size.columns:
                    size = current_size
                    draw_width = self._draw_width(size)
                    layout = self._layout_for(size)
                    drops = create_drops(
                        draw_width,
                        self.rng,
                        scene_height=layout.height,
                    )

                layout = self._layout_for(current_size)
                for drop in drops:
                    drop.advance(self.rng, scene_height=layout.height)
                cells, bits = compose_cells(layout, drops, self._panel_lines(layout))
                self._write_frame(render_cells(cells, bits), rendered_frames > 0, stream)
                rendered_frames += 1
                if frame_index + 1 < self.frame_count:
                    self.sleeper(FRAME_INTERVAL)
        except KeyboardInterrupt:
            # Startup decoration should not turn Ctrl+C into a damaged terminal.
            return False
        except (OSError, ValueError):
            # Output and size probing are best-effort: this decoration must not
            # become the reason an otherwise viable console session cannot run.
            return False
        finally:
            if cursor_hidden:
                self._restore_cursor(stream)

        return rendered_frames > 0

    def _output_stream(self) -> TextIO:
        return self.stream if self.stream is not None else sys.stdout

    def _can_animate(self, size: os.terminal_size, stream: TextIO) -> bool:
        try:
            is_tty = stream.isatty()
        except (AttributeError, OSError):
            is_tty = False
        return is_tty and self._size_is_suitable(size) and self.ansi_supported(stream)

    def _size_is_suitable(self, size: os.terminal_size) -> bool:
        return (
            size.columns >= PANEL_MIN_WIDTH + 1
            and size.lines >= self._layout_for(size).height + 1
        )

    def _live_size_is_suitable(self, size: os.terminal_size) -> bool:
        """Return whether the current cursor can safely reach the header."""
        # write_live_frame restores prompt_toolkit's current cursor; it never
        # traverses the rows beneath that cursor. The complete visible composer
        # height remains useful layout state, but is not an anchored-move bound.
        return self._size_is_suitable(size) and (
            size.lines
            > self._layout_for(size).height + self._live_rows_below_header
        )

    @staticmethod
    def _draw_width(size: os.terminal_size) -> int:
        return terminal_draw_width(size)

    def _write_static(self, width: int, stream: TextIO) -> None:
        try:
            size = os.terminal_size((width, max(MIN_HEIGHT, 1)))
            layout = self._layout_for(size)
            cells, bits = compose_cells(layout, [], self._panel_lines(layout))
            stream.write(f"{render_cells(cells, bits, ansi=False)}\n")
            stream.flush()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _reserve_initial_viewport(
        layout: StartupSceneLayout,
        size: os.terminal_size,
        stream: TextIO,
    ) -> None:
        """Make a history-preserving draw region when the complete UI fits."""
        required_rows = initial_viewport_height(layout)
        if required_rows > size.lines:
            return
        # Advancing and returning the cursor first scrolls prior terminal
        # content into normal history when necessary. The scene can then be
        # painted forward without its own top being pushed out of the viewport.
        rows_to_reserve = required_rows - 1
        stream.write(
            ("\r\n" * rows_to_reserve)
            + f"\033[{rows_to_reserve}A\r"
        )

    def _write_frame(self, frame: str, redraw: bool, stream: TextIO) -> None:
        frame_height = len(frame.splitlines())
        prefix = f"\033[{frame_height}A" if redraw else ""
        # Clearing each owned row makes a width decrease safe without touching
        # output above the header or anything subsequently printed below it.
        rows = frame.splitlines()
        body = "\r\n".join(f"{CLEAR_LINE}\r{row}" for row in rows)
        stream.write(f"{prefix}{body}\r\n")
        stream.flush()

    def _restore_cursor(self, stream: TextIO) -> None:
        try:
            stream.write(SHOW_CURSOR)
            stream.flush()
        except (OSError, ValueError):
            # A closed output stream cannot be repaired, but it also must not
            # make this decorative component prevent application startup.
            pass

    def _layout_for(self, size: os.terminal_size) -> StartupSceneLayout:
        """Return geometry matching the current optional Skill row."""
        show_skill = (
            self.startup_menu is None
            and self.startup_info is not None
            and self.startup_info.skill_name is not None
            and self.startup_info.mod_name is None
        )
        return startup_scene_layout(size.columns, show_skill=show_skill)

    def _panel_lines(self, layout: StartupSceneLayout) -> list[str]:
        """Return panel text without giving the rain layer content ownership."""
        if self.startup_menu is not None:
            return self.startup_menu.panel_lines(layout)
        if self.startup_info is None:
            empty_info = StartupInfo(Path("."), "none", "none", "none")
            return startup_panel_lines(empty_info, layout)
        return startup_panel_lines(self.startup_info, layout)


def _enable_ansi(stream: TextIO) -> bool:
    """Return ANSI suitability, enabling virtual terminal output on Windows."""
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    if os.name != "nt":
        return True

    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = wintypes.HANDLE(msvcrt.get_osfhandle(stream.fileno()))
        mode = wintypes.DWORD()
        kernel32 = ctypes.windll.kernel32
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_virtual_terminal_processing = 0x0004
        return bool(
            kernel32.SetConsoleMode(
                handle,
                wintypes.DWORD(mode.value | enable_virtual_terminal_processing),
            )
        )
    except (AttributeError, ImportError, OSError, ValueError):
        return False

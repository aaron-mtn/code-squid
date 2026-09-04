"""Bounded binary-rain header rendering for the Code Squid console."""

from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
import os
import random
import shutil
import sys
import threading
import time
from typing import Callable, Sequence, TextIO


HEADER_HEIGHT = 9
TITLE = "c o d e   s q u i d"
TITLE_ROW = 5
MIN_WIDTH = len(TITLE) + 4
MIN_HEIGHT = HEADER_HEIGHT + 1

# This scales each drop's independently randomized movement per frame. Keeping
# it in one obvious place makes presentation tuning possible without a CLI API.
RAIN_SPEED = 0.7
FRAME_INTERVAL = 0.05
STARTUP_FRAME_COUNT = 24
DROP_DENSITY = 0.24
# Startup details, the separating blank line, and the prompt identity occupy
# seven rows between the header and prompt_toolkit's input layout. Live redraws
# return to that layout origin before prompt_toolkit repaints typed content.
LIVE_ROWS_BELOW_HEADER = 7

EMPTY = 0
TRAIL_BIT = 1
HEAD_BIT = 2
TITLE_TEXT = 3

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
    def create(cls, column: int, rng: random.Random) -> "Drop":
        """Create a staggered drop using the supplied random source."""
        drop = cls(column=column, head=0, speed=0, bits=[])
        drop.reset(rng)
        return drop

    def reset(self, rng: random.Random) -> None:
        """Move the drop above the header and give it a fresh trail and speed."""
        self.head = rng.randint(-TITLE_ROW, 0)
        self.speed = rng.uniform(0.3, 1.2) * RAIN_SPEED
        trail_length = rng.randint(2, 5)
        self.bits = [rng.choice("01") for _ in range(trail_length + 1)]

    def advance(self, rng: random.Random) -> None:
        """Advance one frame, resetting only after the complete trail has left."""
        self.head += self.speed
        if self.head - len(self.bits) >= HEADER_HEIGHT:
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
) -> list[Drop]:
    """Create a restrained random subset of independently moving columns."""
    return [Drop.create(column, rng) for column in range(width) if rng.random() < density]


def compose_cells(
    width: int,
    drops: Sequence[Drop],
) -> tuple[list[list[int]], list[list[str]]]:
    """Compose drops into semantic cells, with heads winning over trails."""
    cells = [[EMPTY for _ in range(width)] for _ in range(HEADER_HEIGHT)]
    bits = [[" " for _ in range(width)] for _ in range(HEADER_HEIGHT)]

    for drop in drops:
        if not 0 <= drop.column < width:
            continue
        for row in range(HEADER_HEIGHT):
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

    overlay_title(cells, bits, width)
    return cells, bits


def overlay_title(cells: list[list[int]], bits: list[list[str]], width: int) -> None:
    """Center and clip the fixed title over the rain grid."""
    start_column = (width - len(TITLE)) // 2
    for offset, character in enumerate(TITLE):
        column = start_column + offset
        if 0 <= column < width:
            cells[TITLE_ROW][column] = TITLE_TEXT
            bits[TITLE_ROW][column] = character


def render_cells(cells: Sequence[Sequence[int]], bits: Sequence[Sequence[str]]) -> str:
    """Render semantic cells with bright heads, dim trails, and a plain title."""
    lines: list[str] = []
    for row_cells, row_bits in zip(cells, bits):
        line: list[str] = []
        for cell, bit in zip(row_cells, row_bits):
            # Equality is intentional: callers may use equivalent semantic cell
            # values rather than the exact constant objects exported here.
            if cell == HEAD_BIT:
                line.append(f"{BRIGHT_STYLE}{bit}{RESET_STYLE}")
            elif cell == TRAIL_BIT:
                line.append(f"{DIM_STYLE}{bit}{RESET_STYLE}")
            elif cell == TITLE_TEXT:
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
    """Own the fixed header region and its single idle-time animation worker."""

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
    ) -> None:
        # With no explicit stream, resolve stdout per frame so prompt_toolkit's
        # output proxy can serialize worker writes with its input redraws.
        self.stream = stream
        self.frame_count = max(frame_count, 0)
        self.rng = rng if rng is not None else random.Random()
        self.sleeper = sleeper
        self.frame_interval = max(frame_interval, 0)
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
        self._draw_width_value = 0
        self._drops: list[Drop] = []
        self._live_redraw: Callable[[str], None] | None = None

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
            self._draw_width_value = self._draw_width(size)
            self._drops = create_drops(self._draw_width_value, self.rng)
            self._animation_available = True
            self._stopping = False
            self._paused = True
            try:
                self._render_next_frame(anchored=False)
            except (OSError, ValueError):
                self._animation_available = False
                return False
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

    def resume(self, redraw: Callable[[str], None] | None = None) -> None:
        """Resume the existing animator without creating another worker."""
        with self._condition:
            if self._thread is None or self._stopping:
                return
            self._live_redraw = redraw
            self._paused = False
            self._condition.notify_all()

    def reanchor(self) -> bool:
        """Render preserved state at the current cursor for the next prompt."""
        self.pause()
        with self._condition:
            if self._thread is None or self._stopping:
                return False
        with self._render_lock:
            try:
                self._render_next_frame(anchored=False)
            except (OSError, ValueError):
                return False
        return True

    def stop(self) -> None:
        """Terminate the animator and restore a visible cursor."""
        with self._condition:
            thread = self._thread
            if thread is None:
                return
            self._stopping = True
            self._paused = False
            self._condition.notify_all()
        if thread is not threading.current_thread():
            thread.join()
        with self._condition:
            self._thread = None
            self._animation_available = False
            self._started = False
        self._restore_cursor(self._output_stream())

    @property
    def has_animator(self) -> bool:
        """Return whether this header owns a live animation worker."""
        with self._condition:
            return self._thread is not None and not self._stopping

    def _animate(self) -> None:
        """Advance frames only while prompt input has explicitly resumed us."""
        while True:
            with self._condition:
                while self._paused and not self._stopping:
                    self._condition.wait()
                if self._stopping:
                    return

            with self._render_lock:
                with self._condition:
                    if self._paused or self._stopping:
                        continue
                try:
                    self._render_next_frame(anchored=True)
                except (CancelledError, OSError, RuntimeError, ValueError):
                    # Decoration failure must never take down the prompt.
                    with self._condition:
                        self._paused = True

            with self._condition:
                if not self._paused and not self._stopping:
                    self._condition.wait(timeout=self.frame_interval)

    def _render_next_frame(self, *, anchored: bool) -> None:
        current_size = self.terminal_size()
        if not self._size_is_suitable(current_size):
            return
        if self._size is None or current_size.columns != self._size.columns:
            self._size = current_size
            self._draw_width_value = self._draw_width(current_size)
            self._drops = create_drops(self._draw_width_value, self.rng)

        for drop in self._drops:
            drop.advance(self.rng)
        cells, bits = compose_cells(self._draw_width_value, self._drops)
        frame = render_cells(cells, bits)
        if anchored:
            redraw = self._live_redraw
            if redraw is None:
                self.write_live_frame(frame)
            else:
                redraw(frame)
        else:
            self._write_frame(frame, False, self._output_stream())

    def write_live_frame(self, frame: str) -> None:
        """Redraw above an erased prompt and return to its layout origin."""
        stream = self._output_stream()
        rows_up = HEADER_HEIGHT + LIVE_ROWS_BELOW_HEADER
        rows_down = rows_up - HEADER_HEIGHT
        rows = frame.splitlines()
        body = "\r\n".join(f"{CLEAR_LINE}\r{row}" for row in rows)
        stream.write(
            f"{HIDE_CURSOR}\033[{rows_up}A{body}\r\n"
            f"\033[{rows_down}B\r{SHOW_CURSOR}"
        )
        stream.flush()

    def show(self) -> bool:
        """Show the bounded header; return whether animation was available."""
        stream = self._output_stream()
        size = self.terminal_size()
        if self.frame_count == 0 or not self._can_animate(size, stream):
            self._write_static(size.columns, stream)
            return False

        draw_width = self._draw_width(size)
        drops = create_drops(draw_width, self.rng)
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
                    drops = create_drops(draw_width, self.rng)

                for drop in drops:
                    drop.advance(self.rng)
                cells, bits = compose_cells(draw_width, drops)
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

    @staticmethod
    def _size_is_suitable(size: os.terminal_size) -> bool:
        return size.columns >= MIN_WIDTH and size.lines >= MIN_HEIGHT

    @staticmethod
    def _draw_width(size: os.terminal_size) -> int:
        # Avoid the final physical column: writing there can trigger an eager
        # terminal wrap and break the invariant that exactly nine rows are ours.
        return size.columns - 1

    def _write_static(self, width: int, stream: TextIO) -> None:
        try:
            stream.write(f"{static_title(width)}\n")
            stream.flush()
        except (OSError, ValueError):
            pass

    def _write_frame(self, frame: str, redraw: bool, stream: TextIO) -> None:
        prefix = f"\033[{HEADER_HEIGHT}A" if redraw else ""
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

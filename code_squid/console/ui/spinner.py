"""Tiny terminal spinner used only for interactive display."""

from __future__ import annotations

import sys
import threading
import time
from typing import TextIO

SPINNER_FRAMES = (
    "\u00b7 Thinking...",
    "\u2022 Thinking...",
    "\u25cf Thinking...",
    "\u2022 Thinking...",
)
RESET_STYLE = "\033[0m"
THINKING_LABEL = "Thinking..."


class TerminalSpinner:
    """Animate one terminal line for the model's current active status."""

    def __init__(
        self,
        stream: TextIO | None = None,
        # thinking animation speed
        interval: float = 0.17,
        enabled: bool = True,
        prefix: str = "",
        style: str = "",
    ) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.interval = interval
        self.enabled = enabled
        self.prefix = prefix
        self.style = style
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active = False
        self._label = THINKING_LABEL

    def start(self, label: str = THINKING_LABEL) -> None:
        """Start the pulse, or update the label of the active pulse."""
        if not self._can_animate():
            return

        with self._lock:
            if self._active:
                if self._label != label:
                    self._label = label
                    # Labels have different widths, so clear the old text before
                    # repainting the same spinner-owned terminal line.
                    self.stream.write("\r\033[K")
                    self._write_frame(0)
                return

            self._active = True
            self._label = label
            self._stop_event.clear()
            self._write_frame(0)
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        thread: threading.Thread | None
        should_clear: bool

        with self._lock:
            should_clear = self._active and self._can_animate()
            if not self._active:
                return

            self._active = False
            self._stop_event.set()
            thread = self._thread
            self._thread = None

        if thread is not None:
            thread.join(timeout=self.interval * 2)

        if should_clear:
            self.stream.write("\r\033[K")
            self.stream.flush()

    def _run(self) -> None:
        frame_index = 1
        while not self._stop_event.wait(self.interval):
            with self._lock:
                if not self._active:
                    return
                self._write_frame(frame_index)
            frame_index = (frame_index + 1) % len(SPINNER_FRAMES)

    def _write_frame(self, frame_index: int) -> None:
        frame = SPINNER_FRAMES[frame_index]
        if self._label != THINKING_LABEL:
            # Keep the established pulse glyphs while changing only its status.
            pulse, _separator, _thinking_label = frame.partition(" ")
            frame = f"{pulse} {self._label}"
        if self.style and self.stream.isatty():
            # The pulse is one semantic status line. Reset immediately so its
            # active Mod accent cannot bleed into later terminal output.
            frame = f"{self.style}{frame}{RESET_STYLE}"
        text = f"{self.prefix}{frame}"
        self.stream.write(f"\r{text}")
        self.stream.flush()

    def _can_animate(self) -> bool:
        return self.enabled and self.stream.isatty()

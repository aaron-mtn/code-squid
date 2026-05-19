# ui/spinner.py

"""Tiny terminal spinner used only for interactive display."""

from __future__ import annotations

import sys
import threading
import time
from typing import TextIO


SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class TerminalSpinner:
    """Animates one terminal line while the model is thinking."""

    def __init__(
        self,
        stream: TextIO | None = None,
        interval: float = 0.08,
        enabled: bool = True,
    ) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.interval = interval
        self.enabled = enabled
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active = False

    def start(self) -> None:
        if not self._can_animate():
            return

        with self._lock:
            if self._active:
                return

            self._active = True
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
        self.stream.write(f"\r🦑 {SPINNER_FRAMES[frame_index]}")
        self.stream.flush()

    def _can_animate(self) -> bool:
        return self.enabled and self.stream.isatty()

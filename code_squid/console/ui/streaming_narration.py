"""Own the CLI's one temporary, in-place assistant narration region."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TextIO


_CURSOR_UP = "\033[{count}A"
_CLEAR_LINE = "\r\033[2K"


class StreamingNarration:
    """Render one provisional narration panel without managing terminal history."""

    def __init__(
        self,
        render_lines: Callable[[str], list[str]],
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
    ) -> None:
        self._render_lines = render_lines
        self._stream = stream if stream is not None else sys.stdout
        self._enabled = enabled
        self._active = False
        self._buffer = ""
        self._rendered_line_count = 0

    @property
    def active(self) -> bool:
        """Return whether Core has an open provisional assistant message."""
        return self._active

    @property
    def visible(self) -> bool:
        """Return whether this stream currently owns terminal rows."""
        return self._rendered_line_count > 0

    @property
    def can_render(self) -> bool:
        """Only rewrite terminals; redirected output receives settled text once."""
        return self._enabled and self._stream.isatty()

    def begin(self) -> None:
        """Open an empty provisional message without drawing a blank panel."""
        self.discard()
        self._active = True

    def append(self, delta: str) -> None:
        """Append a presentation-only chunk and repaint the owned rows."""
        if not self._active:
            self._active = True
        self._buffer += delta
        if self.can_render and self._buffer:
            self._replace_visible(self._render_lines(self._buffer))

    def commit(self, full_text: str) -> bool:
        """Replace provisional text and report whether a live panel was settled."""
        if not self._active:
            return False
        if not self.visible:
            self._reset()
            return False
        if full_text:
            self._replace_visible(self._render_lines(full_text))
        else:
            self._clear_visible()
        self._reset()
        return bool(full_text)

    def discard(self) -> None:
        """Erase provisional rows, if any, and release terminal ownership."""
        if self.visible:
            self._clear_visible()
        self._reset()

    def _replace_visible(self, lines: list[str]) -> None:
        if self.visible:
            self._clear_visible()
        self._stream.write("\n".join(lines) + "\n")
        self._stream.flush()
        self._rendered_line_count = len(lines)

    def _clear_visible(self) -> None:
        # Output rests below the panel. Clear exactly the rows owned here, then
        # return to the first one for replacement or subsequent normal output.
        count = self._rendered_line_count
        self._stream.write(_CURSOR_UP.format(count=count))
        for _ in range(count):
            self._stream.write(f"{_CLEAR_LINE}\033[1B")
        self._stream.write(_CURSOR_UP.format(count=count))
        self._stream.flush()
        self._rendered_line_count = 0

    def _reset(self) -> None:
        self._active = False
        self._buffer = ""
        self._rendered_line_count = 0

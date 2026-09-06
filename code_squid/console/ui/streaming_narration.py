"""Own the CLI's temporary prompt_toolkit-rendered narration region."""

from __future__ import annotations

import contextvars
import sys
import threading
from collections.abc import Callable
from typing import TextIO

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output.base import Output
from prompt_toolkit.output.defaults import create_output


RenderLines = Callable[[str, int], list[str]]


class _PromptToolkitLiveRegion:
    """Run one nonfullscreen Application until its content settles or clears.

    The private pipe keeps this presentation-only Application from consuming
    stdin. The real Output remains prompt_toolkit's source of viewport and
    cursor geometry, just as it is for the composer.
    """

    def __init__(
        self,
        render_lines: RenderLines,
        text: str,
        *,
        output: Output,
    ) -> None:
        self._render_lines = render_lines
        self._text = text
        self._text_lock = threading.Lock()
        self._started = threading.Event()
        self._rendered = threading.Event()
        self._failure: BaseException | None = None
        self._input_context = create_pipe_input()
        pipe_input = self._input_context.__enter__()

        control = FormattedTextControl(self._formatted_text)
        window = Window(
            control,
            wrap_lines=False,
            dont_extend_height=True,
            always_hide_cursor=True,
        )
        self.application: Application[None] = Application(
            layout=Layout(window),
            full_screen=False,
            erase_when_done=False,
            input=pipe_input,
            output=output,
        )
        self.application.after_render += self._after_render

        # Application.run() is blocking. This is the same narrow background
        # ownership pattern prompt_toolkit uses for its progress renderer.
        context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=context.run,
            args=(self._run,),
            name="code-squid-narration-renderer",
        )
        self._thread.start()
        self._wait_for(self._started, "start")
        self._wait_for(self._rendered, "initial render")

    def update(self, text: str) -> None:
        """Replace content and synchronously wait for one coherent redraw."""
        with self._text_lock:
            # Clearing under the same lock used by the content callback keeps
            # an asynchronous resize redraw from acknowledging stale text.
            self._rendered.clear()
            self._text = text
        self.application.invalidate()
        self._wait_for(self._rendered, "redraw")

    def close(self, *, erase: bool) -> None:
        """Stop the Application, either erasing or retaining its last frame."""
        self.application.erase_when_done = erase
        if self.application.is_running and self.application.loop is not None:
            self.application.loop.call_soon_threadsafe(self.application.exit)
        self._thread.join()
        self._input_context.__exit__(None, None, None)
        self._raise_failure()

    def _formatted_text(self) -> ANSI:
        with self._text_lock:
            text = self._text
        width = max(self.application.output.get_size().columns, 1)
        # Existing panel builders return ANSI-styled rows. ANSI translates them
        # to fragments; prompt_toolkit alone performs terminal cursor writes.
        return ANSI("\n".join(self._render_lines(text, width)))

    def _after_render(self, _application: Application[None]) -> None:
        self._rendered.set()

    def _run(self) -> None:
        try:
            self.application.run(pre_run=self._started.set)
        except BaseException as error:
            self._failure = error
            self._started.set()
            self._rendered.set()

    def _wait_for(self, event: threading.Event, operation: str) -> None:
        if not event.wait(timeout=5):
            raise RuntimeError(f"prompt_toolkit narration failed to {operation}")
        self._raise_failure()

    def _raise_failure(self) -> None:
        if self._failure is not None:
            raise RuntimeError("prompt_toolkit narration renderer failed") from self._failure


class StreamingNarration:
    """Render one provisional narration panel without managing terminal history."""

    def __init__(
        self,
        render_lines: RenderLines,
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
        output: Output | None = None,
    ) -> None:
        self._render_lines = render_lines
        self._stream = stream if stream is not None else sys.stdout
        self._enabled = enabled
        self._output = output
        self._active = False
        self._buffer = ""
        self._live_region: _PromptToolkitLiveRegion | None = None

    @property
    def active(self) -> bool:
        """Return whether Core has an open provisional assistant message."""
        return self._active

    @property
    def visible(self) -> bool:
        """Return whether prompt_toolkit currently owns terminal rows."""
        return self._live_region is not None

    @property
    def can_render(self) -> bool:
        """Only rewrite terminals; redirected output receives settled text once."""
        return self._enabled and self._stream.isatty()

    def begin(self) -> None:
        """Open an empty provisional message without drawing a blank panel."""
        self.discard()
        self._active = True

    def append(self, delta: str) -> None:
        """Append a presentation-only chunk and invalidate the live region."""
        if not self._active:
            self._active = True
        self._buffer += delta
        if not self.can_render or not self._buffer:
            return
        if self._live_region is None:
            output = self._output or create_output(stdout=self._stream)
            self._live_region = _PromptToolkitLiveRegion(
                self._render_lines,
                self._buffer,
                output=output,
            )
        else:
            self._live_region.update(self._buffer)

    def commit(self, full_text: str) -> bool:
        """Settle authoritative text and report whether a live panel was retained."""
        if not self._active:
            return False
        if self._live_region is None:
            self._reset()
            return False
        if full_text:
            if full_text != self._buffer:
                self._live_region.update(full_text)
            self._live_region.close(erase=False)
            settled = True
        else:
            self._live_region.close(erase=True)
            settled = False
        self._reset()
        return settled

    def discard(self) -> None:
        """Erase provisional content, if any, and release renderer ownership."""
        if self._live_region is not None:
            self._live_region.close(erase=True)
        self._reset()

    def _reset(self) -> None:
        self._active = False
        self._buffer = ""
        self._live_region = None

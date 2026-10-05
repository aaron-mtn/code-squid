"""Temporary alternate-buffer ownership for the startup renderer only."""

from contextlib import contextmanager

from prompt_toolkit.output import Output


class StartupOutput:
    """Delegate rendering while the startup boundary owns buffer switches."""

    def __init__(self, output) -> None:
        self._output = output

    def __getattr__(self, name):
        return getattr(self._output, name)

    def enter_alternate_screen(self) -> None:
        # Fullscreen renderer entry prepares only the already-selected canvas.
        # Its reset/cleanup must never restore primary before rendering stops.
        self._output.cursor_goto(0, 0)
        self._output.erase_screen()

    def quit_alternate_screen(self) -> None:
        # startup_terminal restores only after Application cleanup has finished.
        pass


# Output's ABC permits complete delegated implementations (Windows10_Output
# does the same); formatted printing and renderer geometry remain supported.
Output.register(StartupOutput)


@contextmanager
def startup_terminal(output):
    """Restore primary after renderer cleanup, including failed entry/flush."""
    try:
        output.enter_alternate_screen()
        output.flush()
        yield
    finally:
        try:
            # Native Windows changes its console handle on restore. Drain first,
            # but never let a failed drain skip the restoration attempt.
            output.flush()
        finally:
            try:
                output.quit_alternate_screen()
            finally:
                output.flush()

from code_squid.console.ui.spinner import RESET_STYLE, SPINNER_FRAMES, TerminalSpinner
from code_squid.console.ui.formatting import SOFT_CYAN_STYLE


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


def test_spinner_frames_are_tiny_braille_cycle() -> None:
    assert SPINNER_FRAMES == ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


def test_spinner_is_quiet_when_stdout_is_not_tty() -> None:
    stream = FakeStream(tty=False)
    spinner = TerminalSpinner(stream=stream)

    spinner.start()
    spinner.stop()

    assert stream.writes == []
    assert stream.flushes == 0


def test_spinner_writes_and_clears_one_tty_line() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, interval=10)

    spinner.start()
    spinner.stop()

    assert stream.writes == ["\r🦑 ⠋", "\r\033[K"]


def test_spinner_styles_tty_frame_and_resets() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, interval=10, style=SOFT_CYAN_STYLE)

    spinner.start()
    spinner.stop()

    assert stream.writes == [
        f"\r{SOFT_CYAN_STYLE}🦑{RESET_STYLE} ⠋",
        "\r\033[K",
    ]


def test_spinner_ignores_style_when_stdout_is_not_tty() -> None:
    stream = FakeStream(tty=False)
    spinner = TerminalSpinner(stream=stream, style=SOFT_CYAN_STYLE)

    spinner.start()
    spinner.stop()

    assert stream.writes == []
    assert stream.flushes == 0


def test_spinner_is_quiet_when_disabled() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, enabled=False, style=SOFT_CYAN_STYLE)

    spinner.start()
    spinner.stop()

    assert stream.writes == []
    assert stream.flushes == 0


def test_spinner_prefix_indents_frame_text() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, interval=10, prefix="  ")

    spinner.start()
    spinner.stop()

    assert stream.writes == ["\r  🦑 ⠋", "\r\033[K"]

from ui.spinner import SPINNER_FRAMES, TerminalSpinner


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

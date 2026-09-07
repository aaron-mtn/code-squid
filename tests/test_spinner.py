from wcwidth import wcswidth

from code_squid.console.ui.spinner import SPINNER_FRAMES, TerminalSpinner
from code_squid.console.ui.formatting import SQUID_GLYPH


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


def test_spinner_frames_are_stable_thinking_pulse() -> None:
    assert SPINNER_FRAMES == (
        "\u00b7 Thinking...",
        "\u2022 Thinking...",
        "\u25cf Thinking...",
        "\u2022 Thinking...",
    )
    assert all(SQUID_GLYPH not in frame for frame in SPINNER_FRAMES)
    assert [wcswidth(frame[0]) for frame in SPINNER_FRAMES] == [1, 1, 1, 1]


def test_thinking_pulse_keeps_committed_speed() -> None:
    assert TerminalSpinner().interval == 0.17


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

    assert stream.writes == ["\r\u00b7 Thinking...", "\r\033[K"]


def test_active_spinner_reuses_pulse_frames_with_requested_label() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, interval=10)

    spinner.start()
    spinner.start("Writing...")
    spinner.stop()

    assert stream.writes == [
        "\r\u00b7 Thinking...",
        "\r\033[K",
        "\r\u00b7 Writing...",
        "\r\033[K",
    ]


def test_default_thinking_frame_is_terminal_neutral() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, interval=10)

    spinner.start()
    spinner.stop()

    assert stream.writes == ["\r\u00b7 Thinking...", "\r\033[K"]
    assert "\033[" not in stream.writes[0]


def test_spinner_ignores_style_when_stdout_is_not_tty() -> None:
    stream = FakeStream(tty=False)
    spinner = TerminalSpinner(stream=stream, style="\033[31m")

    spinner.start()
    spinner.stop()

    assert stream.writes == []
    assert stream.flushes == 0


def test_spinner_is_quiet_when_disabled() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, enabled=False, style="\033[31m")

    spinner.start()
    spinner.stop()

    assert stream.writes == []
    assert stream.flushes == 0


def test_spinner_prefix_indents_frame_text() -> None:
    stream = FakeStream(tty=True)
    spinner = TerminalSpinner(stream=stream, interval=10, prefix="  ")

    spinner.start()
    spinner.stop()

    assert stream.writes == ["\r  \u00b7 Thinking...", "\r\033[K"]

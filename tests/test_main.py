import builtins
from pathlib import Path

from core.agent_loop import RunResult
from core.model_adapter import ModelRequestError
from main import _resume_session, _run_loop, _run_new_session
from storage.session_store import SessionStore
from ui.terminal import CODE_SQUID_BANNER, RUN_STARTED_DIVIDER


class ModelFailingLoop:
    def run(self) -> None:
        try:
            raise RuntimeError("provider unavailable")
        except RuntimeError as error:
            raise ModelRequestError("Model request failed") from error


class FakeDisplay:
    def __init__(self) -> None:
        self.starts = 0
        self.run_starts = 0
        self.failure_path = None
        self.finished = False
        self.run_result = None

    def start(self) -> None:
        self.starts += 1

    def run_started(self) -> None:
        self.run_starts += 1

    def model_request_failed(self, log_path: Path) -> None:
        self.failure_path = log_path

    def loop_finished(self, session, run_result=None) -> None:
        self.finished = True
        self.run_result = run_result


class FakeSessionStore:
    def __init__(self) -> None:
        self.statuses = []

    def update_status(self, status: str) -> None:
        self.statuses.append(status)


def test_run_loop_handles_model_request_error_with_log_and_status(tmp_path) -> None:
    display = FakeDisplay()
    session_store = FakeSessionStore()

    status = _run_loop(
        tmp_path,
        ModelFailingLoop(),
        display,
        session=object(),
        session_store=session_store,
    )

    log_path = tmp_path / ".code-squid" / "logs" / "latest.log"
    log_text = log_path.read_text(encoding="utf-8")

    assert status == 1
    assert display.starts == 0
    assert display.failure_path == Path(".code-squid/logs/latest.log")
    assert display.finished is False
    assert session_store.statuses == ["failed"]
    assert "RuntimeError: provider unavailable" in log_text
    assert "core.model_adapter.ModelRequestError: Model request failed" in log_text


class BannerDisplay(FakeDisplay):
    def start(self) -> None:
        super().start()
        print(CODE_SQUID_BANNER)
        print()

    def run_started(self) -> None:
        super().run_started()
        print()
        print(RUN_STARTED_DIVIDER)
        print()


class NoopLoop:
    def run(self) -> RunResult:
        return RunResult(status="complete")


def _fake_input(response: str):
    def fake_input(prompt: str) -> str:
        print(prompt, end="")
        return response

    return fake_input


def test_new_session_prints_banner_before_task_prompt(monkeypatch, tmp_path, capsys) -> None:
    displays: list[BannerDisplay] = []

    def fake_display(debug: bool = False, show_transcript: bool = False) -> BannerDisplay:
        display = BannerDisplay()
        displays.append(display)
        return display

    def fake_build_loop(*args):
        assert args[-1] is displays[0]
        return NoopLoop()

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(builtins, "input", _fake_input("Do the thing"))
    monkeypatch.setattr("main._build_loop", fake_build_loop)
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert capsys.readouterr().out == (
        f"{CODE_SQUID_BANNER}\n\n"
        "Task: "
        f"\n{RUN_STARTED_DIVIDER}\n\n"
    )
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 1


def test_resume_session_prints_banner_before_follow_up_prompt(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    displays: list[BannerDisplay] = []

    def fake_display(debug: bool = False, show_transcript: bool = False) -> BannerDisplay:
        display = BannerDisplay()
        displays.append(display)
        return display

    def fake_build_loop(*args):
        assert args[-1] is displays[0]
        return NoopLoop()

    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._session_dir_for_resume", lambda repo_root, session_id: session_store.session_dir)
    monkeypatch.setattr(builtins, "input", _fake_input("Continue the thing"))
    monkeypatch.setattr("main._build_loop", fake_build_loop)
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert capsys.readouterr().out == (
        f"{CODE_SQUID_BANNER}\n\n"
        "Follow-up task: "
        f"\n{RUN_STARTED_DIVIDER}\n\n"
    )
    assert len(displays) == 1
    assert displays[0].starts == 1
    assert displays[0].run_starts == 1


def test_new_session_passes_trace_to_terminal_display(
    monkeypatch,
    tmp_path,
) -> None:
    display_kwargs = []

    def fake_display(**kwargs) -> BannerDisplay:
        display_kwargs.append(kwargs)
        return BannerDisplay()

    monkeypatch.setenv("CODE_SQUID_TRACE", "1")
    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(builtins, "input", _fake_input("Do the thing"))
    monkeypatch.setattr("main._build_loop", lambda *args: NoopLoop())
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert display_kwargs == [{"debug": True, "show_transcript": True}]


def test_new_session_trace_threads_effective_debug_to_provider(
    monkeypatch,
    tmp_path,
) -> None:
    provider_kwargs = []

    class CapturingDisplay(BannerDisplay):
        def __init__(self, debug: bool = False, show_transcript: bool = False) -> None:
            super().__init__()
            self.debug = debug
            self.show_transcript = show_transcript

    class CapturingProvider:
        def __init__(self, **kwargs) -> None:
            provider_kwargs.append(kwargs)

    monkeypatch.setenv("CODE_SQUID_TRACE", "1")
    monkeypatch.setattr("main.TerminalDisplay", CapturingDisplay)
    monkeypatch.setattr("main.OpenAICompatibleProvider", CapturingProvider)
    monkeypatch.setattr(builtins, "input", _fake_input("Do the thing"))
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert provider_kwargs[0]["debug"] is True


def test_new_session_passes_debug_without_trace_to_terminal_display(
    monkeypatch,
    tmp_path,
) -> None:
    display_kwargs = []

    def fake_display(**kwargs) -> BannerDisplay:
        display_kwargs.append(kwargs)
        return BannerDisplay()

    monkeypatch.setenv("CODE_SQUID_DEBUG", "1")
    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr(builtins, "input", _fake_input("Do the thing"))
    monkeypatch.setattr("main._build_loop", lambda *args: NoopLoop())
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _run_new_session(tmp_path) == 0

    assert display_kwargs == [{"debug": True, "show_transcript": False}]


def test_resume_session_passes_trace_to_terminal_display(
    monkeypatch,
    tmp_path,
) -> None:
    session_store = SessionStore.create(tmp_path, "original task")
    display_kwargs = []

    def fake_display(**kwargs) -> BannerDisplay:
        display_kwargs.append(kwargs)
        return BannerDisplay()

    monkeypatch.setenv("CODE_SQUID_TRACE", "1")
    monkeypatch.setattr("main.TerminalDisplay", fake_display)
    monkeypatch.setattr("main._session_dir_for_resume", lambda repo_root, session_id: session_store.session_dir)
    monkeypatch.setattr(builtins, "input", _fake_input("Continue the thing"))
    monkeypatch.setattr("main._build_loop", lambda *args: NoopLoop())
    monkeypatch.setattr("main._run_loop", lambda *args: 0)

    assert _resume_session(tmp_path, session_store.session_id) == 0

    assert display_kwargs == [{"debug": True, "show_transcript": True}]

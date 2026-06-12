from pathlib import Path

from core.agent_loop import RunResult
from core.runner import run_coding_task


class FakeDisplay:
    debug = False

    def __init__(self) -> None:
        self.run_starts = 0

    def run_started(self) -> None:
        self.run_starts += 1


def test_run_coding_task_passes_callbacks_to_agent_loop(monkeypatch, tmp_path) -> None:
    callbacks = []

    class FakeAgentLoop:
        def __init__(
            self,
            *args,
            on_event=None,
            should_cancel=None,
            **kwargs,
        ) -> None:
            callbacks.append((on_event, should_cancel))
            self.display = kwargs["display"]

        def run(self) -> RunResult:
            return RunResult(status="complete")

    def on_event(event: dict) -> None:
        pass

    def should_cancel() -> bool:
        return False

    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("core.runner.AgentLoop", FakeAgentLoop)

    run_coding_task(
        repo_root=tmp_path,
        task="Do the thing",
        on_event=on_event,
        should_cancel=should_cancel,
        display=FakeDisplay(),
    )

    assert callbacks == [(on_event, should_cancel)]


def test_run_coding_task_returns_loop_run_result(monkeypatch, tmp_path: Path) -> None:
    expected = RunResult(status="failed", reason="fake failure")

    class FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            self.display = kwargs["display"]

        def run(self) -> RunResult:
            return expected

    display = FakeDisplay()
    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("core.runner.AgentLoop", FakeAgentLoop)

    result = run_coding_task(
        repo_root=tmp_path,
        task="Do the thing",
        display=display,
    )

    assert result is expected
    assert display.run_starts == 1

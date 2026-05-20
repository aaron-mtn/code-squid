from pathlib import Path

from core.model_adapter import ModelRequestError
from main import _run_loop


class ModelFailingLoop:
    def run(self) -> None:
        try:
            raise RuntimeError("provider unavailable")
        except RuntimeError as error:
            raise ModelRequestError("Model request failed") from error


class FakeDisplay:
    def __init__(self) -> None:
        self.started = False
        self.failure_path = None
        self.finished = False

    def start(self) -> None:
        self.started = True

    def model_request_failed(self, log_path: Path) -> None:
        self.failure_path = log_path

    def loop_finished(self, session) -> None:
        self.finished = True


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
    assert display.started is True
    assert display.failure_path == Path(".code-squid/logs/latest.log")
    assert display.finished is False
    assert session_store.statuses == ["failed"]
    assert "RuntimeError: provider unavailable" in log_text
    assert "core.model_adapter.ModelRequestError: Model request failed" in log_text

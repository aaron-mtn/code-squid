from pathlib import Path

from core.agent_loop import RunResult
from core.runner import build_coding_task_run, run_coding_task
from core.platform_context import PlatformContext


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


def test_run_construction_supplies_detected_platform_and_resolved_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    from core.runner import build_coding_task_run

    context = PlatformContext("Linux", "bash", "/bin/bash", "/", False)
    captured_agent = {}
    captured_executor = {}

    class FakeCodingAgent:
        def __init__(self, **kwargs) -> None:
            captured_agent.update(kwargs)

    class FakeToolExecutor:
        def __init__(self, **kwargs) -> None:
            captured_executor.update(kwargs)

    monkeypatch.setattr("core.runner.detect_platform_context", lambda: context)
    monkeypatch.setattr("core.runner.CodingAgent", FakeCodingAgent)
    monkeypatch.setattr("core.runner.ToolExecutor", FakeToolExecutor)
    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())

    build_coding_task_run(tmp_path / ".", "Do the thing", display=FakeDisplay())

    assert captured_agent["platform_context"] is context
    assert captured_agent["workspace"] == str(tmp_path.resolve())
    assert captured_executor["platform_context"] is context


def test_run_construction_uses_default_storage_factories(monkeypatch, tmp_path: Path) -> None:
    calls = []

    original_session_create = __import__(
        "storage.session_store", fromlist=["SessionStore"]
    ).SessionStore.create
    original_undo_create = __import__(
        "storage.undo_store", fromlist=["UndoStore"]
    ).UndoStore.create

    def create_session(*, repo_root, task):
        calls.append(("session", repo_root, task))
        return original_session_create(repo_root=repo_root, task=task)

    def create_undo(repo_root, session_id=None):
        calls.append(("undo", repo_root, session_id))
        return original_undo_create(repo_root, session_id=session_id)

    monkeypatch.setattr("core.runner.SessionStore.create", create_session)
    monkeypatch.setattr("core.runner.UndoStore.create", create_undo)
    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())

    run = build_coding_task_run(tmp_path, "Store defaults", display=FakeDisplay())

    assert calls == [
        ("session", tmp_path.resolve(), "Store defaults"),
        ("undo", tmp_path.resolve(), run.session_store.session_id),
    ]


def test_run_construction_uses_explicit_storage_factories(monkeypatch, tmp_path: Path) -> None:
    from storage.session_store import SessionStore
    from storage.undo_store import UndoStore

    custom_session = SessionStore.create(tmp_path / "persistence", "Custom session")
    custom_undo = UndoStore.create(tmp_path / "persistence", custom_session.session_id)
    calls = []
    captured_executor = {}
    tools = {"custom_tool": {"marker": object()}}
    skill = type(
        "FakeSkill",
        (),
        {"name": "custom", "prompt_sections": {}},
    )()

    class FakeToolExecutor:
        def __init__(self, **kwargs) -> None:
            captured_executor.update(kwargs)

    def session_factory(repo_root, task):
        calls.append(("session", repo_root, task))
        return custom_session

    def undo_factory(repo_root, session_id):
        calls.append(("undo", repo_root, session_id))
        return custom_undo

    monkeypatch.setattr("core.runner.ToolExecutor", FakeToolExecutor)
    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())

    run = build_coding_task_run(
        tmp_path / ".",
        "Use host storage",
        display=FakeDisplay(),
        resolved_skill=skill,
        resolved_tools=tools,
        session_store_factory=session_factory,
        undo_store_factory=undo_factory,
    )

    assert calls == [
        ("session", tmp_path.resolve(), "Use host storage"),
        ("undo", tmp_path.resolve(), custom_session.session_id),
    ]
    assert run.session_store is custom_session
    assert run.loop.session_store is custom_session
    assert captured_executor["undo_store"] is custom_undo
    assert captured_executor["tools"] is tools


def test_storage_factories_can_be_overridden_independently(monkeypatch, tmp_path: Path) -> None:
    from storage.session_store import SessionStore
    from storage.undo_store import UndoStore

    custom_session = SessionStore.create(tmp_path / "session-data", "Session only")
    custom_undo = UndoStore.create(tmp_path / "undo-data", "undo-only")
    default_undo_calls = []
    original_undo_create = UndoStore.create

    def create_default_undo(repo_root, session_id=None):
        default_undo_calls.append((repo_root, session_id))
        return original_undo_create(tmp_path / "default-undo", session_id)

    monkeypatch.setattr("core.runner.UndoStore.create", create_default_undo)
    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())

    session_run = build_coding_task_run(
        tmp_path,
        "Override session only",
        display=FakeDisplay(),
        session_store_factory=lambda repo_root, task: custom_session,
    )
    undo_run = build_coding_task_run(
        tmp_path,
        "Override undo only",
        display=FakeDisplay(),
        undo_store_factory=lambda repo_root, session_id: custom_undo,
    )

    assert session_run.session_store is custom_session
    assert default_undo_calls == [(tmp_path.resolve(), custom_session.session_id)]
    assert undo_run.loop.tool_executor.undo_store is custom_undo


def test_run_coding_task_forwards_storage_factories(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeLoop:
        display = FakeDisplay()

        def run(self):
            return RunResult(status="complete")

    def fake_build(**kwargs):
        captured.update(kwargs)
        return type("FakeRun", (), {"loop": FakeLoop()})()

    session_factory = lambda repo_root, task: None
    undo_factory = lambda repo_root, session_id: None
    monkeypatch.setattr("core.runner.build_coding_task_run", fake_build)

    run_coding_task(
        tmp_path,
        "Forward stores",
        session_store_factory=session_factory,
        undo_store_factory=undo_factory,
    )

    assert captured["session_store_factory"] is session_factory
    assert captured["undo_store_factory"] is undo_factory

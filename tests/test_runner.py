"""Tests for Code Squid coding-run construction and execution wiring."""

from pathlib import Path

import pytest

from code_squid.app_paths import session_indexes_path
from code_squid.compaction_context import CodeSquidCompactionContextProvider
from code_squid.settings import (
    CompactionSettings,
    DisplaySettings,
    ModelSettings,
    RuntimeSettings,
    Settings,
)
from squid_core.agent_loop import RunResult
from code_squid.agent_setup import build_coding_task_run, run_coding_task
from squid_core.platform_context import PlatformContext
from squid_core.providers.ollama import OllamaProvider
from squid_core.providers.openai_compatible import OpenAICompatibleProvider
from squid_core.spawner import NullDisplay


class FakeDisplay:
    debug = False

    def __init__(self) -> None:
        self.run_starts = 0

    def run_started(self) -> None:
        self.run_starts += 1


def _provider_settings(provider: str) -> Settings:
    """Return application settings suitable for provider construction tests."""

    is_ollama = provider == "ollama"
    return Settings(
        model=ModelSettings(
            provider=provider,
            name="test-model",
            base_url=(
                "http://127.0.0.1:11434"
                if is_ollama
                else "http://127.0.0.1:1234/v1"
            ),
            api_key=None if is_ollama else "test-key",
        ),
        display=DisplaySettings(),
        runtime=RuntimeSettings(),
        compaction=CompactionSettings(enabled=False),
    )


def test_coding_run_uses_native_ollama_provider_from_application_settings(
    tmp_path: Path,
) -> None:
    """Pin the complete Code Squid settings-to-ModelAdapter construction path."""

    run = build_coding_task_run(
        tmp_path,
        "Use the selected provider",
        settings=_provider_settings("ollama"),
    )

    assert isinstance(run.loop.model_adapter.provider, OllamaProvider)
    assert run.loop.model_adapter.provider_name == "ollama"


@pytest.mark.parametrize(
    "provider_name",
    ["lm_studio", "openrouter", "squid_models", "openai_compatible"],
)
def test_coding_run_preserves_openai_compatible_provider_identity(
    tmp_path: Path,
    provider_name: str,
) -> None:
    """Keep each OpenAI-compatible identity intact through actual run wiring."""

    run = build_coding_task_run(
        tmp_path,
        "Use the selected provider",
        settings=_provider_settings(provider_name),
    )

    provider = run.loop.model_adapter.provider
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.provider_name == provider_name
    assert run.loop.model_adapter.model_name == "test-model"
    assert run.loop.model_adapter.tool_call_content_mode == (
        "null" if provider_name == "openrouter" else "empty"
    )


def test_run_construction_uses_core_null_display_when_omitted(tmp_path: Path) -> None:
    run = build_coding_task_run(
        tmp_path,
        "Headless task",
        model_adapter=object(),
    )

    assert type(run.loop.display) is NullDisplay
    assert run.loop.approval_policy.prompter is None


def test_code_squid_installs_authoritative_compaction_context_provider(
    tmp_path: Path,
) -> None:
    run = build_coding_task_run(
        tmp_path,
        "Preserve runtime facts",
        model_adapter=object(),
    )

    assert isinstance(
        run.loop.compactor.context_provider,
        CodeSquidCompactionContextProvider,
    )


def test_run_construction_uses_supplied_display_for_approvals(tmp_path: Path) -> None:
    display = FakeDisplay()

    run = build_coding_task_run(
        tmp_path,
        "Presented task",
        display=display,
        model_adapter=object(),
    )

    assert run.loop.display is display
    assert run.loop.approval_policy.prompter is display


def test_run_construction_uses_persisted_trusted_commands(tmp_path: Path) -> None:
    settings = _provider_settings("lm_studio")
    settings = Settings(
        model=settings.model,
        display=settings.display,
        runtime=RuntimeSettings(
            approval_mode="guarded",
            trusted_commands=("git",),
        ),
        compaction=settings.compaction,
    )

    run = build_coding_task_run(
        tmp_path,
        "Use command trust",
        settings=settings,
        model_adapter=object(),
    )

    assert run.loop.approval_policy.check(
        {"tool": "run_command", "args": {"command": "git status"}}
    ).approved
    assert not run.loop.approval_policy.check(
        {"tool": "run_command", "args": {"command": "python script.py"}}
    ).approved


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

    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr("squid_core.spawner.AgentLoop", FakeAgentLoop)

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
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("squid_core.spawner.AgentLoop", FakeAgentLoop)

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
    from code_squid.agent_setup import build_coding_task_run

    context = PlatformContext("Linux", "bash", "/bin/bash", "/", False)
    captured_agent = {}
    captured_executor = {}

    class FakeCodingAgent:
        def __init__(self, **kwargs) -> None:
            captured_agent.update(kwargs)

    class FakeToolExecutor:
        def __init__(self, **kwargs) -> None:
            captured_executor.update(kwargs)

    monkeypatch.setattr("code_squid.agent_setup.detect_platform_context", lambda: context)
    monkeypatch.setattr("code_squid.agent_setup.Agent", FakeCodingAgent)
    monkeypatch.setattr("squid_core.spawner.ToolExecutor", FakeToolExecutor)
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())

    build_coding_task_run(tmp_path / ".", "Do the thing", display=FakeDisplay())

    assert captured_agent["platform_context"] is context
    assert captured_agent["workspace"] == str(tmp_path.resolve())
    assert captured_executor["platform_context"] is context


def test_run_construction_uses_default_storage_factories(monkeypatch, tmp_path: Path) -> None:
    calls = []

    original_session_create = __import__(
        "squid_core.storage.session_store", fromlist=["SessionStore"]
    ).SessionStore.create
    original_undo_create = __import__(
        "squid_core.storage.undo_store", fromlist=["UndoStore"]
    ).UndoStore.create

    def create_session(sessions_dir, task, *, workspace_root=None):
        calls.append(("session", sessions_dir, task, workspace_root))
        return original_session_create(
            sessions_dir,
            task,
            workspace_root=workspace_root,
        )

    def create_undo(undo_dir, session_id=None, *, workspace_root=None):
        calls.append(("undo", undo_dir, session_id, workspace_root))
        return original_undo_create(
            undo_dir,
            session_id=session_id,
            workspace_root=workspace_root,
        )

    monkeypatch.setattr("code_squid.agent_setup.SessionStore.create", create_session)
    monkeypatch.setattr("code_squid.agent_setup.UndoStore.create", create_undo)
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())

    run = build_coding_task_run(tmp_path, "Store defaults", display=FakeDisplay())

    assert calls == [
        (
            "session",
            tmp_path.resolve() / ".code-squid" / "sessions",
            "Store defaults",
            tmp_path.resolve(),
        ),
        (
            "undo",
            tmp_path.resolve() / ".code-squid" / "undo",
            run.session_store.session_id,
            tmp_path.resolve(),
        ),
    ]


def test_run_construction_explicitly_registers_new_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    registrations = []
    monkeypatch.setattr(
        "code_squid.agent_setup.register_session_root",
        lambda index_path, sessions_dir: registrations.append(
            (index_path, sessions_dir)
        ),
    )
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda *args, **kwargs: object(),
    )

    build_coding_task_run(tmp_path, "Register session", display=FakeDisplay())

    assert registrations == [
        (
            session_indexes_path(),
            tmp_path.resolve() / ".code-squid" / "sessions",
        )
    ]


def test_run_construction_uses_explicit_storage_factories(monkeypatch, tmp_path: Path) -> None:
    from squid_core.storage import SessionStore, UndoStore

    custom_session = SessionStore.create(tmp_path / "persistence", "Custom session")
    custom_undo = UndoStore.create(tmp_path / "undo-persistence", custom_session.session_id)
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

    monkeypatch.setattr("squid_core.spawner.ToolExecutor", FakeToolExecutor)
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())

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
    from squid_core.storage import SessionStore, UndoStore

    custom_session = SessionStore.create(tmp_path / "session-data", "Session only")
    custom_undo = UndoStore.create(tmp_path / "undo-data", "undo-only")
    default_undo_calls = []
    original_undo_create = UndoStore.create

    def create_default_undo(undo_dir, session_id=None, *, workspace_root=None):
        default_undo_calls.append((undo_dir, session_id, workspace_root))
        return original_undo_create(tmp_path / "default-undo", session_id)

    monkeypatch.setattr("code_squid.agent_setup.UndoStore.create", create_default_undo)
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())

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
    assert default_undo_calls == [
        (
            tmp_path.resolve() / ".code-squid" / "undo",
            custom_session.session_id,
            tmp_path.resolve(),
        )
    ]
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
    monkeypatch.setattr("code_squid.agent_setup.build_coding_task_run", fake_build)

    run_coding_task(
        tmp_path,
        "Forward stores",
        session_store_factory=session_factory,
        undo_store_factory=undo_factory,
    )

    assert captured["session_store_factory"] is session_factory
    assert captured["undo_store_factory"] is undo_factory


@pytest.mark.parametrize("with_adapter", [False, True])
def test_custom_model_collaborators_bypass_application_provider_construction(
    monkeypatch, tmp_path, with_adapter,
) -> None:
    def unexpected_construction(*args, **kwargs):
        pytest.fail("application default provider was constructed")
    monkeypatch.setattr("code_squid.provider_setup.build_provider", unexpected_construction)
    provider = object()
    adapter = object() if with_adapter else None
    run = build_coding_task_run(
        tmp_path, "Custom collaborators", settings=_provider_settings("openrouter"),
        provider=provider, model_adapter=adapter,
    )
    if with_adapter:
        assert run.loop.model_adapter is adapter
    else:
        assert run.loop.model_adapter.provider is provider
        assert run.loop.model_adapter.model_name == "test-model"
        assert run.loop.model_adapter.tool_call_content_mode == "null"

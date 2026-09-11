from dataclasses import replace
from pathlib import Path

import pytest

import squid_core.spawner as core_spawner
from code_squid.agent.prompts import CODE_SQUID_PROMPT_DEFAULTS
from squid_core.settings import (
    CompactionSettings,
    ProviderSettings,
    ReadFileSettings,
    RuntimeSettings,
)
from squid_core.session import Session
from squid_core.agent import Agent
from squid_core.storage import SessionStore, UndoStore


def _settings(*, provider: str = "openai_compatible") -> RuntimeSettings:
    return RuntimeSettings(
        provider=ProviderSettings(
            provider=provider,
            model_name="test-model",
            base_url="http://127.0.0.1:1234/v1",
            api_key="test-key",
        ),
        approval_mode="never",
        max_tool_steps=None,
        stream_assistant_text=False,
        compaction=CompactionSettings(
            enabled=False,
            trigger_input_tokens=25_000,
            compact_fraction=0.8,
            min_recent_chunks=2,
        ),
    )


def _storage_paths(tmp_path: Path) -> dict:
    return {
        "sessions_dir": tmp_path / "sessions",
        "undo_dir": tmp_path / "undo",
    }


def test_generic_module_has_no_coding_or_terminal_ui_dependency() -> None:
    source = Path(core_spawner.__file__).read_text(encoding="utf-8")

    assert "code_squid.agent.coding" not in source
    assert "code_squid.agent.prompts" not in source
    assert "code_squid.console.ui.display" not in source
    assert "TerminalDisplay" not in source
    assert "squid_core.mods" not in source


def test_generic_run_builds_default_agent_and_ui_neutral_display(tmp_path: Path) -> None:
    adapter = object()

    run = core_spawner.build_agent_run(
        tmp_path,
        "Generic task",
        settings=_settings(),
        model_adapter=adapter,
        **_storage_paths(tmp_path),
    )

    assert type(run.loop.agent) is Agent
    assert run.loop.agent.task == "Generic task"
    assert run.loop.agent.tools == {}
    assert run.loop.model_adapter is adapter
    assert type(run.loop.display) is core_spawner.NullDisplay


def test_generic_run_passes_read_file_sizing_to_default_executor(tmp_path: Path) -> None:
    read_file_settings = ReadFileSettings(
        default_max_lines=80,
        minimum_range_lines=20,
    )

    run = core_spawner.build_agent_run(
        tmp_path,
        "Sized reads",
        settings=replace(_settings(), read_file=read_file_settings),
        model_adapter=object(),
        **_storage_paths(tmp_path),
    )

    assert run.loop.tool_executor.read_file_settings is read_file_settings


def test_generic_run_requires_explicit_storage_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sessions_dir is required"):
        core_spawner.build_agent_run(
            tmp_path,
            "Generic task",
            settings=_settings(),
            model_adapter=object(),
        )


def test_code_squid_builder_supplies_application_prompt_defaults(
    monkeypatch, tmp_path: Path
) -> None:
    from code_squid.agent_setup import build_coding_task_run

    captured = {}

    class CapturingAgent:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("code_squid.agent_setup.Agent", CapturingAgent)

    build_coding_task_run(
        tmp_path,
        "Coding task",
        display=type("Display", (), {"debug": False})(),
        model_adapter=object(),
    )

    assert captured["prompt_defaults"] is CODE_SQUID_PROMPT_DEFAULTS


def test_supplied_provider_is_used_without_default_provider(
    monkeypatch, tmp_path: Path
) -> None:
    supplied_provider = object()
    monkeypatch.setattr(
        core_spawner,
        "build_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("default provider")),
    )

    run = core_spawner.build_agent_run(
        tmp_path,
        "Provider task",
        settings=_settings(),
        provider=supplied_provider,
        **_storage_paths(tmp_path),
    )

    assert run.loop.model_adapter.provider is supplied_provider


def test_supplied_model_adapter_bypasses_provider_and_adapter_construction(
    monkeypatch, tmp_path: Path
) -> None:
    adapter = object()
    monkeypatch.setattr(
        core_spawner,
        "build_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider built")),
    )
    monkeypatch.setattr(
        core_spawner,
        "ModelAdapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("adapter built")),
    )

    run = core_spawner.build_agent_run(
        tmp_path,
        "Adapter task",
        settings=_settings(),
        model_adapter=adapter,
        **_storage_paths(tmp_path),
    )

    assert run.loop.model_adapter is adapter


def test_supplied_runtime_collaborators_are_used_directly(tmp_path: Path) -> None:
    collaborators = {
        "agent": object(),
        "model_adapter": object(),
        "compactor": object(),
        "tool_executor": object(),
        "tool_results": object(),
        "approval_policy": object(),
        "action_preflight": object(),
        "hook_runner": object(),
        "display": object(),
    }

    run = core_spawner.build_agent_run(
        tmp_path,
        "Custom task",
        settings=_settings(),
        **_storage_paths(tmp_path),
        **collaborators,
    )

    for name, collaborator in collaborators.items():
        assert getattr(run.loop, name) is collaborator


def test_supplied_tool_executor_skips_default_undo_and_executor(
    monkeypatch, tmp_path: Path
) -> None:
    executor = object()
    monkeypatch.setattr(
        core_spawner.UndoStore,
        "create",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("undo built")),
    )
    monkeypatch.setattr(
        core_spawner,
        "ToolExecutor",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("executor built")),
    )

    run = core_spawner.build_agent_run(
        tmp_path,
        "Executor task",
        settings=_settings(),
        model_adapter=object(),
        tool_executor=executor,
        **_storage_paths(tmp_path),
    )

    assert run.loop.tool_executor is executor


def test_store_factories_preserve_order_and_session_id(tmp_path: Path) -> None:
    session_store = SessionStore.create(tmp_path / "session-host", "Stored task")
    undo_store = UndoStore.create(tmp_path / "undo-host", session_store.session_id)
    calls = []

    def session_factory(repo_root, task):
        calls.append(("session", repo_root, task))
        return session_store

    def undo_factory(repo_root, session_id):
        calls.append(("undo", repo_root, session_id))
        return undo_store

    run = core_spawner.build_agent_run(
        tmp_path,
        "Stored task",
        settings=_settings(),
        model_adapter=object(),
        session_store_factory=session_factory,
        undo_store_factory=undo_factory,
    )

    assert calls == [
        ("session", tmp_path.resolve(), "Stored task"),
        ("undo", tmp_path.resolve(), session_store.session_id),
    ]
    assert run.session_store is session_store
    assert run.loop.tool_executor.undo_store is undo_store


def test_precreated_session_and_stores_skip_default_construction(
    monkeypatch, tmp_path: Path
) -> None:
    session = Session(tmp_path)
    session_store = SessionStore.create(tmp_path / "session-host", "Existing")
    undo_store = UndoStore.create(tmp_path / "undo-host", session_store.session_id)

    monkeypatch.setattr(
        core_spawner.SessionStore,
        "create",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("session store built")),
    )
    monkeypatch.setattr(
        core_spawner.UndoStore,
        "create",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("undo store built")),
    )

    run = core_spawner.build_agent_run(
        tmp_path,
        "Existing",
        settings=_settings(),
        model_adapter=object(),
        session=session,
        session_store=session_store,
        undo_store=undo_store,
    )

    assert run.session is session
    assert run.session_store is session_store
    assert run.loop.session_store is session_store
    assert run.loop.tool_executor.undo_store is undo_store


def test_direct_agent_loop_construction_remains_available(tmp_path: Path) -> None:
    from squid_core.agent_loop import AgentLoop

    loop = AgentLoop(
        session=Session(tmp_path),
        model_adapter=object(),
        tool_executor=object(),
        tool_results=object(),
        agent=object(),
        display=core_spawner.NullDisplay(),
    )

    assert isinstance(loop, AgentLoop)

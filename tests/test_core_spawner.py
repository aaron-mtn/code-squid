import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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
from squid_core.tools import ToolResults


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


def _provider_response(content: str = "done") -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=[])
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=None)


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


def test_generic_run_passes_model_request_retry_settings(tmp_path: Path) -> None:
    settings = replace(
        _settings(),
        model_request_max_retries=4,
        model_request_retry_backoff_ms=75,
    )

    run = core_spawner.build_agent_run(
        tmp_path,
        "Retry settings",
        settings=settings,
        model_adapter=object(),
        **_storage_paths(tmp_path),
    )

    assert run.loop.model_request_max_retries == 4
    assert run.loop.model_request_retry_backoff_ms == 75


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


def test_runtime_wires_finalized_requests_to_session_model_view(tmp_path: Path) -> None:
    class Provider:
        reasoning_mode = "high"
        reasoning_token_budget = 321

        def __init__(self) -> None:
            self.requests = []

        def create_response(self, **request):
            self.requests.append(request)
            return _provider_response("summary")

    provider = Provider()
    settings = replace(
        _settings(),
        compaction=CompactionSettings(
            enabled=True,
            trigger_input_tokens=1,
            compact_fraction=0.8,
            min_recent_chunks=2,
        ),
    )
    run = core_spawner.build_agent_run(
        tmp_path,
        "Observed requests",
        settings=settings,
        provider=provider,
        **_storage_paths(tmp_path),
    )
    prepared = run.loop.model_adapter.prepare_request(
        [{"role": "user", "content": "ordinary request"}],
        [{"type": "function", "function": {"name": "inspect"}}],
    )

    run.loop.model_adapter.respond_prepared(prepared)
    run.session.messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "finding " * 80},
        {"role": "tool", "content": "result " * 80},
        {"role": "assistant", "content": "change " * 80},
        {"role": "user", "content": "continue " * 80},
    ]
    run.loop.compactor.maybe_compact(run.session)

    records = [
        json.loads(line)
        for line in run.session_store.model_view_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [record["request_index"] for record in records] == [1, 2]
    assert records[0]["messages"] == provider.requests[0]["messages"]
    assert records[0]["tools"] == provider.requests[0]["tools"]
    assert records[1]["messages"] == provider.requests[1]["messages"]
    assert records[1]["tools"] == []
    assert records[0]["reasoning_mode"] == "high"
    assert records[0]["reasoning_token_budget"] == 321


def test_model_view_records_textual_tool_observation_not_canonical_json(
    tmp_path: Path,
) -> None:
    class Provider:
        def create_response(self, **request):
            return _provider_response()

    run = core_spawner.build_agent_run(
        tmp_path,
        "Observe a read",
        settings=_settings(),
        provider=Provider(),
        **_storage_paths(tmp_path),
    )
    canonical_result = {
        "ok": True,
        "tool": "read_file",
        "path": str(tmp_path / "script.py"),
        "content": "first\nsecond\n",
        "start_line": 10,
        "end_line": 11,
        "returned_line_ranges": [{"start_line": 10, "end_line": 11}],
    }
    assistant = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "read-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
    }
    canonical_tool_message = ToolResults().message_from_action_result(
        {"tool_call_id": "read-1"}, canonical_result
    )
    run.session.messages = [assistant, canonical_tool_message]

    run.loop._respond([])

    record = json.loads(
        run.session_store.model_view_path.read_text(encoding="utf-8").splitlines()[-1]
    )
    model_tool_message = record["messages"][-1]
    assert model_tool_message["tool_call_id"] == "read-1"
    assert model_tool_message["content"].startswith("READ_FILE OK")
    assert (
        "<<< CODE SQUID SOURCE: script.py lines 10-11 >>>"
        in model_tool_message["content"]
    )
    assert '"content": "first' not in model_tool_message["content"]
    assert json.loads(canonical_tool_message["content"]) == canonical_result


def test_each_real_retry_attempt_gets_its_own_model_view_record(
    tmp_path: Path,
) -> None:
    class RetryProvider:
        def __init__(self) -> None:
            self.requests = []

        def create_response(self, **request):
            self.requests.append(request)
            if len(self.requests) == 1:
                raise TimeoutError("try again")
            return _provider_response()

    class FinishingAgent:
        def initial_messages(self):
            return [{"role": "system", "content": "system"}]

        def tool_definitions(self):
            return []

        def should_stop(self, session):
            return any(message.get("content") == "done" for message in session.messages)

        def validate_reply(self, _reply):
            return {"ok": True, "reason": ""}

    provider = RetryProvider()
    run = core_spawner.build_agent_run(
        tmp_path,
        "Retry capture",
        settings=replace(
            _settings(),
            model_request_max_retries=1,
            model_request_retry_backoff_ms=0,
        ),
        provider=provider,
        agent=FinishingAgent(),
        tool_executor=object(),
        tool_results=ToolResults(),
        **_storage_paths(tmp_path),
    )

    result = run.loop.run()

    records = [
        json.loads(line)
        for line in run.session_store.model_view_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert result.status == "complete"
    assert len(provider.requests) == 2
    assert [record["request_index"] for record in records] == [1, 2]
    assert records[0]["messages"] == records[1]["messages"]


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

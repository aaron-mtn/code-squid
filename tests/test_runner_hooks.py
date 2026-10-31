"""Verify Code Squid's application-owned Hook construction and wiring."""

import json
from pathlib import Path

import pytest

from code_squid.settings import (
    DEFAULT_BUILT_IN_HOOK_SETTINGS,
    CompactionSettings,
    DisplaySettings,
    ModelSettings,
    RuntimeSettings,
    Settings,
)
from squid_core.agent_loop import RunResult
from code_squid.app_paths import CODE_SQUID_HOME_ENV
from squid_core.tools.builtins.read_file import execute as execute_read_file
from squid_core.hooks import (
    BeforeRunContext,
    HookRunner,
    PromptContextBlock,
    HookResponse,
)
from code_squid.hooks import (
    RepeatedFailureNudge,
    PostVerificationNudge,
    TooManyReadsNudge,
)
from code_squid.agent_setup import (
    build_coding_task_run,
    build_hook_runner,
)


class FakeDisplay:
    debug = False

    def thinking(self) -> None:
        pass

    def debug_reply(self, reply: dict) -> None:
        pass

    def final_message(self, content: str) -> None:
        pass

    def assistant_message(self, content: str) -> None:
        pass

    def reply_rejected(self, reason: str) -> None:
        pass

    def action_started(self, action: dict) -> None:
        pass

    def tool_result(self, action: dict, result: dict) -> None:
        pass

    def step_limit_reached(self, max_tool_steps: int) -> None:
        pass


class FakeModelAdapter:
    instances = []

    def __init__(self, *args, **kwargs) -> None:
        self.calls = []
        FakeModelAdapter.instances.append(self)

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        self.calls.append(
            {
                "messages": list(messages),
                "tool_definitions": tool_definitions,
            }
        )
        return {
            "message": {"role": "assistant", "content": "TASK COMPLETE"},
            "actions": [],
            "format_error": "",
            "usage": None,
            "raw_reply": {
                "assistant": {"content": "TASK COMPLETE", "raw_tool_calls": []},
            },
        }

    def supports_streaming(self) -> bool:
        return False


class SequenceModelAdapter:
    """Return normalized replies while retaining each model-visible request."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = iter(replies)
        self.calls = []

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        self.calls.append(list(messages))
        return next(self.replies)

    def supports_streaming(self) -> bool:
        return False


class RuntimeAgent:
    """Small deterministic agent that exercises the real AgentLoop lifecycle."""

    task = "Inspect overlapping ranges"
    skill_name = None

    def initial_messages(self) -> list[dict]:
        return [{"role": "system", "content": "system"}]

    def tool_definitions(self) -> list[dict]:
        return [{"function": {"name": "read_file"}}]

    def should_stop(self, session) -> bool:
        return any(
            message.get("role") == "assistant"
            and message.get("content") == "TASK COMPLETE"
            for message in session.messages
        )

    def validate_reply(self, reply: dict) -> dict:
        return {"ok": True, "reason": ""}


class ReadFileExecutor:
    """Execute only the built-in read operation needed by this regression."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root

    def execute(self, action: dict) -> dict:
        return execute_read_file(self.workspace_root, **action["args"])


def _reply(content: str, action: dict | None = None) -> dict:
    actions = [] if action is None else [action]
    message = {"role": "assistant", "content": content}
    if action is not None:
        message["tool_calls"] = [
            {
                "id": action["tool_call_id"],
                "type": "function",
                "function": {
                    "name": action["tool"],
                    "arguments": json.dumps(action["args"]),
                },
            }
        ]
    return {
        "message": message,
        "actions": actions,
        "raw_reply": {"assistant": {"content": content}},
    }


class ManualContextHook:
    def __init__(self, marker: str = "MANUAL_MARKER") -> None:
        self.marker = marker

    def before_run(self, ctx: BeforeRunContext) -> HookResponse:
        return HookResponse(
            context_blocks=(
                PromptContextBlock("Manual Hook", self.marker, "manual"),
            )
        )


def _settings(
    built_in_hook_settings: dict[str, bool] | None = None,
) -> Settings:
    return Settings(
        model=ModelSettings(),
        display=DisplaySettings(debug=False),
        runtime=RuntimeSettings(
            built_in_hook_settings=(
                dict(DEFAULT_BUILT_IN_HOOK_SETTINGS)
                if built_in_hook_settings is None
                else built_in_hook_settings
            )
        ),
        compaction=CompactionSettings(enabled=False),
    )


def _install_runner_fakes(monkeypatch) -> None:
    FakeModelAdapter.instances = []
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("squid_core.spawner.ModelAdapter", FakeModelAdapter)


def _write_saved_hook(
    home: Path,
    *,
    enabled: bool = True,
    marker: str = "DISK_MARKER",
) -> None:
    hook_dir = home / "hooks" / "test-hook"
    hook_dir.mkdir(parents=True)
    (hook_dir / "hook.yaml").write_text(
        f"""name: test-hook
enabled: {str(enabled).lower()}
version: 1
""",
        encoding="utf-8",
    )
    (hook_dir / "hook.py").write_text(
        f"""
from squid_core.hooks import PromptContextBlock, HookResponse


class DiskContextHook:
    def before_run(self, ctx):
        return HookResponse(
            context_blocks=(
                PromptContextBlock("Disk Hook", {marker!r}, "user"),
            )
        )


def create_hook(config=None):
    return DiskContextHook()
""",
        encoding="utf-8",
    )


def _run_and_collect_model_messages(tmp_path: Path, **kwargs) -> list[dict]:
    run = build_coding_task_run(
        workspace_root=tmp_path,
        task="Do the thing",
        display=FakeDisplay(),
        settings=_settings(),
        **kwargs,
    )

    assert run.loop.run() == RunResult(status="complete")
    assert len(FakeModelAdapter.instances) == 1
    return FakeModelAdapter.instances[0].calls[0]["messages"]


def _message_text(messages: list[dict]) -> str:
    return "\n".join(str(message.get("content", "")) for message in messages)


def test_default_runner_behavior_does_not_load_user_hooks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_runner_fakes(monkeypatch)
    home = tmp_path / "code-squid-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_saved_hook(home, marker="DISK_DEFAULT_MARKER")

    messages = _run_and_collect_model_messages(
        tmp_path,
        include_user_hooks=False,
    )

    assert "DISK_DEFAULT_MARKER" not in _message_text(messages)


def test_code_squid_enables_configured_built_in_hooks_by_default() -> None:
    runner = build_hook_runner()

    assert [type(hook) for hook in runner.hooks] == [PostVerificationNudge]
    assert all(hook.source == "Code Squid" for hook in runner.hooks)


@pytest.mark.parametrize("enabled", [None, True, False])
def test_coding_task_read_guidance_is_opt_in(monkeypatch, tmp_path, enabled):
    """Default construction omits read guidance; a partial override enables it."""
    _install_runner_fakes(monkeypatch)
    settings = _settings({} if enabled is None else {"too_many_reads": enabled})
    run = build_coding_task_run(
        workspace_root=tmp_path,
        task="Inspect the workspace",
        display=FakeDisplay(),
        settings=settings,
    )

    expected = [PostVerificationNudge]
    if enabled:
        expected.insert(0, TooManyReadsNudge)
    assert [type(hook) for hook in run.loop.hook_runner.hooks] == expected


@pytest.mark.parametrize(
    ("hook_id", "hook_type"),
    [
        ("too_many_reads", TooManyReadsNudge),
        ("post_verification", PostVerificationNudge),
        ("repeated_failure", RepeatedFailureNudge),
    ],
)
def test_each_built_in_hook_can_be_enabled_independently(
    hook_id: str,
    hook_type: type,
) -> None:
    configured = dict.fromkeys(DEFAULT_BUILT_IN_HOOK_SETTINGS, False)
    configured[hook_id] = True
    runner = build_hook_runner(built_in_hook_settings=configured)

    assert [type(hook) for hook in runner.hooks] == [hook_type]


def test_all_built_in_hooks_can_be_disabled_together() -> None:
    runner = build_hook_runner(
        built_in_hook_settings=dict.fromkeys(DEFAULT_BUILT_IN_HOOK_SETTINGS, False)
    )

    assert runner.hooks == []


def test_external_hooks_remain_when_all_built_ins_are_disabled() -> None:
    # Disable only the application-created instances, even when a caller
    # deliberately supplies another Hook of the same application type.
    external_hook = TooManyReadsNudge(source="external")
    runner = build_hook_runner(
        hooks=[external_hook],
        built_in_hook_settings=dict.fromkeys(DEFAULT_BUILT_IN_HOOK_SETTINGS, False),
    )

    assert runner.hooks == [external_hook]


def test_user_hooks_remain_when_all_built_ins_are_disabled(tmp_path: Path) -> None:
    home = tmp_path / "code-squid-home"
    _write_saved_hook(home)

    runner = build_hook_runner(
        include_user_hooks=True,
        app_home=home,
        built_in_hook_settings=dict.fromkeys(DEFAULT_BUILT_IN_HOOK_SETTINGS, False),
    )

    assert [type(hook).__name__ for hook in runner.hooks] == ["DiskContextHook"]


def test_explicit_hook_runner_remains_when_all_built_ins_are_disabled() -> None:
    external_hook = ManualContextHook()
    runner = build_hook_runner(
        hook_runner=HookRunner([external_hook]),
        built_in_hook_settings=dict.fromkeys(DEFAULT_BUILT_IN_HOOK_SETTINGS, False),
    )

    assert runner.hooks == [external_hook]


def test_coding_task_settings_select_built_in_hooks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_runner_fakes(monkeypatch)
    settings = Settings(
        model=ModelSettings(),
        display=DisplaySettings(debug=False),
        runtime=RuntimeSettings(
            built_in_hook_settings={
                **DEFAULT_BUILT_IN_HOOK_SETTINGS,
                "too_many_reads": True,
                "post_verification": False,
                "repeated_failure": True,
            }
        ),
        compaction=CompactionSettings(enabled=False),
    )

    run = build_coding_task_run(
        workspace_root=tmp_path,
        task="Do the thing",
        display=FakeDisplay(),
        settings=settings,
    )

    assert [type(hook) for hook in run.loop.hook_runner.hooks] == [
        TooManyReadsNudge,
        RepeatedFailureNudge,
    ]


def test_include_user_hooks_loads_disk_hooks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_runner_fakes(monkeypatch)
    home = tmp_path / "code-squid-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_saved_hook(home, marker="DISK_ENABLED_MARKER")

    messages = _run_and_collect_model_messages(
        tmp_path,
        include_user_hooks=True,
    )

    assert "DISK_ENABLED_MARKER" in messages[-1]["content"]


def test_manual_hooks_still_work(monkeypatch, tmp_path: Path) -> None:
    _install_runner_fakes(monkeypatch)

    messages = _run_and_collect_model_messages(
        tmp_path,
        hooks=[ManualContextHook()],
    )

    assert "MANUAL_MARKER" in messages[-1]["content"]


def test_manual_hooks_and_loaded_hooks_combine(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_runner_fakes(monkeypatch)
    home = tmp_path / "code-squid-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_saved_hook(home, marker="DISK_COMBINED_MARKER")

    messages = _run_and_collect_model_messages(
        tmp_path,
        hooks=[ManualContextHook("MANUAL_COMBINED_MARKER")],
        include_user_hooks=True,
    )
    context = messages[-1]["content"]

    assert "MANUAL_COMBINED_MARKER" in context
    assert "DISK_COMBINED_MARKER" in context
    assert context.index("MANUAL_COMBINED_MARKER") < context.index(
        "DISK_COMBINED_MARKER"
    )








def test_disabled_saved_hook_is_not_run(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _install_runner_fakes(monkeypatch)
    home = tmp_path / "code-squid-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_saved_hook(home, enabled=False, marker="DISK_DISABLED_MARKER")

    messages = _run_and_collect_model_messages(
        tmp_path,
        include_user_hooks=True,
    )

    assert "DISK_DISABLED_MARKER" not in _message_text(messages)


@pytest.mark.parametrize("disabled_id", list(DEFAULT_BUILT_IN_HOOK_SETTINGS))
def test_persisted_hook_choices_apply_per_run_and_continuation(monkeypatch, tmp_path, disabled_id):
    from code_squid.settings import load_settings, write_built_in_hook_enabled
    _install_runner_fakes(monkeypatch)
    # Start with all enabled to prove each switch leaves every sibling active,
    # including the hook whose application default is disabled.
    for hook_id in DEFAULT_BUILT_IN_HOOK_SETTINGS:
        write_built_in_hook_enabled(tmp_path, hook_id, True)
    package_hook = ManualContextHook("PACKAGE_MARKER")
    def build(settings, **kwargs):
        return build_coding_task_run(workspace_root=tmp_path, task="Task", settings=settings,
                                     display=FakeDisplay(), hooks=[package_hook], **kwargs)
    first = build(load_settings(tmp_path))
    first_hooks = list(first.loop.hook_runner.hooks)
    write_built_in_hook_enabled(tmp_path, disabled_id, False)
    # Explicit settings snapshots remain authoritative, even on continuations.
    captured = load_settings(tmp_path)
    second = build(captured, session=first.session, session_store=first.session_store)
    types = {"too_many_reads": TooManyReadsNudge, "post_verification": PostVerificationNudge,
             "repeated_failure": RepeatedFailureNudge}
    assert [type(h) for h in second.loop.hook_runner.hooks] == [
        ManualContextHook, *(kind for name, kind in types.items() if name != disabled_id),
    ]
    assert second.loop.hook_runner.hooks[0] is package_hook
    assert first.loop.hook_runner.hooks == first_hooks
    assert len(first_hooks) == 4
    assert second.session is first.session
    third = build(captured)
    assert [type(h) for h in third.loop.hook_runner.hooks] == [type(h) for h in second.loop.hook_runner.hooks]
    write_built_in_hook_enabled(tmp_path, disabled_id, True)
    retained = build(captured, session=first.session, session_store=first.session_store)
    assert [type(h) for h in retained.loop.hook_runner.hooks] == [type(h) for h in second.loop.hook_runner.hooks]

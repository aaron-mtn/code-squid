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
    RepeatedFailureNudge,
    RepeatedReadNudge,
    PostVerificationNudge,
    TooManyReadsNudge,
    HookResponse,
)
from code_squid.agent_setup import (
    NO_PROGRESS_GUIDANCE,
    RUN_COMMAND_RECOVERY_GUIDANCE,
    RUN_COMMAND_TIMEOUT_RECOVERY_GUIDANCE,
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

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def execute(self, action: dict) -> dict:
        return execute_read_file(self.repo_root, **action["args"])


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


def _settings() -> Settings:
    return Settings(
        model=ModelSettings(),
        display=DisplaySettings(debug=False),
        runtime=RuntimeSettings(),
        compaction=CompactionSettings(enabled=False),
    )


def _install_runner_fakes(monkeypatch) -> None:
    FakeModelAdapter.instances = []
    monkeypatch.setattr("squid_core.spawner.build_provider", lambda *args, **kwargs: object())
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
        repo_root=tmp_path,
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


def test_code_squid_enables_all_built_in_hooks_by_default() -> None:
    runner = build_hook_runner()

    assert isinstance(runner.hooks[-4], RepeatedReadNudge)
    assert runner.hooks[-4].source == "Code Squid"
    assert isinstance(runner.hooks[-3], TooManyReadsNudge)
    assert runner.hooks[-3].source == "Code Squid"
    assert isinstance(runner.hooks[-2], PostVerificationNudge)
    assert runner.hooks[-2].source == "Code Squid"
    assert isinstance(runner.hooks[-1], RepeatedFailureNudge)
    assert runner.hooks[-1].guidance == NO_PROGRESS_GUIDANCE
    assert runner.hooks[-1].run_command_guidance == RUN_COMMAND_RECOVERY_GUIDANCE
    assert (
        runner.hooks[-1].run_command_timeout_guidance
        == RUN_COMMAND_TIMEOUT_RECOVERY_GUIDANCE
    )


@pytest.mark.parametrize(
    ("hook_id", "hook_type"),
    [
        ("repeated_read", RepeatedReadNudge),
        ("too_many_reads", TooManyReadsNudge),
        ("post_verification", PostVerificationNudge),
        ("repeated_failure", RepeatedFailureNudge),
    ],
)
def test_each_built_in_hook_can_be_disabled_independently(
    hook_id: str,
    hook_type: type,
) -> None:
    runner = build_hook_runner(built_in_hook_settings={hook_id: False})

    assert not any(isinstance(hook, hook_type) for hook in runner.hooks)
    assert len(runner.hooks) == len(DEFAULT_BUILT_IN_HOOK_SETTINGS) - 1


def test_all_built_in_hooks_can_be_disabled_together() -> None:
    runner = build_hook_runner(
        built_in_hook_settings=dict.fromkeys(DEFAULT_BUILT_IN_HOOK_SETTINGS, False)
    )

    assert runner.hooks == []


def test_external_hooks_remain_when_all_built_ins_are_disabled() -> None:
    # Disable only the application-created instances, even when a caller
    # deliberately supplies another Hook of the same Core type.
    external_hook = RepeatedReadNudge(source="external")
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
                "repeated_read": False,
                "post_verification": False,
            }
        ),
        compaction=CompactionSettings(enabled=False),
    )

    run = build_coding_task_run(
        repo_root=tmp_path,
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


def _run_overlapping_reads(tmp_path: Path, second_start: int):
    path = tmp_path / "deepseek_sample.py"
    path.write_text(
        "".join(f"line {line}\n" for line in range(1, 201)),
        encoding="utf-8",
    )
    actions = [
        {
            "tool": "read_file",
            "args": {
                "path": str(path),
                "ranges": [{"start_line": 1, "end_line": 100}],
            },
            "tool_call_id": "read-1",
        },
        {
            "tool": "read_file",
            "args": {
                "path": str(path),
                "ranges": [
                    {
                        "start_line": second_start,
                        # Keep the coverage-boundary fixture at the configured minimum
                        # so intentional small-range expansion is not involved.
                        "end_line": second_start + 149,
                    }
                ],
            },
            "tool_call_id": "read-2",
        },
    ]
    model = SequenceModelAdapter(
        [
            _reply("Read the first range.", actions[0]),
            _reply("Read an overlapping range.", actions[1]),
            _reply("TASK COMPLETE"),
        ]
    )
    run = build_coding_task_run(
        repo_root=tmp_path,
        task="Inspect overlapping ranges",
        display=FakeDisplay(),
        settings=_settings(),
        agent=RuntimeAgent(),
        model_adapter=model,
        tool_executor=ReadFileExecutor(tmp_path),
    )

    assert run.loop.run() == RunResult(status="complete")
    entries = [
        json.loads(line)
        for line in run.session_store.jsonl_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    return model, entries


def test_default_runtime_repeated_read_fires_and_is_logged(tmp_path: Path) -> None:
    model, entries = _run_overlapping_reads(tmp_path, second_start=46)

    configured = next(entry for entry in entries if entry["type"] == "hooks_configured")
    assert configured["hooks"][-4:] == [
        "RepeatedReadNudge",
        "TooManyReadsNudge",
        "PostVerificationNudge",
        "RepeatedFailureNudge",
    ]
    read_events = [
        entry
        for entry in entries
        if entry["type"] == "hook_execution"
        and entry["hook"] == "RepeatedReadNudge"
        and entry["seam"] == "tool_result"
    ]
    assert [event["status"] for event in read_events] == ["no_effect", "effect"]
    assert read_events[1]["effects"] == [
        "updated_tool_output",
        "additional_context",
    ]
    second_read_observation = next(
        message["content"]
        for message in reversed(model.calls[2])
        if message.get("role") == "tool"
    )
    assert second_read_observation.startswith("READ_FILE PARTIAL")
    assert "lines 46-150 already available unchanged" in second_read_observation
    assert "SOURCE: deepseek_sample.py lines 151-195" in second_read_observation
    assert "line 151\n" in second_read_observation
    assert "line 150\n" not in second_read_observation
    assert "If the next edit is already clear" in model.calls[2][-1]["content"]
    assert "hook_execution" not in str(model.calls)


def test_default_runtime_low_overlap_is_filtered_and_logged(tmp_path: Path) -> None:
    model, entries = _run_overlapping_reads(tmp_path, second_start=47)

    read_events = [
        entry
        for entry in entries
        if entry["type"] == "hook_execution"
        and entry["hook"] == "RepeatedReadNudge"
        and entry["seam"] == "tool_result"
    ]
    assert [event["status"] for event in read_events] == ["no_effect", "effect"]
    assert read_events[1]["produced_effect"] is True
    assert any(
        "READ_FILE PARTIAL" in str(message.get("content", ""))
        for message in model.calls[2]
    )
    assert any(
        "If the next edit is already clear" in str(message.get("content", ""))
        for message in model.calls[2]
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

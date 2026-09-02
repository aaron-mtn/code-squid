from pathlib import Path

from config.settings import (
    CompactionSettings,
    DisplaySettings,
    ModelSettings,
    RuntimeSettings,
    Settings,
)
from core.agent_loop import RunResult
from core.app_paths import CODE_SQUID_HOME_ENV
from core.hooks import BeforeRunContext, PromptContextBlock, RunHookDecision
from core.runner import build_coding_task_run


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


class ManualContextHook:
    def __init__(self, marker: str = "MANUAL_MARKER") -> None:
        self.marker = marker

    def before_run(self, ctx: BeforeRunContext) -> RunHookDecision:
        return RunHookDecision(
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
    monkeypatch.setattr("squid_core.runner.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("squid_core.runner.ModelAdapter", FakeModelAdapter)


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
from core.hooks import PromptContextBlock, RunHookDecision


class DiskContextHook:
    def before_run(self, ctx):
        return RunHookDecision(
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

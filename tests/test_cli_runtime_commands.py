"""Tests for interactive runtime, session, and workspace CLI commands."""

import json
from pathlib import Path

import pytest

from code_squid.app_paths import workspace_sessions_dir
from code_squid.console.cli.control_commands import handle_control_command
from code_squid.console.cli.prompt_loop import _resume_session, _run_interactive
from code_squid.console.cli.runtime_commands import handle_runtime_command
from code_squid.settings import load_settings
from squid_core.storage import SessionStore


@pytest.fixture(autouse=True)
def clean_runtime_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SQUID_PROVIDER", raising=False)
    monkeypatch.delenv("CODE_SQUID_MODEL", raising=False)


def _write_settings(repo_root: Path, settings: dict) -> Path:
    settings_path = repo_root / ".code-squid" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    return settings_path


def _prompt_sequence(responses: list[str]):
    pending = list(responses)

    def prompt(label: str) -> str:
        if not pending:
            raise AssertionError("No fake prompt responses left")
        return pending.pop(0)

    return prompt


class QuietDisplay:
    """Minimal display used to isolate command-loop behavior."""

    def start(self) -> None:
        pass


def test_provider_status_lists_effective_and_supported_values(tmp_path, capsys) -> None:
    handled, settings = handle_runtime_command(tmp_path, "/provider", load_settings(tmp_path))

    output = capsys.readouterr().out
    assert handled is True
    assert settings.model.provider == "openai_compatible"
    assert "Current provider: openai_compatible" in output
    assert "ollama" in output
    assert "openrouter" in output


def test_provider_selection_persists_and_preserves_unrelated_settings(tmp_path, capsys) -> None:
    settings_path = _write_settings(
        tmp_path,
        {"display": {"debug": True}, "model": {"name": "existing-model"}},
    )

    handled, settings = handle_runtime_command(
        tmp_path,
        "/provider ollama",
        load_settings(tmp_path),
    )

    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert handled is True
    assert settings.model.provider == "ollama"
    assert persisted["model"] == {"name": "existing-model", "provider": "ollama"}
    assert persisted["display"] == {"debug": True}
    assert "Provider set to: ollama" in capsys.readouterr().out


def test_invalid_provider_does_not_persist(tmp_path, capsys) -> None:
    handled, settings = handle_runtime_command(
        tmp_path,
        "/provider unknown",
        load_settings(tmp_path),
    )

    assert handled is True
    assert settings.model.provider == "openai_compatible"
    assert not (tmp_path / ".code-squid" / "settings.json").exists()
    assert "Invalid provider" in capsys.readouterr().out


def test_provider_environment_override_is_reported_but_saved(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("CODE_SQUID_PROVIDER", "openrouter")

    _, settings = handle_runtime_command(
        tmp_path,
        "/provider ollama",
        load_settings(tmp_path),
    )

    output = capsys.readouterr().out
    persisted = json.loads(
        (tmp_path / ".code-squid" / "settings.json").read_text(encoding="utf-8")
    )
    assert persisted["model"]["provider"] == "ollama"
    assert settings.model.provider == "openrouter"
    assert "Saved provider: ollama" in output
    assert "CODE_SQUID_PROVIDER overrides" in output


def test_model_status_and_selection_persist_without_losing_settings(tmp_path, capsys) -> None:
    settings_path = _write_settings(
        tmp_path,
        {"runtime": {"max_tool_steps": 4}, "model": {"provider": "ollama"}},
    )

    handle_runtime_command(tmp_path, "/model", load_settings(tmp_path))
    _, settings = handle_runtime_command(
        tmp_path,
        "/model local-model:latest",
        load_settings(tmp_path),
    )

    output = capsys.readouterr().out
    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Current model: qwen3.5-9b" in output
    assert settings.model.name == "local-model:latest"
    assert persisted["model"] == {
        "provider": "ollama",
        "name": "local-model:latest",
    }
    assert persisted["runtime"] == {"max_tool_steps": 4}


def test_model_environment_override_is_reported_but_saved(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CODE_SQUID_MODEL", "environment-model")

    _, settings = handle_runtime_command(
        tmp_path,
        "/model saved-model",
        load_settings(tmp_path),
    )

    output = capsys.readouterr().out
    assert settings.model.name == "environment-model"
    assert "Saved model: saved-model" in output
    assert "CODE_SQUID_MODEL overrides" in output


@pytest.mark.parametrize(
    ("friendly_mode", "approval_mode"),
    [("strict", "always"), ("balanced", "guarded"), ("yolo", "never")],
)
def test_safety_status_and_selection_mapping(
    tmp_path,
    capsys,
    friendly_mode,
    approval_mode,
) -> None:
    _write_settings(tmp_path, {"model": {"name": "preserved"}})
    handle_runtime_command(tmp_path, "/safety", load_settings(tmp_path))

    _, settings = handle_runtime_command(
        tmp_path,
        f"/safety {friendly_mode}",
        load_settings(tmp_path),
    )

    persisted = json.loads(
        (tmp_path / ".code-squid" / "settings.json").read_text(encoding="utf-8")
    )
    assert "Current safety mode:" in capsys.readouterr().out
    assert settings.runtime.approval_mode == approval_mode
    assert persisted["runtime"]["approval_mode"] == approval_mode
    assert persisted["model"] == {"name": "preserved"}


def test_runtime_changes_are_used_by_subsequent_runs_without_restart(
    tmp_path,
    monkeypatch,
) -> None:
    run_settings = []

    def fake_new(repo_root, task, settings, display, skill_name=None, mod_name=None):
        run_settings.append(
            (settings.model.provider, settings.model.name, settings.runtime.approval_mode)
        )
        return 0, "active-session"

    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_display", lambda *args: QuietDisplay())
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _prompt_sequence(
            [
                "/provider ollama",
                "/model qwen-new",
                "/safety strict",
                "run this",
                "/exit",
            ]
        ),
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_new_session_task", fake_new)

    assert _run_interactive(tmp_path) == 0
    assert run_settings == [("ollama", "qwen-new", "always")]


def _saved_session(repo_root: Path, task: str) -> SessionStore:
    store = SessionStore.create(
        workspace_sessions_dir(repo_root),
        task,
        workspace_root=repo_root,
    )
    store.append_message({"role": "user", "content": task})
    return store


def test_sessions_and_show_current_latest_and_explicit(tmp_path, capsys) -> None:
    current = _saved_session(tmp_path, "current transcript")

    handle_control_command(tmp_path, "/sessions", current.session_id)
    handle_control_command(tmp_path, "/show", current.session_id)
    handle_control_command(tmp_path, "/show current", current.session_id)
    handle_control_command(tmp_path, "/show latest", current.session_id)
    handle_control_command(tmp_path, f"/show {current.session_id}", None)

    output = capsys.readouterr().out
    assert "Code Squid Sessions" in output
    assert output.count(f"Session: {current.session_id}") == 4
    assert output.count("current transcript") >= 4


def test_resume_latest_and_explicit_switch_the_active_session(tmp_path, capsys) -> None:
    saved = _saved_session(tmp_path, "saved task")

    handled, active = handle_control_command(tmp_path, "/resume latest", None)
    handled_explicit, active_explicit = handle_control_command(
        tmp_path,
        f"/resume {saved.session_id}",
        None,
    )

    assert handled is True
    assert handled_explicit is True
    assert active == saved.session_id
    assert active_explicit == saved.session_id
    assert capsys.readouterr().out.count(f"Active session: {saved.session_id}") == 2


def test_undo_delegates_and_cwd_is_report_only(tmp_path, monkeypatch, capsys) -> None:
    undo_calls = []
    monkeypatch.setattr(
        "code_squid.console.cli.control_commands.undo_latest_run",
        lambda repo_root: undo_calls.append(repo_root),
    )

    _, active_after_undo = handle_control_command(tmp_path, "/undo", "session-one")
    _, active_after_cwd = handle_control_command(tmp_path, "/cwd", active_after_undo)
    _, active_after_invalid_cwd = handle_control_command(
        tmp_path,
        "/cwd somewhere-else",
        active_after_cwd,
    )

    output = capsys.readouterr().out
    assert undo_calls == [tmp_path]
    assert active_after_invalid_cwd == "session-one"
    assert f"Current workspace: {tmp_path}" in output
    assert "Usage: /cwd" in output


def test_interactive_resume_keeps_normal_commands_and_multiple_follow_ups(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    saved = _saved_session(tmp_path, "saved task")
    follow_ups = []

    def fake_follow_up(
        repo_root,
        session_id,
        task,
        settings,
        display,
        skill_name=None,
        mod_name=None,
    ):
        follow_ups.append((session_id, task))
        return 0, session_id

    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_display", lambda *args: QuietDisplay())
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _prompt_sequence(["/resume latest", "first", "/cwd", "second", "/exit"]),
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_follow_up_task",
        fake_follow_up,
    )

    assert _run_interactive(tmp_path) == 0
    assert follow_ups == [(saved.session_id, "first"), (saved.session_id, "second")]
    assert f"Current workspace: {tmp_path}" in capsys.readouterr().out


def test_shell_resume_enters_the_same_multi_turn_interactive_loop(
    tmp_path,
    monkeypatch,
) -> None:
    saved = _saved_session(tmp_path, "saved task")
    follow_ups = []

    def fake_follow_up(
        repo_root,
        session_id,
        task,
        settings,
        display,
        skill_name=None,
        mod_name=None,
    ):
        follow_ups.append((session_id, task))
        return 0, session_id

    monkeypatch.setattr("code_squid.console.cli.prompt_loop._run_display", lambda *args: QuietDisplay())
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._prompt_task",
        _prompt_sequence(["first", "/sessions", "second", "/exit"]),
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_follow_up_task",
        fake_follow_up,
    )

    assert _resume_session(tmp_path, saved.session_id) == 0
    assert follow_ups == [(saved.session_id, "first"), (saved.session_id, "second")]

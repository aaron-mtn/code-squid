"""Tests for interactive runtime, session, and workspace CLI commands."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from code_squid.app_paths import (
    recent_workspaces_path,
    settings_path,
    workspace_sessions_dir,
)
from code_squid.console.cli.control_commands import (
    RECENT_SESSION_LIMIT,
    discover_recent_sessions,
    handle_control_command,
    handle_workspace_command,
)
from code_squid.console.cli.prompt_loop import (
    _resume_session,
    _run_interactive,
)
from code_squid.console.cli.runtime_commands import handle_runtime_command
from code_squid.console.startup_menu import MAIN_ROWS, StartupMenu
from code_squid.console.ui.startup_application import (
    STARTUP_SESSION_SELECTED,
    STARTUP_WORKSPACE_SELECTED,
)
from code_squid.settings import load_settings
from squid_core.storage import SessionStore


@pytest.fixture(autouse=True)
def clean_runtime_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODE_SQUID_PROVIDER", raising=False)
    monkeypatch.delenv("CODE_SQUID_MODEL", raising=False)


def _write_settings(repo_root: Path, settings: dict) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


def _prompt_sequence(responses: list[str]):
    pending = list(responses)

    def prompt(label: str, animator=None) -> str:
        if not pending:
            raise AssertionError("No fake prompt responses left")
        return pending.pop(0)

    return prompt


class QuietDisplay:
    """Minimal display used to isolate command-loop behavior."""

    header = None
    session_scene_active = False

    def __init__(self) -> None:
        self.loaded_sessions = []
        self.loaded_session_scene_states = []

    def start(self) -> None:
        self.start_session_scene()

    def start_session_scene(self) -> None:
        self.session_scene_active = True

    def retire_session_scene(self) -> None:
        self.session_scene_active = False

    def stop_header(self) -> None:
        pass

    def previous_session_loaded(self, title, age, message_count=None) -> None:
        self.loaded_sessions.append((title, age, message_count))
        self.loaded_session_scene_states.append(self.session_scene_active)


def test_workspace_command_shows_current_root_and_accepts_quoted_path(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "home"
    selected = tmp_path / "selected workspace"
    selected.mkdir()
    monkeypatch.setenv("CODE_SQUID_HOME", str(home))

    shown, no_target = handle_workspace_command(tmp_path, "/workspace")
    switched, target = handle_workspace_command(
        tmp_path, f'/workspace "{selected}"'
    )

    assert (shown, no_target) == (True, None)
    assert (switched, target) == (True, selected.resolve())
    assert f"Workspace: {tmp_path}" in capsys.readouterr().out
    persisted = json.loads(recent_workspaces_path().read_text(encoding="utf-8"))
    assert persisted[0] == str(selected.resolve())


def test_workspace_command_expands_home_and_rejects_missing_or_file_paths(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "user-home"
    workspace = home / "project"
    workspace.mkdir(parents=True)
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CODE_SQUID_HOME", str(tmp_path / "app-home"))

    _, expanded = handle_workspace_command(tmp_path, "/workspace ~/project")
    _, missing = handle_workspace_command(tmp_path, "/workspace ~/missing")
    _, file_target = handle_workspace_command(tmp_path, f"/workspace {file_path}")

    assert expanded == workspace.resolve()
    assert missing is None
    assert file_target is None
    assert capsys.readouterr().out.count("Workspace unchanged:") == 2


def test_provider_status_lists_effective_and_supported_values(tmp_path, capsys) -> None:
    handled, settings = handle_runtime_command(tmp_path, "/provider", load_settings(tmp_path))

    output = capsys.readouterr().out
    assert handled is True
    assert settings.model.provider == "lm_studio"
    assert "Provider: LM Studio" in output
    assert "Ollama" in output
    assert "OpenRouter" in output


def test_provider_selection_persists_and_preserves_unrelated_settings(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(
            is_ready=lambda: True,
            list_models=lambda: ["existing-model"],
        ),
    )
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
    assert "Provider set to: Ollama" in capsys.readouterr().out


def test_invalid_provider_does_not_persist(tmp_path, capsys) -> None:
    handled, settings = handle_runtime_command(
        tmp_path,
        "/provider unknown",
        load_settings(tmp_path),
    )

    assert handled is True
    assert settings.model.provider == "lm_studio"
    assert not (tmp_path / ".code-squid" / "settings.json").exists()
    assert not settings_path().exists()
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
    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert persisted["model"]["provider"] == "ollama"
    assert settings.model.provider == "openrouter"
    assert "Saved; CODE_SQUID_PROVIDER remains" in output


def test_provider_use_accepts_friendly_name_and_uses_shared_selection(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    selected = []

    def select(repo_root, provider):
        selected.append((repo_root, provider))
        return load_settings(tmp_path), "OpenRouter is not connected."

    monkeypatch.setattr(
        "code_squid.console.cli.runtime_commands.select_provider",
        select,
    )
    handle_runtime_command(tmp_path, "/provider use OpenRouter", load_settings(tmp_path))
    assert selected == [(tmp_path, "openrouter")]
    assert "not connected" in capsys.readouterr().out


def test_disconnected_lm_studio_can_be_selected_then_configured(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _write_settings(tmp_path, {"model": {"provider": "ollama"}})
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(is_ready=lambda: False),
    )

    _, selected = handle_runtime_command(
        tmp_path,
        "/provider use LM Studio",
        load_settings(tmp_path),
    )
    handle_runtime_command(tmp_path, "/provider status", selected)
    _, configured = handle_runtime_command(
        tmp_path,
        "/provider url http://localhost:4321/v1/",
        selected,
    )
    monkeypatch.setattr(
        "code_squid.console.cli.runtime_commands.provider_ready",
        lambda settings: settings.model.base_url == "http://localhost:4321/v1",
    )
    handle_runtime_command(tmp_path, "/provider status", configured)

    output = capsys.readouterr().out
    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert selected.model.provider == "lm_studio"
    assert selected.model.base_url == "http://127.0.0.1:1234/v1"
    assert configured.model.provider == "lm_studio"
    assert configured.model.base_url == "http://localhost:4321/v1"
    assert persisted["model"]["provider"] == "lm_studio"
    assert persisted["providers"]["lm_studio"]["base_url"] == (
        "http://localhost:4321/v1"
    )
    assert "LM Studio is not connected." in output
    assert "Provider set to: LM Studio" in output
    assert "Provider: LM Studio" in output
    assert "Readiness: not connected" in output
    assert "Readiness: ready" in output


def test_provider_key_is_persisted_but_never_echoed(tmp_path, capsys) -> None:
    secret = "never-print-this-secret"
    handle_runtime_command(
        tmp_path,
        f"/provider key {secret}",
        load_settings(tmp_path),
    )
    output = capsys.readouterr().out
    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert persisted["providers"]["lm_studio"]["api_key"] == secret
    assert secret not in output
    assert "API key saved" in output


def test_runtime_commands_write_only_application_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(is_ready=lambda: False),
    )

    commands = (
        "/provider url http://lan-host:4321/v1",
        "/provider key app-secret",
        "/model app-model",
        "/safety balanced",
    )
    current = load_settings(tmp_path)
    for command in commands:
        _, current = handle_runtime_command(tmp_path, command, current)

    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert persisted["providers"]["lm_studio"]["base_url"] == (
        "http://lan-host:4321/v1"
    )
    assert persisted["providers"]["lm_studio"]["api_key"] == "app-secret"
    assert persisted["model"]["name"] == "app-model"
    assert persisted["runtime"]["approval_mode"] == "guarded"
    assert not (tmp_path / ".code-squid" / "settings.json").exists()


@pytest.mark.parametrize(
    ("value", "expected_tokens", "expected_confirmation"),
    (
        ("30000", 30_000, "Compaction trigger set to 30k tokens."),
        ("30k", 30_000, "Compaction trigger set to 30k tokens."),
        ("28.5k", 28_500, "Compaction trigger set to 28.5k tokens."),
    ),
)
def test_compact_at_normalizes_persists_and_confirms(
    tmp_path,
    capsys,
    value,
    expected_tokens,
    expected_confirmation,
) -> None:
    settings_path = _write_settings(
        tmp_path,
        {
            "display": {"debug": True},
            "compaction": {
                "enabled": False,
                "compact_fraction": 0.7,
                "min_recent_chunks": 4,
            },
        },
    )

    handled, settings = handle_runtime_command(
        tmp_path,
        f"/compact-at {value}",
        load_settings(tmp_path),
    )

    persisted = json.loads(settings_path.read_text(encoding="utf-8"))
    assert handled is True
    assert settings.compaction.trigger_input_tokens == expected_tokens
    assert persisted["compaction"] == {
        "enabled": False,
        "compact_fraction": 0.7,
        "min_recent_chunks": 4,
        "trigger_input_tokens": expected_tokens,
    }
    assert persisted["display"] == {"debug": True}
    assert expected_confirmation in capsys.readouterr().out


@pytest.mark.parametrize(
    "command",
    ("/compact-at", "/compact-at banana", "/compact-at -5k", "/compact-at 0"),
)
def test_compact_at_rejects_missing_malformed_and_non_positive_values(
    tmp_path,
    capsys,
    command,
) -> None:
    current = load_settings(tmp_path)

    handled, settings = handle_runtime_command(tmp_path, command, current)

    assert handled is True
    assert (
        settings.compaction.trigger_input_tokens
        == current.compaction.trigger_input_tokens
    )
    assert not settings_path().exists()
    output = capsys.readouterr().out
    assert ("Usage: /compact-at" in output) == (command == "/compact-at")
    assert ("Invalid token count" in output) == (command != "/compact-at")


def test_provider_connections_survive_switching_and_mutate_only_the_active_provider(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(is_ready=lambda: False),
    )

    handle_runtime_command(
        tmp_path,
        "/provider url http://192.168.0.24:1234/v1",
        load_settings(tmp_path),
    )
    handle_runtime_command(
        tmp_path,
        "/provider key lm-secret",
        load_settings(tmp_path),
    )
    handle_runtime_command(
        tmp_path,
        "/provider use OpenRouter",
        load_settings(tmp_path),
    )
    handle_runtime_command(
        tmp_path,
        "/provider key router-secret",
        load_settings(tmp_path),
    )
    handle_runtime_command(
        tmp_path,
        "/provider url https://router.example/v1",
        load_settings(tmp_path),
    )
    handle_runtime_command(
        tmp_path,
        "/provider use Ollama",
        load_settings(tmp_path),
    )

    ollama = load_settings(tmp_path)
    assert ollama.model.base_url == "http://127.0.0.1:11434"
    assert ollama.model.api_key is None

    handle_runtime_command(
        tmp_path,
        "/provider use LM Studio",
        ollama,
    )
    lm_studio = load_settings(tmp_path)
    assert lm_studio.model.base_url == "http://192.168.0.24:1234/v1"
    assert lm_studio.model.api_key == "lm-secret"

    handle_runtime_command(
        tmp_path,
        "/provider use OpenRouter",
        lm_studio,
    )
    openrouter = load_settings(tmp_path)
    assert openrouter.model.base_url == "https://router.example/v1"
    assert openrouter.model.api_key == "router-secret"
    assert openrouter.model.api_key_env is None

    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert persisted["model"] == {
        "provider": "openrouter",
    }
    assert persisted["providers"] == {
        "lm_studio": {
            "base_url": "http://192.168.0.24:1234/v1",
            "api_key": "lm-secret",
            "api_key_env": None,
        },
        "openrouter": {
            "api_key": "router-secret",
            "api_key_env": None,
            "base_url": "https://router.example/v1",
        },
    }


def test_provider_url_and_status_report_safe_effective_configuration(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "code_squid.console.cli.runtime_commands.provider_ready",
        lambda _settings: True,
    )
    handle_runtime_command(
        tmp_path,
        "/provider url http://localhost:9000/v1/",
        load_settings(tmp_path),
    )
    handle_runtime_command(tmp_path, "/provider status", load_settings(tmp_path))
    output = capsys.readouterr().out
    assert "http://localhost:9000/v1" in output
    assert "Provider: LM Studio" in output
    assert "API key set: yes" in output
    assert "Readiness: ready" in output
    assert "Environment overrides: none" in output


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

    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert "Current safety mode:" in capsys.readouterr().out
    assert settings.runtime.approval_mode == approval_mode
    assert persisted["runtime"]["approval_mode"] == approval_mode
    assert persisted["model"] == {"name": "preserved"}


def test_runtime_changes_are_used_by_subsequent_runs_without_restart(
    tmp_path,
    monkeypatch,
) -> None:
    run_settings = []
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(
            is_ready=lambda: True,
            list_models=lambda: ["qwen3.5-9b"],
        ),
    )

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


def test_recent_session_discovery_reuses_workspace_index_and_caps_results(
    tmp_path,
    monkeypatch,
) -> None:
    sessions = [{"session_id": str(index)} for index in range(25)]
    seen = []

    def list_index(sessions_dir):
        seen.append(sessions_dir)
        return sessions

    monkeypatch.setattr(
        "code_squid.console.cli.control_commands.list_sessions",
        list_index,
    )

    assert discover_recent_sessions(tmp_path) == sessions[:RECENT_SESSION_LIMIT]
    assert seen == [workspace_sessions_dir(tmp_path)]


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


def test_startup_session_selection_notices_once_and_uses_existing_follow_up_runner(
    tmp_path,
    monkeypatch,
) -> None:
    saved = _saved_session(tmp_path, "original task")
    display = QuietDisplay()
    selected_menu = None
    follow_ups = []
    prompts = iter([STARTUP_SESSION_SELECTED, "continue it", "continue again", "/exit"])
    prompt_animators = []
    startup_released = False
    forced_handoffs = 0

    def set_startup_menu(menu):
        nonlocal selected_menu
        selected_menu = menu
        display.header = object()

    def prompt(_label, animator=None):
        prompt_animators.append(animator)
        task = next(prompts)
        if task is STARTUP_SESSION_SELECTED:
            selected_menu.focus_from_composer()
            selected_menu.selected_index = MAIN_ROWS.index("Session")
            selected_menu.activate()
            selected_menu.selected_index = 1
            assert selected_menu.activate() is True
        elif task == "continue it":
            # The notice must already be visible when the ordinary composer is
            # available, rather than after this task has been submitted.
            assert display.loaded_sessions
            assert startup_released is True
            assert forced_handoffs == 0
        return task

    def wait_for_startup_fade():
        nonlocal startup_released
        startup_released = True

    def finish_startup_fade():
        nonlocal forced_handoffs
        forced_handoffs += 1

    display.wait_for_startup_fade = wait_for_startup_fade
    display.finish_startup_fade = finish_startup_fade

    def follow_up(
        repo_root,
        session_id,
        task,
        settings,
        current_display,
        skill_name=None,
        mod_name=None,
    ):
        follow_ups.append((session_id, task))
        return 0, session_id

    display.set_startup_menu = set_startup_menu
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_display",
        lambda *args: display,
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", prompt)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_follow_up_task",
        follow_up,
    )

    assert _run_interactive(tmp_path) == 0
    assert follow_ups == [
        (saved.session_id, "continue it"),
        (saved.session_id, "continue again"),
    ]
    assert len(display.loaded_sessions) == 1
    assert display.loaded_sessions[0][0] == "original task"
    assert display.loaded_sessions[0][2] is None
    assert display.loaded_session_scene_states == [False]
    assert prompt_animators[0] is display.header
    assert prompt_animators[1:] == [None, None, None]
    assert forced_handoffs == 1


def test_workspace_handoff_preserves_app_settings_and_clears_session(
    tmp_path,
    monkeypatch,
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    _write_settings(
        new_root,
        {
            "model": {"provider": "lm_studio", "name": "app-model"},
            "providers": {
                "lm_studio": {"base_url": "http://lan-host:4321/v1"},
                "openrouter": {"api_key": "router-key", "api_key_env": None},
            },
            "runtime": {"approval_mode": "guarded"},
        },
    )
    displays = []
    menus = []
    prompts = iter([STARTUP_WORKSPACE_SELECTED, "/exit"])

    def build_display(repo_root, settings, skill_name=None):
        display = QuietDisplay()
        display.repo_root = repo_root
        display.settings = settings

        def set_startup_menu(menu):
            menus.append(menu)

        display.set_startup_menu = set_startup_menu
        displays.append(display)
        return display

    def prompt(_label, animator=None):
        result = next(prompts)
        if result is STARTUP_WORKSPACE_SELECTED:
            menu = menus[-1]
            menu.focus_from_composer()
            menu.selected_index = MAIN_ROWS.index("Workspace")
            menu.activate()
            menu._workspace_paths = (new_root.resolve(),)
            menu._options = (str(new_root.resolve()),)
            menu.selected_index = 0
            menu.activate()
        return result

    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_display",
        build_display,
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", prompt)

    assert _run_interactive(old_root, active_session_id="old-session") == 0
    assert [display.repo_root for display in displays] == [old_root, new_root.resolve()]
    rebuilt = displays[1].settings
    assert rebuilt.model.provider == "lm_studio"
    assert rebuilt.model.name == "app-model"
    assert rebuilt.model.base_url == "http://lan-host:4321/v1"
    assert rebuilt.providers["openrouter"] == {
        "api_key": "router-key",
        "api_key_env": None,
    }
    assert rebuilt.runtime.approval_mode == "guarded"
    assert menus[1].repo_root == new_root.resolve()
    assert menus[1].session_id is None
    assert menus[1].session_title is None


def test_workspace_command_rebuilds_state_and_routes_subsequent_runs_to_new_root(
    tmp_path,
    monkeypatch,
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new root"
    old_root.mkdir()
    new_root.mkdir()
    _write_settings(new_root, {"model": {"name": "new-workspace-model"}})
    saved = _saved_session(new_root, "new-root session")
    displays = []
    menus = []
    runs = []
    rebuilt_session_ids = []

    def build_display(repo_root, settings, skill_name=None):
        display = QuietDisplay()
        display.repo_root = repo_root
        display.settings = settings
        display.set_startup_menu = menus.append
        displays.append(display)
        return display

    def run_new(repo_root, task, settings, display, skill_name=None, mod_name=None):
        runs.append(("new", repo_root, task, settings.model.name))
        return 0, "new-session"

    def run_follow_up(
        repo_root,
        session_id,
        task,
        settings,
        display,
        skill_name=None,
        mod_name=None,
    ):
        runs.append(("follow-up", repo_root, task, settings.model.name))
        return 0, session_id

    responses = iter([f'/workspace "{new_root}"', "first", "second", "/exit"])

    def prompt(_label, animator=None):
        response = next(responses)
        if response == "first":
            # The replacement menu's discovery callback must be rooted in the
            # reconstructed workspace before any subsequent task is run.
            assert menus[-1].repo_root == new_root.resolve()
            rebuilt_session_ids.append(menus[-1].session_id)
            assert menus[-1].session_discovery(menus[-1].repo_root)[0][
                "session_id"
            ] == saved.session_id
        return response

    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_display", build_display
    )
    monkeypatch.setattr("code_squid.console.cli.prompt_loop._prompt_task", prompt)
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_new_session_task", run_new
    )
    monkeypatch.setattr(
        "code_squid.console.cli.prompt_loop._run_follow_up_task", run_follow_up
    )

    assert _run_interactive(old_root, active_session_id="old-session") == 0
    assert [display.repo_root for display in displays] == [old_root, new_root.resolve()]
    assert displays[1].settings.model.name == "new-workspace-model"
    assert rebuilt_session_ids == [None]
    assert runs == [
        ("new", new_root.resolve(), "first", "new-workspace-model"),
        ("follow-up", new_root.resolve(), "second", "new-workspace-model"),
    ]

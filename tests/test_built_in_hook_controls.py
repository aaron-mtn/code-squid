"""Regression coverage for global hook settings and CLI controls, without inference."""

import json

import pytest

from code_squid.app_paths import settings_path
from code_squid.built_in_hooks import built_in_hooks_payload
from code_squid.console.cli import runtime_commands
from code_squid.settings import (
    DEFAULT_BUILT_IN_HOOK_SETTINGS, load_settings, write_built_in_hook_enabled,
)


def test_defaults_and_individual_writes_preserve_peers(tmp_path):
    before = load_settings(tmp_path)
    rows = built_in_hooks_payload(before)["hooks"]
    assert {row["id"]: row["enabled"] for row in rows} == DEFAULT_BUILT_IN_HOOK_SETTINGS
    assert {row["id"]: row["default_enabled"] for row in rows} == DEFAULT_BUILT_IN_HOOK_SETTINGS
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"custom": [1], "runtime": {"max_tool_steps": 12}}))
    write_built_in_hook_enabled(tmp_path, "too_many_reads", False)
    write_built_in_hook_enabled(tmp_path, "repeated_failure", True)
    assert load_settings(tmp_path).runtime.built_in_hook_settings == {
        "too_many_reads": False, "post_verification": True, "repeated_failure": True,
    }
    raw = json.loads(path.read_text())
    assert raw["custom"] == [1]
    assert raw["runtime"]["max_tool_steps"] == 12
    assert set(raw["runtime"]["built_in_hook_settings"]) == {"too_many_reads", "repeated_failure"}
    assert before.runtime.built_in_hook_settings == DEFAULT_BUILT_IN_HOOK_SETTINGS


@pytest.mark.parametrize("hook_id,enabled", [("unknown", True), ([], True), ("too_many_reads", 0)])
def test_invalid_choice_does_not_write(tmp_path, hook_id, enabled):
    with pytest.raises(ValueError):
        write_built_in_hook_enabled(tmp_path, hook_id, enabled)
    assert not settings_path().exists()


@pytest.mark.parametrize("runtime", [[], {"built_in_hook_settings": None},
                                    {"built_in_hook_settings": {"post_verification": "false"}},
                                    {"built_in_hook_settings": {"unknown": True}}])
def test_malformed_settings_are_not_overwritten(tmp_path, runtime):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"runtime": runtime})
    path.write_text(original)
    with pytest.raises(ValueError):
        write_built_in_hook_enabled(tmp_path, "too_many_reads", False)
    assert path.read_text() == original


def test_atomic_write_failure_preserves_file(monkeypatch, tmp_path):
    from squid_core.storage import atomic_json
    write_built_in_hook_enabled(tmp_path, "repeated_failure", True)
    original = settings_path().read_bytes()
    def fail(*args):
        raise OSError("replace failed")
    monkeypatch.setattr(atomic_json.os, "replace", fail)
    with pytest.raises(OSError):
        write_built_in_hook_enabled(tmp_path, "too_many_reads", False)
    assert settings_path().read_bytes() == original


def test_cli_interactive_toggle_reload_and_defaults(monkeypatch, tmp_path, capsys):
    answers = iter(["invalid", "0", "1", "3", ""])
    monkeypatch.setattr(runtime_commands, "prompt_multiline_input", lambda *a: next(answers))
    handled, settings = runtime_commands.handle_runtime_command(tmp_path, "/hooks", load_settings(tmp_path))
    assert handled
    assert settings.runtime.built_in_hook_settings == {
        "too_many_reads": False, "post_verification": True, "repeated_failure": True,
    }
    output = capsys.readouterr().out
    assert "Read activity guidance: enabled (default: enabled)" in output
    assert "Read activity guidance: disabled (default: enabled)" in output
    assert "Repeated failure guidance: disabled (default: disabled)" in output
    assert "Repeated failure guidance: enabled (default: disabled)" in output
    assert settings == load_settings(tmp_path)


@pytest.mark.parametrize("error", [KeyboardInterrupt, EOFError])
def test_cli_cancel_preserves_saved_choices(monkeypatch, tmp_path, error):
    def cancel(*args):
        raise error()
    monkeypatch.setattr(runtime_commands, "prompt_multiline_input", cancel)
    write_built_in_hook_enabled(tmp_path, "post_verification", False)
    handled, settings = runtime_commands.handle_runtime_command(tmp_path, "/hooks", load_settings(tmp_path))
    assert handled
    assert settings.runtime.built_in_hook_settings["post_verification"] is False


def test_cli_write_error_retains_in_memory_settings(monkeypatch, tmp_path, capsys):
    before = load_settings(tmp_path)
    monkeypatch.setattr(runtime_commands, "prompt_multiline_input", lambda *a: "1")
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(runtime_commands, "write_built_in_hook_enabled", fail)
    assert runtime_commands.handle_runtime_command(tmp_path, "/hooks", before) == (True, before)
    assert "Settings change failed: disk full" in capsys.readouterr().out


def test_cli_later_write_failure_retains_earlier_saved_choice(monkeypatch, tmp_path):
    answers = iter(["1", "2"])
    monkeypatch.setattr(runtime_commands, "prompt_multiline_input", lambda *a: next(answers))
    def save(workspace, hook_id, enabled):
        if hook_id == "post_verification":
            raise OSError("disk full")
        write_built_in_hook_enabled(workspace, hook_id, enabled)
    monkeypatch.setattr(runtime_commands, "write_built_in_hook_enabled", save)
    _, settings = runtime_commands.handle_runtime_command(tmp_path, "/hooks", load_settings(tmp_path))
    assert settings.runtime.built_in_hook_settings["too_many_reads"] is False
    assert settings.runtime.built_in_hook_settings["post_verification"] is True
    assert settings == load_settings(tmp_path)

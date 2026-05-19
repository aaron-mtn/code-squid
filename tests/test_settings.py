import json
from pathlib import Path

import pytest

from config.settings import load_settings


ENV_VARS = [
    "CODE_SQUID_BASE_URL",
    "CODE_SQUID_API_KEY",
    "CODE_SQUID_MODEL",
    "CODE_SQUID_DEBUG",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_settings(repo_root: Path, settings: dict) -> None:
    settings_dir = repo_root / ".code-squid"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


def test_missing_settings_file_returns_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path)

    assert settings.model.base_url == "http://127.0.0.1:1234/v1"
    assert settings.model.api_key == "lm-studio"
    assert settings.model.api_key_env is None
    assert settings.model.name == "qwen3.5-9b"
    assert settings.display.debug is False
    assert settings.runtime.approval_mode == "never"
    assert settings.runtime.max_tool_steps is None


def test_settings_file_overrides_defaults(tmp_path: Path) -> None:
    write_settings(
        tmp_path,
        {
            "model": {
                "base_url": "http://localhost:9999/v1",
                "api_key": "local-key",
                "name": "local-model",
            },
            "display": {
                "debug": True,
            },
            "runtime": {
                "approval_mode": "always",
                "max_tool_steps": 3,
            },
        },
    )

    settings = load_settings(tmp_path)

    assert settings.model.base_url == "http://localhost:9999/v1"
    assert settings.model.api_key == "local-key"
    assert settings.model.api_key_env is None
    assert settings.model.name == "local-model"
    assert settings.display.debug is True
    assert settings.runtime.approval_mode == "always"
    assert settings.runtime.max_tool_steps == 3


def test_settings_file_allows_null_max_tool_steps(tmp_path: Path) -> None:
    write_settings(tmp_path, {"runtime": {"max_tool_steps": None}})

    settings = load_settings(tmp_path)

    assert settings.runtime.max_tool_steps is None


def test_env_vars_override_settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_settings(
        tmp_path,
        {
            "model": {
                "base_url": "http://localhost:9999/v1",
                "api_key": "local-key",
                "name": "local-model",
            },
        },
    )
    monkeypatch.setenv("CODE_SQUID_BASE_URL", "http://env-host:1234/v1")
    monkeypatch.setenv("CODE_SQUID_API_KEY", "env-key")
    monkeypatch.setenv("CODE_SQUID_MODEL", "env-model")

    settings = load_settings(tmp_path)

    assert settings.model.base_url == "http://env-host:1234/v1"
    assert settings.model.api_key == "env-key"
    assert settings.model.name == "env-model"


def test_debug_env_var_enables_debug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SQUID_DEBUG", "1")

    settings = load_settings(tmp_path)

    assert settings.display.debug is True


def test_debug_env_var_zero_disables_debug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_settings(tmp_path, {"display": {"debug": True}})
    monkeypatch.setenv("CODE_SQUID_DEBUG", "0")

    settings = load_settings(tmp_path)

    assert settings.display.debug is False


def test_invalid_approval_mode_raises(tmp_path: Path) -> None:
    write_settings(tmp_path, {"runtime": {"approval_mode": "sometimes"}})

    with pytest.raises(ValueError, match="runtime\\.approval_mode"):
        load_settings(tmp_path)


@pytest.mark.parametrize("max_tool_steps", [0, -1, True, False, "3"])
def test_invalid_max_tool_steps_raises(tmp_path: Path, max_tool_steps: object) -> None:
    write_settings(tmp_path, {"runtime": {"max_tool_steps": max_tool_steps}})

    with pytest.raises(ValueError, match="runtime\\.max_tool_steps"):
        load_settings(tmp_path)


def test_api_key_env_reads_named_environment_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(
        tmp_path,
        {
            "model": {
                "api_key": "local-key",
                "api_key_env": "MY_CODE_SQUID_KEY",
            },
        },
    )
    monkeypatch.setenv("MY_CODE_SQUID_KEY", "env-file-key")

    settings = load_settings(tmp_path)

    assert settings.model.api_key == "env-file-key"
    assert settings.model.api_key_env == "MY_CODE_SQUID_KEY"


def test_code_squid_api_key_overrides_api_key_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(
        tmp_path,
        {
            "model": {
                "api_key": "local-key",
                "api_key_env": "MY_CODE_SQUID_KEY",
            },
        },
    )
    monkeypatch.setenv("MY_CODE_SQUID_KEY", "env-file-key")
    monkeypatch.setenv("CODE_SQUID_API_KEY", "global-env-key")

    settings = load_settings(tmp_path)

    assert settings.model.api_key == "global-env-key"
    assert settings.model.api_key_env == "MY_CODE_SQUID_KEY"


def test_missing_api_key_env_variable_raises_clearly(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"api_key_env": "MISSING_CODE_SQUID_KEY"}})

    with pytest.raises(ValueError, match="MISSING_CODE_SQUID_KEY"):
        load_settings(tmp_path)


def test_invalid_json_produces_clear_failure(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".code-squid"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid settings JSON"):
        load_settings(tmp_path)

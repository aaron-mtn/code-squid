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
    assert settings.model.name == "qwen3.5-9b"
    assert settings.display.debug is False


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
        },
    )

    settings = load_settings(tmp_path)

    assert settings.model.base_url == "http://localhost:9999/v1"
    assert settings.model.api_key == "local-key"
    assert settings.model.name == "local-model"
    assert settings.display.debug is True


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


def test_invalid_json_produces_clear_failure(tmp_path: Path) -> None:
    settings_dir = tmp_path / ".code-squid"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid settings JSON"):
        load_settings(tmp_path)

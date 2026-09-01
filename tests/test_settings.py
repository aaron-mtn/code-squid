import json
from pathlib import Path

import pytest

from config.settings import load_settings, write_approval_mode


ENV_VARS = [
    "CODE_SQUID_BASE_URL",
    "CODE_SQUID_API_KEY",
    "CODE_SQUID_MODEL",
    "CODE_SQUID_PROVIDER",
    "CODE_SQUID_TEMPERATURE",
    "CODE_SQUID_DEBUG",
    "CODE_SQUID_STREAM_ASSISTANT_TEXT",
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
    assert settings.model.provider == "openai_compatible"
    assert settings.model.temperature is None
    assert settings.display.debug is False
    assert settings.runtime.approval_mode == "never"
    assert settings.runtime.max_tool_steps is None
    assert settings.runtime.stream_assistant_text is False
    assert settings.compaction.enabled is True
    assert settings.compaction.trigger_input_tokens == 48000
    assert settings.compaction.keep_recent_turns == 8


def test_settings_file_overrides_defaults(tmp_path: Path) -> None:
    write_settings(
        tmp_path,
        {
            "model": {
                "base_url": "http://localhost:9999/v1",
                "api_key": "local-key",
                "name": "local-model",
                "provider": "ollama",
                "temperature": 0.2,
            },
            "display": {
                "debug": True,
            },
            "runtime": {
                "approval_mode": "always",
                "max_tool_steps": 3,
                "stream_assistant_text": True,
            },
            "compaction": {
                "enabled": False,
                "trigger_input_tokens": 24000,
                "keep_recent_turns": 4,
            },
        },
    )

    settings = load_settings(tmp_path)

    assert settings.model.base_url == "http://localhost:9999/v1"
    assert settings.model.api_key == "local-key"
    assert settings.model.api_key_env is None
    assert settings.model.name == "local-model"
    assert settings.model.provider == "ollama"
    assert settings.model.temperature == 0.2
    assert settings.display.debug is True
    assert settings.runtime.approval_mode == "always"
    assert settings.runtime.max_tool_steps == 3
    assert settings.runtime.stream_assistant_text is True
    assert settings.compaction.enabled is False
    assert settings.compaction.trigger_input_tokens == 24000
    assert settings.compaction.keep_recent_turns == 4


def test_settings_file_can_set_zero_temperature(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"temperature": 0}})

    settings = load_settings(tmp_path)

    assert settings.model.temperature == 0


def test_settings_file_can_set_decimal_temperature(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"temperature": 0.2}})

    settings = load_settings(tmp_path)

    assert settings.model.temperature == 0.2


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
    monkeypatch.setenv("CODE_SQUID_PROVIDER", "ollama")
    monkeypatch.setenv("CODE_SQUID_TEMPERATURE", "0.4")

    settings = load_settings(tmp_path)

    assert settings.model.base_url == "http://env-host:1234/v1"
    assert settings.model.api_key == "env-key"
    assert settings.model.name == "env-model"
    assert settings.model.provider == "ollama"
    assert settings.model.temperature == 0.4


def test_code_squid_provider_openrouter_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODE_SQUID_PROVIDER", "openrouter")

    settings = load_settings(tmp_path)

    assert settings.model.provider == "openrouter"


def test_invalid_provider_settings_raise(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"provider": "not-a-provider"}})

    with pytest.raises(ValueError, match="model\\.provider"):
        load_settings(tmp_path)


def test_empty_temperature_env_var_unsets_temperature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(tmp_path, {"model": {"temperature": 0.2}})
    monkeypatch.setenv("CODE_SQUID_TEMPERATURE", "")

    settings = load_settings(tmp_path)

    assert settings.model.temperature is None


def test_null_temperature_preserves_none(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"temperature": None}})

    settings = load_settings(tmp_path)

    assert settings.model.temperature is None


def test_invalid_temperature_env_var_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODE_SQUID_TEMPERATURE", "warm")

    with pytest.raises(ValueError, match="CODE_SQUID_TEMPERATURE"):
        load_settings(tmp_path)


@pytest.mark.parametrize("temperature", [-0.1, 2.1, True, False])
def test_invalid_temperature_settings_raise(tmp_path: Path, temperature: object) -> None:
    write_settings(tmp_path, {"model": {"temperature": temperature}})

    with pytest.raises(ValueError, match="model\\.temperature"):
        load_settings(tmp_path)


def test_debug_env_var_enables_debug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_SQUID_DEBUG", "1")

    settings = load_settings(tmp_path)

    assert settings.display.debug is True


def test_debug_env_var_zero_disables_debug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_settings(tmp_path, {"display": {"debug": True}})
    monkeypatch.setenv("CODE_SQUID_DEBUG", "0")

    settings = load_settings(tmp_path)

    assert settings.display.debug is False


def test_stream_assistant_text_env_var_enables_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODE_SQUID_STREAM_ASSISTANT_TEXT", "1")

    settings = load_settings(tmp_path)

    assert settings.runtime.stream_assistant_text is True


def test_stream_assistant_text_env_var_zero_disables_streaming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(tmp_path, {"runtime": {"stream_assistant_text": True}})
    monkeypatch.setenv("CODE_SQUID_STREAM_ASSISTANT_TEXT", "0")

    settings = load_settings(tmp_path)

    assert settings.runtime.stream_assistant_text is False


def test_invalid_approval_mode_raises(tmp_path: Path) -> None:
    write_settings(tmp_path, {"runtime": {"approval_mode": "sometimes"}})

    with pytest.raises(ValueError, match="runtime\\.approval_mode"):
        load_settings(tmp_path)


@pytest.mark.parametrize("max_tool_steps", [0, -1, True, False, "3"])
def test_invalid_max_tool_steps_raises(tmp_path: Path, max_tool_steps: object) -> None:
    write_settings(tmp_path, {"runtime": {"max_tool_steps": max_tool_steps}})

    with pytest.raises(ValueError, match="runtime\\.max_tool_steps"):
        load_settings(tmp_path)


@pytest.mark.parametrize("stream_assistant_text", [None, 1, 0, "true"])
def test_invalid_stream_assistant_text_raises(
    tmp_path: Path,
    stream_assistant_text: object,
) -> None:
    write_settings(tmp_path, {"runtime": {"stream_assistant_text": stream_assistant_text}})

    with pytest.raises(ValueError, match="runtime\\.stream_assistant_text"):
        load_settings(tmp_path)


@pytest.mark.parametrize("enabled", [None, 1, 0, "true"])
def test_invalid_compaction_enabled_raises(tmp_path: Path, enabled: object) -> None:
    write_settings(tmp_path, {"compaction": {"enabled": enabled}})

    with pytest.raises(ValueError, match="compaction\\.enabled"):
        load_settings(tmp_path)


@pytest.mark.parametrize("trigger_input_tokens", [0, -1, True, False, "48000"])
def test_invalid_compaction_trigger_input_tokens_raises(
    tmp_path: Path,
    trigger_input_tokens: object,
) -> None:
    write_settings(tmp_path, {"compaction": {"trigger_input_tokens": trigger_input_tokens}})

    with pytest.raises(ValueError, match="compaction\\.trigger_input_tokens"):
        load_settings(tmp_path)


@pytest.mark.parametrize("keep_recent_turns", [0, -1, True, False, "8"])
def test_invalid_compaction_keep_recent_turns_raises(
    tmp_path: Path,
    keep_recent_turns: object,
) -> None:
    write_settings(tmp_path, {"compaction": {"keep_recent_turns": keep_recent_turns}})

    with pytest.raises(ValueError, match="compaction\\.keep_recent_turns"):
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


def test_write_approval_mode_preserves_settings_and_json_format(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"name": "local-model"}})

    write_approval_mode(tmp_path, "guarded")

    settings_path = tmp_path / ".code-squid" / "settings.json"
    assert settings_path.read_text(encoding="utf-8") == (
        '{\n  "model": {\n    "name": "local-model"\n  },\n'
        '  "runtime": {\n    "approval_mode": "guarded"\n  }\n}\n'
    )
    assert load_settings(tmp_path).runtime.approval_mode == "guarded"

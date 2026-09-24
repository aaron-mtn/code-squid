import json
from pathlib import Path

import pytest

from code_squid.app_paths import settings_path
from code_squid.settings import (
    DEFAULT_BUILT_IN_HOOK_SETTINGS,
    load_settings,
    write_approval_mode,
    write_provider,
)


ENV_VARS = [
    "CODE_SQUID_BASE_URL",
    "CODE_SQUID_API_KEY",
    "CODE_SQUID_MODEL",
    "CODE_SQUID_PROVIDER",
    "CODE_SQUID_TEMPERATURE",
    "CODE_SQUID_REASONING_MODE",
    "CODE_SQUID_REASONING_TOKEN_BUDGET",
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
    assert settings.model.provider == "lm_studio"
    assert settings.model.temperature is None
    assert settings.model.reasoning_mode is None
    assert settings.model.reasoning_token_budget is None
    assert settings.model.ollama_request_timeout is None
    assert settings.display.debug is False
    assert settings.runtime.approval_mode == "never"
    assert settings.runtime.max_tool_steps is None
    assert settings.runtime.stream_assistant_text is False
    assert settings.runtime.built_in_hook_settings == DEFAULT_BUILT_IN_HOOK_SETTINGS
    assert settings.runtime.model_request_max_retries == 2
    assert settings.runtime.model_request_retry_backoff_ms == 250
    assert settings.compaction.enabled is True
    assert settings.compaction.trigger_input_tokens == 25_000
    assert settings.compaction.compact_fraction == 0.8
    assert settings.compaction.min_recent_chunks == 2

    runtime_settings = settings.to_runtime_settings()
    assert runtime_settings.provider.provider == "lm_studio"
    assert runtime_settings.provider.model_name == "qwen3.5-9b"
    assert runtime_settings.provider.api_key == "lm-studio"
    assert runtime_settings.provider.reasoning_mode is None
    assert runtime_settings.provider.reasoning_token_budget is None
    assert runtime_settings.provider.ollama_request_timeout is None
    assert runtime_settings.approval_mode == "never"
    assert runtime_settings.compaction.compact_fraction == 0.8
    assert runtime_settings.compaction.min_recent_chunks == 2
    assert runtime_settings.read_file.default_max_lines == 1000
    assert runtime_settings.read_file.minimum_range_lines == 150
    assert runtime_settings.model_request_max_retries == 2
    assert runtime_settings.model_request_retry_backoff_ms == 250


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("model_request_max_retries", -1),
        ("model_request_max_retries", 11),
        ("model_request_max_retries", True),
        ("model_request_retry_backoff_ms", -1),
        ("model_request_retry_backoff_ms", 10_001),
        ("model_request_retry_backoff_ms", False),
    ],
)
def test_invalid_model_request_retry_settings_raise(
    tmp_path: Path,
    name: str,
    value: object,
) -> None:
    write_settings(tmp_path, {"runtime": {name: value}})

    with pytest.raises(ValueError, match=name):
        load_settings(tmp_path)


def test_built_in_hooks_can_be_disabled_in_runtime_settings(
    tmp_path: Path,
) -> None:
    write_settings(
        tmp_path,
        {"runtime": {"built_in_hook_settings": {"too_many_reads": False}}},
    )

    settings = load_settings(tmp_path)

    assert settings.runtime.built_in_hook_settings == {
        **DEFAULT_BUILT_IN_HOOK_SETTINGS,
        "too_many_reads": False,
    }


@pytest.mark.parametrize("enabled", [None, 0, 1, "false"])
def test_invalid_built_in_hook_setting_raises(
    tmp_path: Path,
    enabled: object,
) -> None:
    write_settings(
        tmp_path,
        {"runtime": {"built_in_hook_settings": {"too_many_reads": enabled}}},
    )

    with pytest.raises(
        ValueError,
        match="runtime\\.built_in_hook_settings\\.too_many_reads",
    ):
        load_settings(tmp_path)


def test_unknown_built_in_hook_setting_raises(tmp_path: Path) -> None:
    write_settings(
        tmp_path,
        {"runtime": {"built_in_hook_settings": {"unknown_hook": False}}},
    )

    with pytest.raises(ValueError, match="unknown_hook"):
        load_settings(tmp_path)


def test_application_settings_survive_workspace_change_and_process_reload(
    tmp_path: Path,
) -> None:
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    persisted = {
        "model": {"provider": "lm_studio", "name": "chosen-model"},
        "providers": {
            "lm_studio": {"base_url": "http://lan-host:4321/v1"},
            "openrouter": {"api_key": "saved-router-key", "api_key_env": None},
        },
        "runtime": {"approval_mode": "never"},
    }
    write_settings(workspace_a, persisted)

    first_process = load_settings(workspace_a)
    assert json.loads(settings_path().read_text(encoding="utf-8")) == persisted
    assert (workspace_a / ".code-squid" / "settings.json").exists()
    write_settings(workspace_b, {"model": {"name": "workspace-owned-model"}})
    after_switch = load_settings(workspace_b)
    after_restart = load_settings(workspace_b)

    for settings in (first_process, after_switch, after_restart):
        assert settings.model.provider == "lm_studio"
        assert settings.model.name == "chosen-model"
        assert settings.model.base_url == "http://lan-host:4321/v1"
        assert settings.providers["openrouter"] == {
            "api_key": "saved-router-key",
            "api_key_env": None,
        }
        assert settings.runtime.approval_mode == "never"


def test_existing_application_settings_are_authoritative_over_legacy_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_settings(workspace, {"model": {"name": "legacy-model"}})
    settings_path().write_text(
        json.dumps({"model": {"provider": "ollama", "name": "global-model"}}),
        encoding="utf-8",
    )

    settings = load_settings(workspace)

    assert settings.model.provider == "ollama"
    assert settings.model.name == "global-model"
    assert json.loads(
        (workspace / ".code-squid" / "settings.json").read_text(encoding="utf-8")
    )["model"]["name"] == "legacy-model"


def test_ollama_product_default_is_the_native_endpoint(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"provider": "ollama"}})

    runtime_settings = load_settings(tmp_path).to_runtime_settings()

    assert runtime_settings.provider.base_url == "http://127.0.0.1:11434"


def test_provider_scoped_settings_fall_back_field_by_field_to_profile_defaults(
    tmp_path: Path,
) -> None:
    write_settings(
        tmp_path,
        {
            "model": {"provider": "lm_studio"},
            "providers": {
                "lm_studio": {"base_url": "http://lan-host:1234/v1"},
            },
        },
    )

    settings = load_settings(tmp_path)

    assert settings.model.base_url == "http://lan-host:1234/v1"
    assert settings.model.api_key == "lm-studio"
    assert settings.providers == {
        "lm_studio": {"base_url": "http://lan-host:1234/v1"},
    }


def test_environment_connection_overrides_do_not_mutate_scoped_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted = {
        "model": {"provider": "openrouter"},
        "providers": {
            "openrouter": {
                "base_url": "https://saved.example/v1",
                "api_key": "saved-secret",
                "api_key_env": None,
            },
        },
    }
    write_settings(tmp_path, persisted)
    settings_path = tmp_path / ".code-squid" / "settings.json"
    before = settings_path.read_text(encoding="utf-8")
    monkeypatch.setenv("CODE_SQUID_BASE_URL", "https://environment.example/v1")
    monkeypatch.setenv("CODE_SQUID_API_KEY", "environment-secret")

    settings = load_settings(tmp_path)

    assert settings.model.base_url == "https://environment.example/v1"
    assert settings.model.api_key == "environment-secret"
    assert settings.providers == persisted["providers"]
    assert settings_path.read_text(encoding="utf-8") == before


def test_provider_environment_override_uses_that_providers_saved_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted = {
        "model": {"provider": "lm_studio"},
        "providers": {
            "lm_studio": {"base_url": "http://lm-host:1234/v1"},
            "openrouter": {
                "base_url": "https://saved-router.example/v1",
                "api_key": "saved-router-key",
            },
        },
    }
    write_settings(tmp_path, persisted)
    settings_path = tmp_path / ".code-squid" / "settings.json"
    before = settings_path.read_text(encoding="utf-8")
    monkeypatch.setenv("CODE_SQUID_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-environment-key")

    settings = load_settings(tmp_path)

    assert settings.model.provider == "openrouter"
    assert settings.model.base_url == "https://saved-router.example/v1"
    assert settings.model.api_key == "router-environment-key"
    assert settings_path.read_text(encoding="utf-8") == before


def test_legacy_flat_connection_loads_and_migrates_on_provider_switch(
    tmp_path: Path,
) -> None:
    write_settings(
        tmp_path,
        {
            "model": {
                "provider": "lm_studio",
                "name": "exact-model-id",
                "base_url": "http://legacy-lan:1234/v1",
                "api_key": "legacy-key",
                "api_key_env": None,
            },
        },
    )

    legacy = load_settings(tmp_path)
    assert legacy.model.base_url == "http://legacy-lan:1234/v1"
    assert legacy.model.api_key == "legacy-key"
    assert legacy.model.name == "exact-model-id"

    write_provider(tmp_path, "ollama")
    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert persisted == {
        "model": {"provider": "ollama", "name": "exact-model-id"},
        "providers": {
            "lm_studio": {
                "base_url": "http://legacy-lan:1234/v1",
                "api_key": "legacy-key",
                "api_key_env": None,
            },
        },
    }

    write_provider(tmp_path, "lm_studio")
    restored = load_settings(tmp_path)
    assert restored.model.base_url == "http://legacy-lan:1234/v1"
    assert restored.model.api_key == "legacy-key"
    assert restored.model.name == "exact-model-id"


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
                "model_request_max_retries": 4,
                "model_request_retry_backoff_ms": 75,
            },
            "compaction": {
                "enabled": False,
                "trigger_input_tokens": 24000,
                "compact_fraction": 0.65,
                "min_recent_chunks": 4,
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
    assert settings.runtime.model_request_max_retries == 4
    assert settings.runtime.model_request_retry_backoff_ms == 75
    assert settings.compaction.enabled is False
    assert settings.compaction.trigger_input_tokens == 24000
    assert settings.compaction.compact_fraction == 0.65
    assert settings.compaction.min_recent_chunks == 4

    runtime_settings = settings.to_runtime_settings()
    assert runtime_settings.compaction.compact_fraction == 0.65
    assert runtime_settings.compaction.min_recent_chunks == 4


def test_legacy_keep_recent_turns_is_ignored(tmp_path: Path) -> None:
    write_settings(tmp_path, {"compaction": {"keep_recent_turns": 9}})

    settings = load_settings(tmp_path)

    assert settings.compaction.compact_fraction == 0.8
    assert settings.compaction.min_recent_chunks == 2


def test_settings_file_can_set_zero_temperature(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"temperature": 0}})

    settings = load_settings(tmp_path)

    assert settings.model.temperature == 0


def test_settings_file_can_set_decimal_temperature(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"temperature": 0.2}})

    settings = load_settings(tmp_path)

    assert settings.model.temperature == 0.2


@pytest.mark.parametrize("reasoning_mode", ["off", "low", "medium", "high"])
def test_settings_file_accepts_reasoning_mode(
    tmp_path: Path,
    reasoning_mode: str,
) -> None:
    write_settings(tmp_path, {"model": {"reasoning_mode": reasoning_mode}})

    settings = load_settings(tmp_path)

    assert settings.model.reasoning_mode == reasoning_mode
    assert settings.to_runtime_settings().provider.reasoning_mode == reasoning_mode


@pytest.mark.parametrize("reasoning_token_budget", [0, 1, 4_000])
def test_settings_file_accepts_reasoning_token_budget(
    tmp_path: Path,
    reasoning_token_budget: int,
) -> None:
    write_settings(
        tmp_path,
        {"model": {"reasoning_token_budget": reasoning_token_budget}},
    )

    settings = load_settings(tmp_path)

    assert settings.model.reasoning_token_budget == reasoning_token_budget
    assert (
        settings.to_runtime_settings().provider.reasoning_token_budget
        == reasoning_token_budget
    )


def test_settings_file_accepts_ollama_request_timeout(tmp_path: Path) -> None:
    write_settings(tmp_path, {"model": {"ollama_request_timeout": 45.5}})

    settings = load_settings(tmp_path)

    assert settings.model.ollama_request_timeout == 45.5
    assert settings.to_runtime_settings().provider.ollama_request_timeout == 45.5


@pytest.mark.parametrize("value", [0, -1, True, False, "45", []])
def test_invalid_ollama_request_timeout_raises(
    tmp_path: Path,
    value: object,
) -> None:
    write_settings(tmp_path, {"model": {"ollama_request_timeout": value}})

    with pytest.raises(ValueError, match=r"model\.ollama_request_timeout"):
        load_settings(tmp_path)


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


def test_empty_reasoning_mode_env_var_unsets_saved_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(tmp_path, {"model": {"reasoning_mode": "high"}})
    monkeypatch.setenv("CODE_SQUID_REASONING_MODE", "")

    assert load_settings(tmp_path).model.reasoning_mode is None


def test_reasoning_mode_env_var_overrides_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(tmp_path, {"model": {"reasoning_mode": "low"}})
    monkeypatch.setenv("CODE_SQUID_REASONING_MODE", "high")

    assert load_settings(tmp_path).model.reasoning_mode == "high"


def test_invalid_reasoning_mode_env_var_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODE_SQUID_REASONING_MODE", "auto")

    with pytest.raises(ValueError, match="CODE_SQUID_REASONING_MODE"):
        load_settings(tmp_path)


@pytest.mark.parametrize("reasoning_mode", ["auto", "max", "xhigh", "none", 1])
def test_invalid_reasoning_mode_settings_raise(
    tmp_path: Path,
    reasoning_mode: object,
) -> None:
    write_settings(tmp_path, {"model": {"reasoning_mode": reasoning_mode}})

    with pytest.raises(ValueError, match="model\\.reasoning_mode"):
        load_settings(tmp_path)


def test_reasoning_token_budget_env_var_overrides_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(tmp_path, {"model": {"reasoning_token_budget": 2_000}})
    monkeypatch.setenv("CODE_SQUID_REASONING_TOKEN_BUDGET", "4000")

    assert load_settings(tmp_path).model.reasoning_token_budget == 4_000


def test_empty_reasoning_token_budget_env_var_unsets_saved_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(tmp_path, {"model": {"reasoning_token_budget": 2_000}})
    monkeypatch.setenv("CODE_SQUID_REASONING_TOKEN_BUDGET", "")

    assert load_settings(tmp_path).model.reasoning_token_budget is None


@pytest.mark.parametrize("value", ["many", "1.5", "-1"])
def test_invalid_reasoning_token_budget_env_var_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("CODE_SQUID_REASONING_TOKEN_BUDGET", value)

    with pytest.raises(ValueError, match="CODE_SQUID_REASONING_TOKEN_BUDGET"):
        load_settings(tmp_path)


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "4000", []])
def test_invalid_reasoning_token_budget_settings_raise(
    tmp_path: Path,
    value: object,
) -> None:
    write_settings(tmp_path, {"model": {"reasoning_token_budget": value}})

    with pytest.raises(ValueError, match=r"model\.reasoning_token_budget"):
        load_settings(tmp_path)


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


@pytest.mark.parametrize("compact_fraction", [0, -0.1, 1.1, True, False, "0.8"])
def test_invalid_compaction_compact_fraction_raises(
    tmp_path: Path,
    compact_fraction: object,
) -> None:
    write_settings(tmp_path, {"compaction": {"compact_fraction": compact_fraction}})

    with pytest.raises(ValueError, match="compaction\\.compact_fraction"):
        load_settings(tmp_path)


@pytest.mark.parametrize("min_recent_chunks", [-1, True, False, 2.0, "2"])
def test_invalid_compaction_min_recent_chunks_raises(
    tmp_path: Path,
    min_recent_chunks: object,
) -> None:
    write_settings(
        tmp_path, {"compaction": {"min_recent_chunks": min_recent_chunks}}
    )

    with pytest.raises(ValueError, match="compaction\\.min_recent_chunks"):
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

    persisted_path = settings_path()
    assert persisted_path.read_text(encoding="utf-8") == (
        '{\n  "model": {\n    "name": "local-model"\n  },\n'
        '  "runtime": {\n    "approval_mode": "guarded"\n  }\n}\n'
    )
    assert load_settings(tmp_path).runtime.approval_mode == "guarded"

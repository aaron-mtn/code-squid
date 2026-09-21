"""Load application-wide Code Squid settings with environment overrides."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from code_squid.app_paths import settings_path as app_settings_path
from code_squid.app_paths import workspace_state_dir
from code_squid.provider_setup import PROFILES_BY_ID, VALID_PROVIDERS
from squid_core.settings import (
    CompactionSettings as CoreCompactionSettings,
    ProviderSettings,
    RuntimeSettings as CoreRuntimeSettings,
    VALID_REASONING_MODES,
)
from squid_core.storage.atomic_json import atomic_write_json


# Defaults keep Code Squid usable with a local OpenAI-compatible server,
# especially LM Studio, without requiring a settings file.
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
DEFAULT_MODEL_NAME = "qwen3.5-9b"
DEFAULT_PROVIDER = "lm_studio"
DEFAULT_DEBUG = False
DEFAULT_TEMPERATURE = None
DEFAULT_REASONING_MODE = None
DEFAULT_REASONING_TOKEN_BUDGET = None
DEFAULT_OLLAMA_REQUEST_TIMEOUT = None

# Approval mode is parsed here, but enforcement belongs in the runtime/tool
# execution path. "never" is the current trusted-local behavior.
DEFAULT_APPROVAL_MODE = "never"
VALID_APPROVAL_MODES = {"never", "always", "guarded"}

# None means unlimited tool steps. Users can set a positive integer if they want
# a loop guard for smaller or less reliable models.
DEFAULT_MAX_TOOL_STEPS = None
DEFAULT_STREAM_ASSISTANT_TEXT = False
DEFAULT_TOO_MANY_READS_ENABLED = True
DEFAULT_MODEL_REQUEST_MAX_RETRIES = 2
DEFAULT_MODEL_REQUEST_RETRY_BACKOFF_MS = 250

DEFAULT_COMPACTION_ENABLED = True
DEFAULT_COMPACTION_TRIGGER_INPUT_TOKENS = 25_000
DEFAULT_COMPACTION_FRACTION = 0.80
DEFAULT_COMPACTION_MIN_RECENT_CHUNKS = 2


@dataclass(frozen=True)
class ModelSettings:
    base_url: str | None = DEFAULT_BASE_URL
    api_key: str | None = DEFAULT_API_KEY
    api_key_env: str | None = None
    name: str = DEFAULT_MODEL_NAME
    provider: str = DEFAULT_PROVIDER
    temperature: float | int | None = DEFAULT_TEMPERATURE
    reasoning_mode: str | None = DEFAULT_REASONING_MODE
    reasoning_token_budget: int | None = DEFAULT_REASONING_TOKEN_BUDGET
    ollama_request_timeout: float | int | None = DEFAULT_OLLAMA_REQUEST_TIMEOUT


@dataclass(frozen=True)
class DisplaySettings:
    debug: bool = DEFAULT_DEBUG


@dataclass(frozen=True)
class RuntimeSettings:
    approval_mode: str = DEFAULT_APPROVAL_MODE
    max_tool_steps: int | None = DEFAULT_MAX_TOOL_STEPS
    stream_assistant_text: bool = DEFAULT_STREAM_ASSISTANT_TEXT
    too_many_reads_enabled: bool = DEFAULT_TOO_MANY_READS_ENABLED
    model_request_max_retries: int = DEFAULT_MODEL_REQUEST_MAX_RETRIES
    model_request_retry_backoff_ms: int = DEFAULT_MODEL_REQUEST_RETRY_BACKOFF_MS


@dataclass(frozen=True)
class CompactionSettings:
    enabled: bool = DEFAULT_COMPACTION_ENABLED
    trigger_input_tokens: int = DEFAULT_COMPACTION_TRIGGER_INPUT_TOKENS
    compact_fraction: float = DEFAULT_COMPACTION_FRACTION
    min_recent_chunks: int = DEFAULT_COMPACTION_MIN_RECENT_CHUNKS


@dataclass(frozen=True)
class Settings:
    """Code Squid's persisted settings shape and presentation preferences."""

    model: ModelSettings
    display: DisplaySettings
    runtime: RuntimeSettings
    compaction: CompactionSettings = field(default_factory=CompactionSettings)
    # Only explicitly saved connection fields live here. Missing providers and
    # fields continue to inherit ProviderProfile defaults at resolution time.
    providers: dict[str, dict[str, str | None]] = field(default_factory=dict)

    def to_runtime_settings(self) -> CoreRuntimeSettings:
        """Translate application configuration into effective Core settings."""

        # An omitted Ollama endpoint means its conventional local endpoint;
        # Code Squid's LM Studio default must not leak into Core construction.
        base_url = self.model.base_url
        if self.model.provider == "ollama" and base_url == DEFAULT_BASE_URL:
            base_url = None

        return CoreRuntimeSettings(
            provider=ProviderSettings(
                provider=self.model.provider,
                model_name=self.model.name,
                base_url=base_url,
                api_key=self.model.api_key,
                temperature=self.model.temperature,
                reasoning_mode=self.model.reasoning_mode,
                reasoning_token_budget=self.model.reasoning_token_budget,
                ollama_request_timeout=self.model.ollama_request_timeout,
            ),
            approval_mode=self.runtime.approval_mode,
            max_tool_steps=self.runtime.max_tool_steps,
            stream_assistant_text=self.runtime.stream_assistant_text,
            model_request_max_retries=self.runtime.model_request_max_retries,
            model_request_retry_backoff_ms=(
                self.runtime.model_request_retry_backoff_ms
            ),
            compaction=CoreCompactionSettings(
                enabled=self.compaction.enabled,
                trigger_input_tokens=self.compaction.trigger_input_tokens,
                compact_fraction=self.compaction.compact_fraction,
                min_recent_chunks=self.compaction.min_recent_chunks,
            ),
        )


def _read_settings_file(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        return {}

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except JSONDecodeError as error:
        raise ValueError(f"Invalid settings JSON in {settings_path}: {error.msg}") from error

    if not isinstance(settings, dict):
        raise ValueError(f"Invalid settings JSON in {settings_path}: root value must be an object")

    return settings


def _read_application_settings(repo_root: Path) -> tuple[Path, dict[str, Any]]:
    """Read global settings, adopting this workspace's legacy file once.

    ``repo_root`` remains an input only so an existing installation can seed the
    application-wide file. Once that file exists, workspace data is ignored.
    """
    settings_path = app_settings_path()
    if settings_path.exists():
        return settings_path, _read_settings_file(settings_path)

    legacy_path = workspace_state_dir(repo_root) / "settings.json"
    raw_settings = _read_settings_file(legacy_path)
    if legacy_path.exists():
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(settings_path, raw_settings)
        except OSError:
            # Adoption is best effort. The current process can still honor the
            # legacy configuration, while all future writes target app home.
            pass
    return settings_path, raw_settings


def _section(settings: dict[str, Any], name: str, settings_path: Path) -> dict[str, Any]:
    value = settings.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Invalid settings JSON in {settings_path}: {name} must be an object")

    return value


def _resolve_api_key(
    connection_settings: dict[str, Any],
    settings_path: Path,
    *,
    provider: str,
    field_prefix: str,
) -> tuple[str | None, str | None]:
    # Resolve API keys without requiring secrets in the app settings file.
    # CODE_SQUID_API_KEY wins over api_key_env, which wins over api_key.
    profile = PROFILES_BY_ID[provider]
    api_key_env = connection_settings.get("api_key_env", profile.api_key_env)
    if api_key_env is not None and not isinstance(api_key_env, str):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: {field_prefix}.api_key_env "
            "must be a string or null"
        )

    env_api_key = os.getenv("CODE_SQUID_API_KEY")
    if env_api_key is not None:
        return env_api_key, api_key_env

    if api_key_env is not None:
        api_key = os.getenv(api_key_env)
        if api_key is not None:
            return api_key, api_key_env
        if "api_key_env" in connection_settings:
            raise ValueError(
                f"Invalid settings JSON in {settings_path}: {field_prefix}.api_key_env "
                f"names missing environment variable {api_key_env!r}"
            )

    return connection_settings.get("api_key", profile.api_key), api_key_env


def _approval_mode(runtime_settings: dict[str, Any], settings_path: Path) -> str:
    approval_mode = runtime_settings.get("approval_mode", DEFAULT_APPROVAL_MODE)
    if approval_mode not in VALID_APPROVAL_MODES:
        valid_modes = ", ".join(sorted(VALID_APPROVAL_MODES))
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: runtime.approval_mode must be one of {valid_modes}"
        )

    return approval_mode


def _max_tool_steps(runtime_settings: dict[str, Any], settings_path: Path) -> int | None:
    max_tool_steps = runtime_settings.get("max_tool_steps", DEFAULT_MAX_TOOL_STEPS)
    if max_tool_steps is None:
        return None

    # Python bool is a subclass of int, but true/false should not silently
    # become 1/0 tool-step limits.
    if isinstance(max_tool_steps, bool) or not isinstance(max_tool_steps, int) or max_tool_steps < 1:
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: runtime.max_tool_steps must be null or a positive integer"
        )

    return max_tool_steps


def _stream_assistant_text(runtime_settings: dict[str, Any], settings_path: Path) -> bool:
    stream_assistant_text = runtime_settings.get(
        "stream_assistant_text",
        DEFAULT_STREAM_ASSISTANT_TEXT,
    )
    if not isinstance(stream_assistant_text, bool):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: runtime.stream_assistant_text must be a boolean"
        )

    stream_env = os.getenv("CODE_SQUID_STREAM_ASSISTANT_TEXT")
    if stream_env is None:
        return stream_assistant_text

    return stream_env == "1"


def _too_many_reads_enabled(
    runtime_settings: dict[str, Any],
    settings_path: Path,
) -> bool:
    enabled = runtime_settings.get(
        "too_many_reads_enabled",
        DEFAULT_TOO_MANY_READS_ENABLED,
    )
    if not isinstance(enabled, bool):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: "
            "runtime.too_many_reads_enabled must be a boolean"
        )
    return enabled


def _model_request_retry_settings(
    runtime_settings: dict[str, Any],
    settings_path: Path,
) -> tuple[int, int]:
    max_retries = runtime_settings.get(
        "model_request_max_retries",
        DEFAULT_MODEL_REQUEST_MAX_RETRIES,
    )
    backoff_ms = runtime_settings.get(
        "model_request_retry_backoff_ms",
        DEFAULT_MODEL_REQUEST_RETRY_BACKOFF_MS,
    )
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or not 0 <= max_retries <= 10
    ):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: "
            "runtime.model_request_max_retries must be an integer from 0 through 10"
        )
    if (
        isinstance(backoff_ms, bool)
        or not isinstance(backoff_ms, int)
        or not 0 <= backoff_ms <= 10_000
    ):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: "
            "runtime.model_request_retry_backoff_ms must be an integer from 0 through 10000"
        )
    return max_retries, backoff_ms


def _positive_int(value: Any, field_path: str, settings_path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: {field_path} must be a positive integer"
        )

    return value


def _fraction(value: Any, field_path: str, settings_path: Path) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not 0 < value <= 1
    ):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: {field_path} must be "
            "greater than 0 and at most 1"
        )

    return float(value)


def _non_negative_int(value: Any, field_path: str, settings_path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: {field_path} must be a "
            "non-negative integer"
        )

    return value


def _compaction_settings(
    compaction_settings: dict[str, Any],
    settings_path: Path,
) -> CompactionSettings:
    enabled = compaction_settings.get("enabled", DEFAULT_COMPACTION_ENABLED)
    if not isinstance(enabled, bool):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: compaction.enabled must be a boolean"
        )

    trigger_input_tokens = _positive_int(
        compaction_settings.get(
            "trigger_input_tokens",
            DEFAULT_COMPACTION_TRIGGER_INPUT_TOKENS,
        ),
        "compaction.trigger_input_tokens",
        settings_path,
    )
    compact_fraction = _fraction(
        compaction_settings.get("compact_fraction", DEFAULT_COMPACTION_FRACTION),
        "compaction.compact_fraction",
        settings_path,
    )
    min_recent_chunks = _non_negative_int(
        compaction_settings.get(
            "min_recent_chunks", DEFAULT_COMPACTION_MIN_RECENT_CHUNKS
        ),
        "compaction.min_recent_chunks",
        settings_path,
    )

    return CompactionSettings(
        enabled=enabled,
        trigger_input_tokens=trigger_input_tokens,
        compact_fraction=compact_fraction,
        min_recent_chunks=min_recent_chunks,
    )


def _validate_temperature(value: Any, source: str) -> float | int | None:
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 2:
        raise ValueError(f"Invalid {source}: model.temperature must be null or a number from 0 through 2")

    return value


def _temperature(model_settings: dict[str, Any], settings_path: Path) -> float | int | None:
    temperature = _validate_temperature(
        model_settings.get("temperature", DEFAULT_TEMPERATURE),
        f"settings JSON in {settings_path}",
    )

    temperature_env = os.getenv("CODE_SQUID_TEMPERATURE")
    if temperature_env is None:
        return temperature

    if temperature_env == "":
        return None

    try:
        return _validate_temperature(float(temperature_env), "CODE_SQUID_TEMPERATURE")
    except ValueError as error:
        if str(error).startswith("Invalid CODE_SQUID_TEMPERATURE"):
            raise
        raise ValueError(
            "Invalid CODE_SQUID_TEMPERATURE: model.temperature must be null or a number from 0 through 2"
        ) from error


def _validate_reasoning_mode(value: Any, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in VALID_REASONING_MODES:
        valid_modes = ", ".join(sorted(VALID_REASONING_MODES))
        raise ValueError(
            f"Invalid {source}: model.reasoning_mode must be null or one of {valid_modes}"
        )
    return value


def _reasoning_mode(model_settings: dict[str, Any], settings_path: Path) -> str | None:
    reasoning_mode = _validate_reasoning_mode(
        model_settings.get("reasoning_mode", DEFAULT_REASONING_MODE),
        f"settings JSON in {settings_path}",
    )
    reasoning_mode_env = os.getenv("CODE_SQUID_REASONING_MODE")
    if reasoning_mode_env is None:
        return reasoning_mode
    if reasoning_mode_env == "":
        return None
    return _validate_reasoning_mode(reasoning_mode_env, "CODE_SQUID_REASONING_MODE")


def _validate_reasoning_token_budget(value: Any, source: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"Invalid {source}: model.reasoning_token_budget must be null or a "
            "non-negative integer"
        )
    return value


def _reasoning_token_budget(
    model_settings: dict[str, Any],
    settings_path: Path,
) -> int | None:
    budget = _validate_reasoning_token_budget(
        model_settings.get(
            "reasoning_token_budget",
            DEFAULT_REASONING_TOKEN_BUDGET,
        ),
        f"settings JSON in {settings_path}",
    )
    budget_env = os.getenv("CODE_SQUID_REASONING_TOKEN_BUDGET")
    if budget_env is None:
        return budget
    if budget_env == "":
        return None
    try:
        parsed_budget = int(budget_env)
    except ValueError as error:
        raise ValueError(
            "Invalid CODE_SQUID_REASONING_TOKEN_BUDGET: "
            "model.reasoning_token_budget must be null or a non-negative integer"
        ) from error
    return _validate_reasoning_token_budget(
        parsed_budget,
        "CODE_SQUID_REASONING_TOKEN_BUDGET",
    )


def _ollama_request_timeout(
    model_settings: dict[str, Any],
    settings_path: Path,
) -> float | int | None:
    """Read an optional Ollama-only timeout; the provider owns its default."""

    timeout = model_settings.get(
        "ollama_request_timeout",
        DEFAULT_OLLAMA_REQUEST_TIMEOUT,
    )
    if timeout is None:
        return None
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int | float)
        or timeout <= 0
    ):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: "
            "model.ollama_request_timeout must be null or a positive number"
        )
    return timeout


def _provider(model_settings: dict[str, Any], settings_path: Path) -> str:
    provider = os.getenv("CODE_SQUID_PROVIDER", model_settings.get("provider", DEFAULT_PROVIDER))
    if provider not in VALID_PROVIDERS:
        valid_providers = ", ".join(sorted(VALID_PROVIDERS))
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: model.provider must be one of {valid_providers}"
        )

    return provider


_CONNECTION_FIELDS = ("base_url", "api_key", "api_key_env")


def _provider_connections(
    raw_settings: dict[str, Any],
    model_settings: dict[str, Any],
    settings_path: Path,
) -> dict[str, dict[str, str | None]]:
    """Read scoped connections and interpret legacy flat fields in memory."""
    raw_providers = _section(raw_settings, "providers", settings_path)
    providers: dict[str, dict[str, str | None]] = {}
    for provider_id, value in raw_providers.items():
        if provider_id not in VALID_PROVIDERS:
            valid_providers = ", ".join(sorted(VALID_PROVIDERS))
            raise ValueError(
                f"Invalid settings JSON in {settings_path}: providers contains "
                f"unsupported provider {provider_id!r}; expected one of {valid_providers}"
            )
        if not isinstance(value, dict):
            raise ValueError(
                f"Invalid settings JSON in {settings_path}: providers.{provider_id} "
                "must be an object"
            )
        connection: dict[str, str | None] = {}
        for name in _CONNECTION_FIELDS:
            if name not in value:
                continue
            field_value = value[name]
            if field_value is not None and not isinstance(field_value, str):
                raise ValueError(
                    f"Invalid settings JSON in {settings_path}: "
                    f"providers.{provider_id}.{name} must be a string or null"
                )
            connection[name] = field_value
        providers[provider_id] = connection

    saved_provider = model_settings.get("provider", DEFAULT_PROVIDER)
    if saved_provider in VALID_PROVIDERS:
        legacy = {
            name: model_settings[name]
            for name in _CONNECTION_FIELDS
            if name in model_settings
        }
        if legacy:
            # Scoped values win field-by-field if a partially migrated file has
            # both shapes. Loading alone intentionally does not rewrite disk.
            providers.setdefault(saved_provider, {})
            providers[saved_provider] = legacy | providers[saved_provider]
    return providers


def load_settings(repo_root: Path) -> Settings:
    settings_path, raw_settings = _read_application_settings(repo_root)
    model_settings = _section(raw_settings, "model", settings_path)
    display_settings = _section(raw_settings, "display", settings_path)
    runtime_settings = _section(raw_settings, "runtime", settings_path)
    compaction_settings = _section(raw_settings, "compaction", settings_path)

    provider = _provider(model_settings, settings_path)
    profile = PROFILES_BY_ID[provider]
    providers = _provider_connections(raw_settings, model_settings, settings_path)
    connection_settings = providers.get(provider, {})
    base_url = os.getenv(
        "CODE_SQUID_BASE_URL",
        connection_settings.get("base_url", profile.base_url),
    )
    api_key, api_key_env = _resolve_api_key(
        connection_settings,
        settings_path,
        provider=provider,
        field_prefix=f"providers.{provider}",
    )
    model_name = os.getenv("CODE_SQUID_MODEL", model_settings.get("name", DEFAULT_MODEL_NAME))
    temperature = _temperature(model_settings, settings_path)
    reasoning_mode = _reasoning_mode(model_settings, settings_path)
    reasoning_token_budget = _reasoning_token_budget(model_settings, settings_path)
    ollama_request_timeout = _ollama_request_timeout(model_settings, settings_path)
    debug = display_settings.get("debug", DEFAULT_DEBUG)
    approval_mode = _approval_mode(runtime_settings, settings_path)
    max_tool_steps = _max_tool_steps(runtime_settings, settings_path)
    stream_assistant_text = _stream_assistant_text(runtime_settings, settings_path)
    too_many_reads_enabled = _too_many_reads_enabled(runtime_settings, settings_path)
    model_request_max_retries, model_request_retry_backoff_ms = (
        _model_request_retry_settings(runtime_settings, settings_path)
    )
    compaction = _compaction_settings(compaction_settings, settings_path)

    debug_env = os.getenv("CODE_SQUID_DEBUG")
    if debug_env is not None:
        debug = debug_env == "1"

    return Settings(
        model=ModelSettings(
            base_url=base_url,
            api_key=api_key,
            api_key_env=api_key_env,
            name=model_name,
            provider=provider,
            temperature=temperature,
            reasoning_mode=reasoning_mode,
            reasoning_token_budget=reasoning_token_budget,
            ollama_request_timeout=ollama_request_timeout,
        ),
        display=DisplaySettings(debug=bool(debug)),
        runtime=RuntimeSettings(
            approval_mode=approval_mode,
            max_tool_steps=max_tool_steps,
            stream_assistant_text=stream_assistant_text,
            too_many_reads_enabled=too_many_reads_enabled,
            model_request_max_retries=model_request_max_retries,
            model_request_retry_backoff_ms=model_request_retry_backoff_ms,
        ),
        compaction=compaction,
        providers=providers,
    )


def write_approval_mode(repo_root: Path, approval_mode: str) -> None:
    if approval_mode not in VALID_APPROVAL_MODES:
        valid_modes = ", ".join(sorted(VALID_APPROVAL_MODES))
        raise ValueError(f"approval_mode must be one of {valid_modes}")

    settings_path, raw_settings = _read_application_settings(repo_root)
    runtime_settings = _section(raw_settings, "runtime", settings_path)
    runtime_settings["approval_mode"] = approval_mode
    raw_settings["runtime"] = runtime_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def write_compaction_trigger_input_tokens(repo_root: Path, tokens: int) -> None:
    """Persist the automatic compaction trigger without replacing its peers."""

    settings_path, raw_settings = _read_application_settings(repo_root)
    tokens = _positive_int(tokens, "compaction.trigger_input_tokens", settings_path)
    compaction_settings = _section(raw_settings, "compaction", settings_path)
    compaction_settings["trigger_input_tokens"] = tokens
    raw_settings["compaction"] = compaction_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def write_provider(repo_root: Path, provider: str) -> None:
    """Persist one supported provider without replacing unrelated settings."""

    if provider not in VALID_PROVIDERS:
        valid_providers = ", ".join(sorted(VALID_PROVIDERS))
        raise ValueError(f"provider must be one of {valid_providers}")

    settings_path, raw_settings = _read_application_settings(repo_root)
    model_settings = _section(raw_settings, "model", settings_path)
    _migrate_flat_provider_connection(raw_settings, model_settings, settings_path)
    model_settings["provider"] = provider
    raw_settings["model"] = model_settings
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def write_model_name(repo_root: Path, model_name: str) -> None:
    """Persist a non-empty model name without replacing unrelated settings."""

    if not model_name:
        raise ValueError("model name must not be empty")

    _write_model_value(repo_root, "name", model_name)


def write_model_value(repo_root: Path, name: str, value: Any) -> None:
    """Persist one connection value for the saved provider without exposing it."""
    if name not in {"base_url", "api_key", "api_key_env"}:
        raise ValueError(f"unsupported model setting: {name}")
    settings_path, raw_settings = _read_application_settings(repo_root)
    model_settings = _section(raw_settings, "model", settings_path)
    provider = model_settings.get("provider", DEFAULT_PROVIDER)
    if provider not in VALID_PROVIDERS:
        valid_providers = ", ".join(sorted(VALID_PROVIDERS))
        raise ValueError(f"provider must be one of {valid_providers}")

    providers = _migrate_flat_provider_connection(
        raw_settings,
        model_settings,
        settings_path,
    )
    connection = providers.setdefault(provider, {})
    connection[name] = value
    raw_settings["providers"] = providers
    raw_settings["model"] = model_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def _migrate_flat_provider_connection(
    raw_settings: dict[str, Any],
    model_settings: dict[str, Any],
    settings_path: Path,
) -> dict[str, Any]:
    """Move legacy flat connection fields under their saved provider."""
    providers = _section(raw_settings, "providers", settings_path)
    provider = model_settings.get("provider", DEFAULT_PROVIDER)
    legacy = {
        name: model_settings.pop(name)
        for name in _CONNECTION_FIELDS
        if name in model_settings
    }
    if legacy and provider in VALID_PROVIDERS:
        existing = providers.get(provider, {})
        if not isinstance(existing, dict):
            raise ValueError(
                f"Invalid settings JSON in {settings_path}: providers.{provider} "
                "must be an object"
            )
        # A scoped field is authoritative in a partially migrated settings file.
        providers[provider] = legacy | existing
    if providers:
        raw_settings["providers"] = providers
    return providers


def _write_model_value(repo_root: Path, name: str, value: Any) -> None:
    """Update one model field while preserving the user's complete settings file."""

    settings_path, raw_settings = _read_application_settings(repo_root)
    model_settings = _section(raw_settings, "model", settings_path)
    model_settings[name] = value
    raw_settings["model"] = model_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)

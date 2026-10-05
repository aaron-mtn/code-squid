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
from squid_providers.catalog import (
    VALID_PROVIDERS, CONNECTION_FIELDS, resolve_config, validate_config,
)
from squid_providers.settings import (
    ProviderSettings, validate_temperature, validate_reasoning_mode,
    validate_reasoning_token_budget,
)
from squid_core.settings import (
    CompactionSettings as CoreCompactionSettings,
    RuntimeSettings as CoreRuntimeSettings,
)
from squid_core.storage.atomic_json import atomic_write_json


# Code Squid chooses its initial backend/model; Providers owns connection defaults.
DEFAULT_MODEL_NAME = "qwen3.5-9b"
DEFAULT_PROVIDER = "lm_studio"
DEFAULT_DEBUG = False
DEFAULT_SHOW_REASONING = False
DEFAULT_TEMPERATURE = None
DEFAULT_REASONING_MODE = None
DEFAULT_REASONING_TOKEN_BUDGET = None

# Approval mode is parsed here, but enforcement belongs in the runtime/tool
# execution path. "never" is the current trusted-local behavior.
DEFAULT_APPROVAL_MODE = "never"
VALID_APPROVAL_MODES = {"never", "always", "guarded"}

# None means unlimited tool steps. Users can set a positive integer if they want
# a loop guard for smaller or less reliable models.
DEFAULT_MAX_TOOL_STEPS = None
DEFAULT_STREAM_ASSISTANT_TEXT = False
# Stable application-level IDs keep enablement policy out of the generic Hook
# implementations and let future Mod/user configuration target one built-in.
DEFAULT_BUILT_IN_HOOK_SETTINGS = {
    "too_many_reads": True,
    "post_verification": True,
    "repeated_failure": False,
}
DEFAULT_MODEL_REQUEST_MAX_RETRIES = 2
DEFAULT_MODEL_REQUEST_RETRY_BACKOFF_MS = 250

DEFAULT_COMPACTION_ENABLED = True
DEFAULT_COMPACTION_TRIGGER_INPUT_TOKENS = 25_000
DEFAULT_COMPACTION_FRACTION = 0.80
DEFAULT_COMPACTION_MIN_RECENT_CHUNKS = 2


@dataclass(frozen=True)
class ModelSettings:
    """Selected model, shared preferences and effective provider-owned config."""

    # Effective connection snapshots for presentation; overrides belong only
    # in provider_config (or the persisted providers mapping), never these fields.
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    name: str = DEFAULT_MODEL_NAME
    provider: str = DEFAULT_PROVIDER
    temperature: float | int | None = DEFAULT_TEMPERATURE
    reasoning_mode: str | None = DEFAULT_REASONING_MODE
    reasoning_token_budget: int | None = DEFAULT_REASONING_TOKEN_BUDGET
    provider_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DisplaySettings:
    """Application presentation preferences."""

    debug: bool = DEFAULT_DEBUG
    show_reasoning: bool = DEFAULT_SHOW_REASONING


@dataclass(frozen=True)
class RuntimeSettings:
    approval_mode: str = DEFAULT_APPROVAL_MODE
    trusted_commands: tuple[str, ...] = ()
    max_tool_steps: int | None = DEFAULT_MAX_TOOL_STEPS
    stream_assistant_text: bool = DEFAULT_STREAM_ASSISTANT_TEXT
    built_in_hook_settings: dict[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_BUILT_IN_HOOK_SETTINGS)
    )
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
    # Only explicitly saved configuration overrides live here. Missing providers and
    # fields continue to inherit ProviderProfile defaults at resolution time.
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_provider_settings(self) -> ProviderSettings:
        """Resolve application transport values without putting them into Core."""

        config = dict(self.model.provider_config)
        # Directly constructed settings still inherit provider defaults. Loaded
        # settings carry resolved config, including explicitly null credentials.
        if not all(name in config for name in CONNECTION_FIELDS):
            config = resolve_config(self.model.provider, config)
        return ProviderSettings(
            provider=self.model.provider,
            model_name=self.model.name,
            base_url=config["base_url"],
            api_key=config["api_key"],
            temperature=self.model.temperature,
            reasoning_mode=self.model.reasoning_mode,
            reasoning_token_budget=self.model.reasoning_token_budget,
            config=config,
        )

    def to_runtime_settings(self) -> CoreRuntimeSettings:
        """Translate only generic execution settings into the Core contract."""

        return CoreRuntimeSettings(
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


def _read_application_settings(workspace_root: Path) -> tuple[Path, dict[str, Any]]:
    """Read global settings, adopting this workspace's legacy file once.

    ``workspace_root`` remains an input only so an existing installation can seed the
    application-wide file. Once that file exists, workspace data is ignored.
    """
    settings_path = app_settings_path()
    if settings_path.exists():
        return settings_path, _read_settings_file(settings_path)

    legacy_path = workspace_state_dir(workspace_root) / "settings.json"
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


def _approval_mode(runtime_settings: dict[str, Any], settings_path: Path) -> str:
    approval_mode = runtime_settings.get("approval_mode", DEFAULT_APPROVAL_MODE)
    if approval_mode not in VALID_APPROVAL_MODES:
        valid_modes = ", ".join(sorted(VALID_APPROVAL_MODES))
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: runtime.approval_mode must be one of {valid_modes}"
        )

    return approval_mode


def _trusted_commands(
    runtime_settings: dict[str, Any], settings_path: Path
) -> tuple[str, ...]:
    """Load normalized command identities trusted by guarded mode."""

    value = runtime_settings.get("trusted_commands", [])
    if not isinstance(value, list) or any(
        not isinstance(command, str) or not command.strip() for command in value
    ):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: "
            "runtime.trusted_commands must be a list of non-empty strings"
        )
    return tuple(dict.fromkeys(command.strip().casefold() for command in value))


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


def _built_in_hook_settings(
    runtime_settings: dict[str, Any],
    settings_path: Path,
) -> dict[str, bool]:
    configured = runtime_settings.get(
        "built_in_hook_settings",
        {},
    )
    if not isinstance(configured, dict):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: "
            "runtime.built_in_hook_settings must be an object"
        )

    unknown_ids = sorted(set(configured) - set(DEFAULT_BUILT_IN_HOOK_SETTINGS))
    if unknown_ids:
        unknown = ", ".join(unknown_ids)
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: unknown built-in Hook "
            f"ID(s) in runtime.built_in_hook_settings: {unknown}"
        )

    resolved = dict(DEFAULT_BUILT_IN_HOOK_SETTINGS)
    for hook_id, enabled in configured.items():
        if not isinstance(enabled, bool):
            raise ValueError(
                f"Invalid settings JSON in {settings_path}: "
                f"runtime.built_in_hook_settings.{hook_id} must be a boolean"
            )
        resolved[hook_id] = enabled
    return resolved


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


def _temperature(model_settings: dict[str, Any], settings_path: Path) -> float | int | None:
    temperature = validate_temperature(
        model_settings.get("temperature", DEFAULT_TEMPERATURE),
        f"settings JSON in {settings_path}",
    )

    temperature_env = os.getenv("CODE_SQUID_TEMPERATURE")
    if temperature_env is None:
        return temperature

    if temperature_env == "":
        return None

    try:
        return validate_temperature(float(temperature_env), "CODE_SQUID_TEMPERATURE")
    except ValueError as error:
        if str(error).startswith("Invalid CODE_SQUID_TEMPERATURE"):
            raise
        raise ValueError(
            "Invalid CODE_SQUID_TEMPERATURE: model.temperature must be null or a number from 0 through 2"
        ) from error


def _reasoning_mode(model_settings: dict[str, Any], settings_path: Path) -> str | None:
    reasoning_mode = validate_reasoning_mode(
        model_settings.get("reasoning_mode", DEFAULT_REASONING_MODE),
        f"settings JSON in {settings_path}",
    )
    reasoning_mode_env = os.getenv("CODE_SQUID_REASONING_MODE")
    if reasoning_mode_env is None:
        return reasoning_mode
    if reasoning_mode_env == "":
        return None
    return validate_reasoning_mode(reasoning_mode_env, "CODE_SQUID_REASONING_MODE")


def _reasoning_token_budget(
    model_settings: dict[str, Any],
    settings_path: Path,
) -> int | None:
    budget = validate_reasoning_token_budget(
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
    return validate_reasoning_token_budget(
        parsed_budget,
        "CODE_SQUID_REASONING_TOKEN_BUDGET",
    )


def _provider(model_settings: dict[str, Any], settings_path: Path) -> str:
    provider = os.getenv("CODE_SQUID_PROVIDER", model_settings.get("provider", DEFAULT_PROVIDER))
    if provider not in VALID_PROVIDERS:
        valid_providers = ", ".join(sorted(VALID_PROVIDERS))
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: model.provider must be one of {valid_providers}"
        )

    return provider


_CONNECTION_FIELDS = CONNECTION_FIELDS


def _provider_connections(
    raw_settings: dict[str, Any],
    settings_path: Path,
) -> dict[str, dict[str, Any]]:
    """Read only current provider-scoped configuration overrides."""
    raw_providers = _section(raw_settings, "providers", settings_path)
    providers: dict[str, dict[str, Any]] = {}
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
        providers[provider_id] = validate_config(provider_id, value)

    return providers


def load_settings(workspace_root: Path) -> Settings:
    settings_path, raw_settings = _read_application_settings(workspace_root)
    model_settings = _section(raw_settings, "model", settings_path)
    display_settings = _section(raw_settings, "display", settings_path)
    runtime_settings = _section(raw_settings, "runtime", settings_path)
    compaction_settings = _section(raw_settings, "compaction", settings_path)

    provider = _provider(model_settings, settings_path)
    providers = _provider_connections(raw_settings, settings_path)
    connection_settings = dict(providers.get(provider, {}))
    # Product-wide overrides outrank provider credential variables and saved keys.
    if os.getenv("CODE_SQUID_BASE_URL") is not None:
        connection_settings["base_url"] = os.environ["CODE_SQUID_BASE_URL"]
    config = resolve_config(
        provider, connection_settings,
        api_key_override=os.getenv("CODE_SQUID_API_KEY"),
    )
    base_url, api_key, api_key_env = (config[name] for name in _CONNECTION_FIELDS)
    model_name = os.getenv("CODE_SQUID_MODEL", model_settings.get("name", DEFAULT_MODEL_NAME))
    temperature = _temperature(model_settings, settings_path)
    reasoning_mode = _reasoning_mode(model_settings, settings_path)
    reasoning_token_budget = _reasoning_token_budget(model_settings, settings_path)
    debug = display_settings.get("debug", DEFAULT_DEBUG)
    show_reasoning = display_settings.get(
        "show_reasoning",
        DEFAULT_SHOW_REASONING,
    )
    if not isinstance(show_reasoning, bool):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: "
            "display.show_reasoning must be a boolean"
        )
    approval_mode = _approval_mode(runtime_settings, settings_path)
    trusted_commands = _trusted_commands(runtime_settings, settings_path)
    max_tool_steps = _max_tool_steps(runtime_settings, settings_path)
    stream_assistant_text = _stream_assistant_text(runtime_settings, settings_path)
    built_in_hook_settings = _built_in_hook_settings(runtime_settings, settings_path)
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
            provider_config=config,
        ),
        display=DisplaySettings(
            debug=bool(debug),
            show_reasoning=show_reasoning,
        ),
        runtime=RuntimeSettings(
            approval_mode=approval_mode,
            trusted_commands=trusted_commands,
            max_tool_steps=max_tool_steps,
            stream_assistant_text=stream_assistant_text,
            built_in_hook_settings=built_in_hook_settings,
            model_request_max_retries=model_request_max_retries,
            model_request_retry_backoff_ms=model_request_retry_backoff_ms,
        ),
        compaction=compaction,
        providers=providers,
    )


def write_approval_mode(workspace_root: Path, approval_mode: str) -> None:
    if approval_mode not in VALID_APPROVAL_MODES:
        valid_modes = ", ".join(sorted(VALID_APPROVAL_MODES))
        raise ValueError(f"approval_mode must be one of {valid_modes}")

    settings_path, raw_settings = _read_application_settings(workspace_root)
    runtime_settings = _section(raw_settings, "runtime", settings_path)
    runtime_settings["approval_mode"] = approval_mode
    raw_settings["runtime"] = runtime_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def trust_command(workspace_root: Path, command: str) -> None:
    """Persist one normalized guarded-mode command identity."""

    identity = command.casefold().strip()
    if not identity:
        raise ValueError("command identity must be non-empty")

    settings_path, raw_settings = _read_application_settings(workspace_root)
    runtime_settings = _section(raw_settings, "runtime", settings_path)
    trusted_commands = list(_trusted_commands(runtime_settings, settings_path))
    if identity not in trusted_commands:
        trusted_commands.append(identity)
        runtime_settings["trusted_commands"] = trusted_commands
        raw_settings["runtime"] = runtime_settings
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(settings_path, raw_settings)


def write_show_reasoning(workspace_root: Path, show_reasoning: bool) -> None:
    """Persist the reasoning presentation preference without changing the model."""

    if not isinstance(show_reasoning, bool):
        raise ValueError("show_reasoning must be a boolean")

    settings_path, raw_settings = _read_application_settings(workspace_root)
    display_settings = _section(raw_settings, "display", settings_path)
    display_settings["show_reasoning"] = show_reasoning
    raw_settings["display"] = display_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def write_compaction_trigger_input_tokens(workspace_root: Path, tokens: int) -> None:
    """Persist the automatic compaction trigger without replacing its peers."""

    settings_path, raw_settings = _read_application_settings(workspace_root)
    tokens = _positive_int(tokens, "compaction.trigger_input_tokens", settings_path)
    compaction_settings = _section(raw_settings, "compaction", settings_path)
    compaction_settings["trigger_input_tokens"] = tokens
    raw_settings["compaction"] = compaction_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def write_provider(workspace_root: Path, provider: str) -> None:
    """Persist one supported provider without replacing unrelated settings."""

    if provider not in VALID_PROVIDERS:
        valid_providers = ", ".join(sorted(VALID_PROVIDERS))
        raise ValueError(f"provider must be one of {valid_providers}")

    settings_path, raw_settings = _read_application_settings(workspace_root)
    model_settings = _section(raw_settings, "model", settings_path)
    model_settings["provider"] = provider
    raw_settings["model"] = model_settings
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def write_model_name(workspace_root: Path, model_name: str) -> None:
    """Persist a non-empty model name without replacing unrelated settings."""

    if not model_name:
        raise ValueError("model name must not be empty")

    _write_model_value(workspace_root, "name", model_name)


def write_model_value(workspace_root: Path, name: str, value: Any) -> None:
    """Persist one provider-validated config override without exposing secrets."""
    settings_path, raw_settings = _read_application_settings(workspace_root)
    model_settings = _section(raw_settings, "model", settings_path)
    provider = model_settings.get("provider", DEFAULT_PROVIDER)
    if provider not in VALID_PROVIDERS:
        valid_providers = ", ".join(sorted(VALID_PROVIDERS))
        raise ValueError(f"provider must be one of {valid_providers}")

    providers = _provider_connections(raw_settings, settings_path)
    connection = providers.setdefault(provider, {})
    connection = validate_config(provider, connection | {name: value})
    providers[provider] = connection
    raw_settings["providers"] = providers
    raw_settings["model"] = model_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)


def _write_model_value(workspace_root: Path, name: str, value: Any) -> None:
    """Update one model field while preserving the user's complete settings file."""

    settings_path, raw_settings = _read_application_settings(workspace_root)
    model_settings = _section(raw_settings, "model", settings_path)
    model_settings[name] = value
    raw_settings["model"] = model_settings

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(settings_path, raw_settings)

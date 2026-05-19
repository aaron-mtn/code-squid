# config/settings.py

"""Load local Code Squid settings with environment variable overrides."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any


# Defaults keep Code Squid usable with a local OpenAI-compatible server,
# especially LM Studio, without requiring a settings file.
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
DEFAULT_MODEL_NAME = "qwen3.5-9b"
DEFAULT_DEBUG = False

# Approval mode is parsed here, but enforcement belongs in the runtime/tool
# execution path. "never" is the current trusted-local behavior.
DEFAULT_APPROVAL_MODE = "never"
VALID_APPROVAL_MODES = {"never", "always"}

# None means unlimited tool steps. Users can set a positive integer if they want
# a loop guard for smaller or less reliable models.
DEFAULT_MAX_TOOL_STEPS = None


@dataclass(frozen=True)
class ModelSettings:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = DEFAULT_API_KEY
    api_key_env: str | None = None
    name: str = DEFAULT_MODEL_NAME


@dataclass(frozen=True)
class DisplaySettings:
    debug: bool = DEFAULT_DEBUG


@dataclass(frozen=True)
class RuntimeSettings:
    approval_mode: str = DEFAULT_APPROVAL_MODE
    max_tool_steps: int | None = DEFAULT_MAX_TOOL_STEPS


@dataclass(frozen=True)
class Settings:
    model: ModelSettings
    display: DisplaySettings
    runtime: RuntimeSettings


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


def _section(settings: dict[str, Any], name: str, settings_path: Path) -> dict[str, Any]:
    value = settings.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Invalid settings JSON in {settings_path}: {name} must be an object")

    return value


def _resolve_api_key(model_settings: dict[str, Any], settings_path: Path) -> tuple[str, str | None]:
    # Resolve API keys without requiring secrets in .code-squid/settings.json.
    # CODE_SQUID_API_KEY wins over api_key_env, which wins over api_key.
    api_key_env = model_settings.get("api_key_env")
    if api_key_env is not None and not isinstance(api_key_env, str):
        raise ValueError(
            f"Invalid settings JSON in {settings_path}: model.api_key_env must be a string or null"
        )

    env_api_key = os.getenv("CODE_SQUID_API_KEY")
    if env_api_key is not None:
        return env_api_key, api_key_env

    if api_key_env is not None:
        api_key = os.getenv(api_key_env)
        if api_key is None:
            raise ValueError(
                f"Invalid settings JSON in {settings_path}: model.api_key_env names missing environment variable {api_key_env!r}"
            )
        return api_key, api_key_env

    return model_settings.get("api_key", DEFAULT_API_KEY), api_key_env


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


def load_settings(repo_root: Path) -> Settings:
    settings_path = repo_root / ".code-squid" / "settings.json"
    raw_settings = _read_settings_file(settings_path)
    model_settings = _section(raw_settings, "model", settings_path)
    display_settings = _section(raw_settings, "display", settings_path)
    runtime_settings = _section(raw_settings, "runtime", settings_path)

    base_url = os.getenv("CODE_SQUID_BASE_URL", model_settings.get("base_url", DEFAULT_BASE_URL))
    api_key, api_key_env = _resolve_api_key(model_settings, settings_path)
    model_name = os.getenv("CODE_SQUID_MODEL", model_settings.get("name", DEFAULT_MODEL_NAME))
    debug = display_settings.get("debug", DEFAULT_DEBUG)
    approval_mode = _approval_mode(runtime_settings, settings_path)
    max_tool_steps = _max_tool_steps(runtime_settings, settings_path)

    debug_env = os.getenv("CODE_SQUID_DEBUG")
    if debug_env is not None:
        debug = debug_env == "1"

    return Settings(
        model=ModelSettings(
            base_url=base_url,
            api_key=api_key,
            api_key_env=api_key_env,
            name=model_name,
        ),
        display=DisplaySettings(debug=bool(debug)),
        runtime=RuntimeSettings(
            approval_mode=approval_mode,
            max_tool_steps=max_tool_steps,
        ),
    )
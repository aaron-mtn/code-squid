# config/settings.py

"""Load local Code Squid settings with environment variable overrides."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
DEFAULT_MODEL_NAME = "qwen3.5-9b"
DEFAULT_DEBUG = False


@dataclass(frozen=True)
class ModelSettings:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = DEFAULT_API_KEY
    name: str = DEFAULT_MODEL_NAME


@dataclass(frozen=True)
class DisplaySettings:
    debug: bool = DEFAULT_DEBUG


@dataclass(frozen=True)
class Settings:
    model: ModelSettings
    display: DisplaySettings


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


def load_settings(repo_root: Path) -> Settings:
    settings_path = repo_root / ".code-squid" / "settings.json"
    raw_settings = _read_settings_file(settings_path)
    model_settings = _section(raw_settings, "model", settings_path)
    display_settings = _section(raw_settings, "display", settings_path)

    base_url = os.getenv("CODE_SQUID_BASE_URL", model_settings.get("base_url", DEFAULT_BASE_URL))
    api_key = os.getenv("CODE_SQUID_API_KEY", model_settings.get("api_key", DEFAULT_API_KEY))
    model_name = os.getenv("CODE_SQUID_MODEL", model_settings.get("name", DEFAULT_MODEL_NAME))
    debug = display_settings.get("debug", DEFAULT_DEBUG)

    debug_env = os.getenv("CODE_SQUID_DEBUG")
    if debug_env is not None:
        debug = debug_env == "1"

    return Settings(
        model=ModelSettings(
            base_url=base_url,
            api_key=api_key,
            name=model_name,
        ),
        display=DisplaySettings(debug=bool(debug)),
    )

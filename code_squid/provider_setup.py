"""Application orchestration for provider selection and persisted user choices.

Backend identities, defaults and protocol behavior belong to squid-providers.
This module coordinates persistence and UI-neutral status without backend branches.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from squid_providers.catalog import (
    PROVIDER_PROFILES, PROFILES_BY_ID, VALID_PROVIDERS,
    build_provider, tool_call_content_mode, friendly_provider_name,
    resolve_provider_name, resolve_config,
)


def provider_ready(settings) -> bool:
    """Return a UI-neutral readiness observation for effective settings."""
    try:
        provider = build_provider(settings.to_provider_settings())
        return provider.is_ready()
    except (OSError, RuntimeError, ValueError):
        return False


def discover_models(settings) -> list[str]:
    """Return model IDs whenever the provider's discovery API is available."""
    # Some providers expose discovery before inference is ready. Construction
    # delegates that distinction to the provider package.
    provider = build_provider(
        settings.to_provider_settings(),
        for_inference=False,
    )
    return sorted(set(provider.list_models()))


def settings_for_provider(settings, provider_id: str):
    """Build a candidate configuration while preserving the exact model ID."""
    connection = dict(settings.providers.get(provider_id, {}))
    if provider_id == settings.model.provider and provider_id not in settings.providers:
        # Programmatically supplied connection values override catalog defaults.
        connection.update({name: value for name, value in {
            "base_url": settings.model.base_url,
            "api_key": settings.model.api_key,
            "api_key_env": settings.model.api_key_env,
        }.items() if value is not None})
    if os.getenv("CODE_SQUID_BASE_URL") is not None:
        connection["base_url"] = os.environ["CODE_SQUID_BASE_URL"]
    config = resolve_config(
        provider_id, connection,
        api_key_override=os.getenv("CODE_SQUID_API_KEY"),
    )
    base_url, api_key, api_key_env = (
        config[name] for name in ("base_url", "api_key", "api_key_env")
    )
    return replace(
        settings,
        model=replace(
            settings.model,
            provider=provider_id,
            base_url=base_url,
            api_key=api_key,
            api_key_env=api_key_env,
            provider_config=config,
        ),
    )


def select_provider(repo_root: Path, provider_id: str):
    """Select a provider, returning settings and an optional status explanation."""
    from code_squid.settings import load_settings, write_provider

    current = load_settings(repo_root)
    write_provider(repo_root, provider_id)
    effective = load_settings(repo_root)
    if os.getenv("CODE_SQUID_PROVIDER") is not None:
        return effective, "Saved; CODE_SQUID_PROVIDER remains the effective override."

    # Selection is the bootstrap seam for provider-specific configuration.
    # Readiness is therefore reported only after persistence and must never
    # roll back a provider that still needs its URL or credential configured.
    try:
        provider = build_provider(effective.to_provider_settings())
        if not provider.is_ready():
            return effective, f"{friendly_provider_name(provider_id)} is not connected."
    except (OSError, RuntimeError, ValueError):
        return effective, f"{friendly_provider_name(provider_id)} is not connected."

    try:
        unavailable_model = current.model.name not in provider.list_models()
    except (OSError, RuntimeError, ValueError):
        # Model discovery is advisory during selection. Its own command/menu
        # paths retain their existing failure semantics.
        unavailable_model = False
    if unavailable_model:
        return (
            effective,
            f"Configured model {current.model.name!r} is unavailable from "
            f"{friendly_provider_name(provider_id)}; model selection was preserved.",
        )
    return effective, None


def select_model(repo_root: Path, model_id: str):
    """Persist an exact model ID and return the effective same-process settings."""
    from code_squid.settings import load_settings, write_model_name

    write_model_name(repo_root, model_id)
    return load_settings(repo_root)


def set_provider_key(repo_root: Path, api_key: str):
    """Persist the current provider key without returning or printing it."""
    from code_squid.settings import load_settings, write_model_value

    write_model_value(repo_root, "api_key", api_key)
    write_model_value(repo_root, "api_key_env", None)
    return load_settings(repo_root)


def set_provider_url(repo_root: Path, base_url: str):
    """Persist the current provider URL and return effective settings."""
    from code_squid.settings import load_settings, write_model_value

    write_model_value(repo_root, "base_url", base_url.rstrip("/"))
    return load_settings(repo_root)


def active_environment_overrides() -> tuple[str, ...]:
    """Return active provider/model setup overrides without secret values."""
    names = [
        name
        for name in (
            "CODE_SQUID_PROVIDER",
            "CODE_SQUID_BASE_URL",
            "CODE_SQUID_API_KEY",
            "CODE_SQUID_MODEL",
        )
        if os.getenv(name) is not None
    ]
    for profile in PROVIDER_PROFILES:
        if profile.api_key_env and os.getenv(profile.api_key_env) is not None:
            names.append(profile.api_key_env)
    return tuple(names)

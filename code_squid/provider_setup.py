"""Shared Code Squid provider identities and setup operations.

This application layer owns friendly names, product defaults, readiness/model
discovery orchestration, and persisted selections. Provider HTTP transports and
provider-specific protocol details remain in :mod:`squid_core.providers`; CLI
and Desktop presentation should consume this module instead of duplicating the
same provider rules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from squid_core.providers import build_provider


@dataclass(frozen=True)
class ProviderProfile:
    """Describe one user-facing provider without owning its transport."""

    provider_id: str
    friendly_name: str
    transport: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None


PROVIDER_PROFILES = (
    ProviderProfile(
        "squid_models",
        "Squid Models",
        "OpenAI-compatible chat completions",
        "http://127.0.0.1:8080/v1",
        api_key="local",
    ),
    ProviderProfile(
        "lm_studio",
        "LM Studio",
        "OpenAI-compatible chat completions",
        "http://127.0.0.1:1234/v1",
        api_key="lm-studio",
    ),
    ProviderProfile(
        "ollama",
        "Ollama",
        "native Ollama chat",
        "http://127.0.0.1:11434",
    ),
    ProviderProfile(
        "openrouter",
        "OpenRouter",
        "OpenAI-compatible chat completions",
        "https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
    ),
    ProviderProfile(
        "openai_compatible",
        "OpenAI Compatible",
        "OpenAI-compatible chat completions",
        "http://127.0.0.1:8000/v1",
        api_key="local",
    ),
)
PROFILES_BY_ID = {profile.provider_id: profile for profile in PROVIDER_PROFILES}
VALID_PROVIDERS = frozenset(PROFILES_BY_ID)


def friendly_provider_name(provider_id: str) -> str:
    """Return the stable product label for a provider identity."""
    profile = PROFILES_BY_ID.get(provider_id)
    return profile.friendly_name if profile is not None else provider_id


def resolve_provider_name(value: str) -> str | None:
    """Resolve friendly names and convenient ID spellings case-insensitively."""
    normalized = " ".join(value.strip().lower().replace("-", "_").split())
    for profile in PROVIDER_PROFILES:
        choices = {
            profile.provider_id.lower(),
            profile.provider_id.replace("_", " ").lower(),
            profile.friendly_name.lower(),
        }
        if normalized in choices:
            return profile.provider_id
    return None


def provider_ready(settings) -> bool:
    """Return a UI-neutral readiness observation for effective settings."""
    try:
        provider = build_provider(settings.to_runtime_settings().provider)
        return provider.is_ready()
    except (OSError, RuntimeError, ValueError):
        return False


def discover_models(settings) -> list[str]:
    """Return model IDs whenever the provider's discovery API is available."""
    # Discovery is not an inference-readiness probe: OpenRouter's catalog is
    # public, while local providers naturally fail here if their service is down.
    provider = build_provider(
        settings.to_runtime_settings().provider,
        for_inference=False,
    )
    return sorted(set(provider.list_models()))


def settings_for_provider(settings, provider_id: str):
    """Build a candidate configuration while preserving the exact model ID."""
    profile = PROFILES_BY_ID[provider_id]
    api_key = os.getenv("CODE_SQUID_API_KEY")
    if api_key is None and provider_id == settings.model.provider:
        api_key = settings.model.api_key
    if api_key is None and profile.api_key_env:
        api_key = os.getenv(profile.api_key_env)
    if api_key is None:
        api_key = profile.api_key
    configured_base_url = (
        settings.model.base_url
        if provider_id == settings.model.provider
        else profile.base_url
    )
    base_url = os.getenv("CODE_SQUID_BASE_URL", configured_base_url)
    return replace(
        settings,
        model=replace(
            settings.model,
            provider=provider_id,
            base_url=base_url,
            api_key=api_key,
            api_key_env=profile.api_key_env,
        ),
    )


def select_provider(repo_root: Path, provider_id: str):
    """Select one ready provider, returning settings and an optional explanation."""
    from code_squid.settings import load_settings, write_provider

    current = load_settings(repo_root)
    candidate = settings_for_provider(current, provider_id)
    unavailable_model = False
    if os.getenv("CODE_SQUID_PROVIDER") is None:
        try:
            provider = build_provider(candidate.to_runtime_settings().provider)
            if not provider.is_ready():
                return current, f"{friendly_provider_name(provider_id)} is not connected."
            unavailable_model = current.model.name not in provider.list_models()
        except (OSError, RuntimeError, ValueError):
            return current, f"{friendly_provider_name(provider_id)} is not connected."
    write_provider(repo_root, provider_id)
    effective = load_settings(repo_root)
    if os.getenv("CODE_SQUID_PROVIDER") is not None:
        return effective, "Saved; CODE_SQUID_PROVIDER remains the effective override."
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

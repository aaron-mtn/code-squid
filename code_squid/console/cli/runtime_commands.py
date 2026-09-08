"""Interactive provider, model, and safety commands for Code Squid."""

import os
from pathlib import Path

from code_squid.console.ui.banner import FRIENDLY_APPROVAL_MODES
from code_squid.provider_setup import (
    PROVIDER_PROFILES,
    active_environment_overrides,
    friendly_provider_name,
    provider_ready,
    resolve_provider_name,
    select_model,
    select_provider,
    set_provider_key,
    set_provider_url,
)
from code_squid.settings import (
    Settings,
    load_settings,
    write_approval_mode,
    write_provider,
)


SAFETY_MODES = {
    "strict": "always",
    "balanced": "guarded",
    "yolo": "never",
}


def apply_provider(repo_root: Path, provider: str) -> Settings:
    """Persist a provider directly for compatibility with non-UI callers."""
    write_provider(repo_root, provider)
    return load_settings(repo_root)


def apply_model(repo_root: Path, model_name: str) -> Settings:
    """Persist a model and return the effective same-process settings."""
    return select_model(repo_root, model_name)


def apply_safety(repo_root: Path, friendly_mode: str) -> Settings:
    """Persist a friendly safety mode through the canonical approval mapping."""
    write_approval_mode(repo_root, SAFETY_MODES[friendly_mode])
    return load_settings(repo_root)


def handle_runtime_command(
    repo_root: Path,
    command: str,
    settings: Settings,
) -> tuple[bool, Settings]:
    """Handle one runtime settings command and return current effective settings."""

    parts = command.strip().split()
    if not parts or parts[0] not in {"/provider", "/model", "/safety"}:
        return False, settings

    if parts[0] == "/provider":
        _handle_provider(repo_root, parts[1:])
    elif parts[0] == "/model":
        _handle_model(repo_root, parts[1:])
    else:
        _handle_safety(repo_root, parts[1:])

    # Reloading keeps later runs current without adding mutable settings state
    # or a settings-manager lifecycle to this deliberately small CLI.
    return True, load_settings(repo_root)


def _handle_provider(repo_root: Path, args: list[str]) -> None:
    if not args:
        settings = load_settings(repo_root)
        status = "ready" if provider_ready(settings) else "not connected"
        print(f"Provider: {friendly_provider_name(settings.model.provider)} ({status})")
        print(
            "Providers: "
            + ", ".join(profile.friendly_name for profile in PROVIDER_PROFILES)
        )
        _print_environment_override("CODE_SQUID_PROVIDER", settings.model.provider)
        return

    action = args[0].lower()
    if action == "status" and len(args) == 1:
        _print_provider_status(load_settings(repo_root))
        return
    if action == "key" and len(args) == 2 and args[1]:
        set_provider_key(repo_root, args[1])
        print("Provider API key saved.")
        return
    if action == "url" and len(args) == 2 and args[1]:
        settings = set_provider_url(repo_root, args[1])
        print(f"Provider URL set to: {settings.model.base_url}")
        return
    if action == "use" and len(args) >= 2:
        requested = " ".join(args[1:])
    elif len(args) == 1:
        # Preserve the original shorthand while documenting `/provider use`.
        requested = args[0]
    else:
        print("Usage: /provider [use <name>|key <value>|url <value>|status]")
        return

    provider = resolve_provider_name(requested)
    if provider is None:
        print("Invalid provider. Valid options: " + ", ".join(
            profile.friendly_name for profile in PROVIDER_PROFILES
        ))
        return
    settings, explanation = select_provider(repo_root, provider)
    if explanation:
        print(explanation)
    if settings.model.provider == provider:
        print(f"Provider set to: {friendly_provider_name(provider)}")


def _handle_model(repo_root: Path, args: list[str]) -> None:
    if not args:
        settings = load_settings(repo_root)
        print(f"Current model: {settings.model.name}")
        _print_environment_override("CODE_SQUID_MODEL", settings.model.name)
        return

    if len(args) != 1:
        print("Usage: /model <name>")
        return

    model_name = args[0]
    effective_model = apply_model(repo_root, model_name).model.name
    if os.getenv("CODE_SQUID_MODEL") is not None:
        print(f"Saved model: {model_name}")
        print(
            "Effective model remains "
            f"{effective_model} because CODE_SQUID_MODEL overrides workspace settings."
        )
    else:
        print(f"Model set to: {effective_model}")


def _print_provider_status(settings: Settings) -> None:
    """Print effective provider setup without ever rendering a credential."""
    profile = next(
        profile for profile in PROVIDER_PROFILES
        if profile.provider_id == settings.model.provider
    )
    print(f"Provider: {profile.friendly_name}")
    print(f"Transport: {profile.transport}")
    print(f"Base URL: {settings.model.base_url or 'not set'}")
    print(f"API key set: {'yes' if settings.model.api_key else 'no'}")
    print(f"Readiness: {'ready' if provider_ready(settings) else 'not connected'}")
    print(f"Model: {settings.model.name}")
    overrides = active_environment_overrides()
    print(f"Environment overrides: {', '.join(overrides) if overrides else 'none'}")


def _handle_safety(repo_root: Path, args: list[str]) -> None:
    if not args:
        approval_mode = load_settings(repo_root).runtime.approval_mode
        print(f"Current safety mode: {FRIENDLY_APPROVAL_MODES[approval_mode]}")
        return

    if len(args) != 1 or args[0] not in SAFETY_MODES:
        print("Invalid safety mode. Valid options: strict, balanced, yolo")
        return

    friendly_mode = args[0]
    settings = apply_safety(repo_root, friendly_mode)
    approval_mode = settings.runtime.approval_mode
    print(f"Safety mode set to: {friendly_mode} (approval_mode={approval_mode})")


def _print_environment_override(variable: str, effective_value: str) -> None:
    if os.getenv(variable) is not None:
        print(f"Effective value is overridden by {variable}: {effective_value}")

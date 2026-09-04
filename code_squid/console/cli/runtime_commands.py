"""Interactive provider, model, and safety commands for Code Squid."""

import os
from pathlib import Path

from code_squid.console.ui.banner import FRIENDLY_APPROVAL_MODES
from code_squid.settings import (
    Settings,
    VALID_PROVIDERS,
    load_settings,
    write_approval_mode,
    write_model_name,
    write_provider,
)


SAFETY_MODES = {
    "strict": "always",
    "balanced": "guarded",
    "yolo": "never",
}


def apply_provider(repo_root: Path, provider: str) -> Settings:
    """Persist a provider and return the effective same-process settings."""
    write_provider(repo_root, provider)
    return load_settings(repo_root)


def apply_model(repo_root: Path, model_name: str) -> Settings:
    """Persist a model and return the effective same-process settings."""
    write_model_name(repo_root, model_name)
    return load_settings(repo_root)


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
        print(f"Current provider: {settings.model.provider}")
        print(f"Supported providers: {', '.join(sorted(VALID_PROVIDERS))}")
        _print_environment_override("CODE_SQUID_PROVIDER", settings.model.provider)
        return

    if len(args) != 1 or args[0] not in VALID_PROVIDERS:
        print(f"Invalid provider. Valid options: {', '.join(sorted(VALID_PROVIDERS))}")
        return

    provider = args[0]
    effective_provider = apply_provider(repo_root, provider).model.provider
    if os.getenv("CODE_SQUID_PROVIDER") is not None:
        print(f"Saved provider: {provider}")
        print(
            "Effective provider remains "
            f"{effective_provider} because CODE_SQUID_PROVIDER overrides workspace settings."
        )
    else:
        print(f"Provider set to: {effective_provider}")


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

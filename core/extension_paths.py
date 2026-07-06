# core/extension_paths.py

"""Central user extension storage paths for Code Squid."""

from __future__ import annotations

import os
from pathlib import Path


CODE_SQUID_HOME_ENV = "CODE_SQUID_HOME"


def code_squid_home() -> Path:
    """Return the user-level Code Squid home directory."""
    configured_home = os.environ.get(CODE_SQUID_HOME_ENV)
    if configured_home:
        return Path(configured_home).expanduser()
    return Path.home() / ".code-squid"


def user_skills_dir() -> Path:
    """Return the user-level skills directory without creating it."""
    return code_squid_home() / "skills"


def user_hooks_dir() -> Path:
    """Return the user-level hooks directory without creating it."""
    return code_squid_home() / "hooks"


def user_tools_dir() -> Path:
    """Return the user-level tools directory without creating it."""
    return code_squid_home() / "tools"


def user_extensions_dir() -> Path:
    """Return the user-level extensions directory without creating it."""
    return code_squid_home() / "extensions"


def extension_state_path() -> Path:
    """Return the user-level active extension state file path."""
    return code_squid_home() / "extension-state.json"


def ensure_user_extension_dirs() -> None:
    """Create the standard user extension directories."""
    for directory in (
        user_skills_dir(),
        user_hooks_dir(),
        user_tools_dir(),
        user_extensions_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)

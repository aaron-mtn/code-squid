"""Code Squid application-home resource paths.

The application chooses its home.  Resource loaders accept that home explicitly;
these helpers retain Code Squid's environment/default policy at the app boundary.
"""

from __future__ import annotations

import os
from pathlib import Path


CODE_SQUID_HOME_ENV = "CODE_SQUID_HOME"


def code_squid_home(app_home: Path | str | None = None) -> Path:
    """Return an explicit or configured Code Squid application home."""
    if app_home is not None:
        return Path(app_home).expanduser()

    configured_home = os.environ.get(CODE_SQUID_HOME_ENV)
    if configured_home:
        configured_home = os.path.expandvars(configured_home)
        if configured_home == "~" or configured_home.startswith(("~/", "~\\")):
            home = Path(os.environ.get("HOME", Path.home()))
            return home / configured_home[2:] if len(configured_home) > 1 else home
        return Path(configured_home).expanduser()
    return Path.home() / ".code-squid"


def user_skills_dir(app_home: Path | str | None = None) -> Path:
    return code_squid_home(app_home) / "skills"


def user_hooks_dir(app_home: Path | str | None = None) -> Path:
    return code_squid_home(app_home) / "hooks"


def user_tools_dir(app_home: Path | str | None = None) -> Path:
    return code_squid_home(app_home) / "tools"


def user_mods_dir(app_home: Path | str | None = None) -> Path:
    return code_squid_home(app_home) / "mods"


def ensure_user_resource_dirs(app_home: Path | str | None = None) -> None:
    """Create Code Squid's standard loose-resource and Mod directories."""
    for directory in (
        user_skills_dir(app_home),
        user_hooks_dir(app_home),
        user_tools_dir(app_home),
        user_mods_dir(app_home),
    ):
        directory.mkdir(parents=True, exist_ok=True)

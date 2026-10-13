"""Code Squid application-home resources and private workspace storage.

The application chooses its home.  Resource loaders accept that home explicitly;
these helpers retain Code Squid's environment/default policy at the app boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from squid_core.storage.atomic_json import atomic_write_json


CODE_SQUID_HOME_ENV = "CODE_SQUID_HOME"
CODE_SQUID_SESSION_INDEXES_ENV = "CODE_SQUID_SESSION_INDEXES"
RECENT_WORKSPACE_LIMIT = 10


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


def settings_path(app_home: Path | str | None = None) -> Path:
    """Return the application-wide Code Squid settings location."""
    return code_squid_home(app_home) / "settings.json"


def normalized_workspace_path(workspace_root: Path | str) -> str:
    """Return native absolute identity: Windows folds case; POSIX preserves it."""
    return os.path.normcase(str(Path(workspace_root).expanduser().resolve()))


def workspace_id(workspace_root: Path | str) -> str:
    """Return a readable basename plus eight hex digits of native path identity."""
    identity = normalized_workspace_path(workspace_root)
    # Derive both parts from the normalized path so Windows case aliases and
    # resolved relative/symlink paths cannot select different storage directories.
    basename = os.path.basename(identity)
    prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f\s]+', "-", basename).strip(" .-")
    # Bound UTF-8 bytes as well as Windows character counts. Reserve ample room
    # for the hash and storage children even when the basename is non-ASCII.
    prefix = prefix.encode("utf-8")[:80].decode("utf-8", errors="ignore").rstrip(" .-")
    prefix = prefix or "workspace"
    # Device names remain reserved with extensions (including COM/LPT superscript
    # digits). Check after truncation, which could itself produce a device name.
    stem = prefix.split(".", 1)[0].rstrip(" ").upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(
        r"(?:COM|LPT)[1-9¹²³]", stem,
    ):
        prefix = f"workspace-{prefix}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{digest}"


def workspace_state_dir(
    workspace_root: Path | str, app_home: Path | str | None = None,
) -> Path:
    """Prepare private workspace state, refusing missing or mismatched ownership.

    Discovery may create the manifest, but never creates sessions or undo. An
    existing unowned directory is never adopted, even when its hash looks right.
    A short-hash collision also fails closed against the full manifest identity;
    never retry with another name or reuse a different workspace's saved data.
    """
    home = code_squid_home(app_home).resolve()
    state = home / "workspaces" / workspace_id(workspace_root)
    if state.resolve() != state:
        raise ValueError(f"Workspace storage must not redirect through symlinks: {state}")
    manifest = state / "workspace.json"
    owner = normalized_workspace_path(workspace_root)
    try:
        state.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        try:
            if manifest.is_symlink():
                raise ValueError("Ownership manifest must not be a symlink")
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError(f"Invalid workspace ownership manifest: {manifest}") from error
        if (
            not isinstance(metadata, dict)
            or type(metadata.get("version")) is not int
            or metadata.get("version") != 1
            or metadata.get("workspace_root") != owner
        ):
            raise ValueError(f"Workspace storage belongs to a different workspace: {state}")
    else:
        # Publish complete ownership before any session/undo/log writer runs.
        atomic_write_json(manifest, {"version": 1, "workspace_root": owner})
    return state


def _workspace_data_path(
    workspace_root: Path | str, app_home: Path | str | None, *parts: str,
) -> Path:
    """Reject redirected storage children before readers or writers use them."""
    path = workspace_state_dir(workspace_root, app_home).joinpath(*parts)
    if path.resolve() != path:
        raise ValueError(f"Workspace storage must not redirect through symlinks: {path}")
    return path


def workspace_sessions_dir(
    workspace_root: Path | str, app_home: Path | str | None = None,
) -> Path:
    """Return the application-owned location for workspace sessions."""
    return _workspace_data_path(workspace_root, app_home, "sessions")


def workspace_undo_dir(
    workspace_root: Path | str, app_home: Path | str | None = None,
) -> Path:
    """Return the application-owned location for the latest undo buffer."""
    return _workspace_data_path(workspace_root, app_home, "undo")


def workspace_error_log_path(
    workspace_root: Path | str, app_home: Path | str | None = None,
) -> Path:
    """Return Code Squid's latest diagnostic error-log location."""
    return _workspace_data_path(workspace_root, app_home, "logs", "latest.log")


def session_indexes_path(app_home: Path | str | None = None) -> Path:
    """Return Code Squid's configured cross-workspace registry path."""
    configured_path = os.environ.get(CODE_SQUID_SESSION_INDEXES_ENV, "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    return code_squid_home(app_home) / "session-indexes.jsonl"


def recent_workspaces_path() -> Path:
    """Return the product-owned recent-workspace list location."""
    return code_squid_home() / "recent-workspaces.json"


def load_recent_workspaces(current: Path) -> list[Path]:
    """Return normalized paths newest first, always including ``current``."""
    current = current.resolve()
    paths = _read_recent_workspaces()
    if current not in paths:
        # Presence is more useful than retaining the oldest persisted entry;
        # opening the picker alone does not reorder global history.
        paths = paths[: RECENT_WORKSPACE_LIMIT - 1] + [current]
    return paths[:RECENT_WORKSPACE_LIMIT]


def _read_recent_workspaces() -> list[Path]:
    """Read and normalize the persisted list, ignoring malformed state."""
    try:
        raw = json.loads(recent_workspaces_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = []

    paths: list[Path] = []
    if isinstance(raw, list):
        for value in raw:
            if not isinstance(value, str):
                continue
            try:
                candidate = Path(value).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate not in paths:
                paths.append(candidate)
            if len(paths) == RECENT_WORKSPACE_LIMIT:
                break
    return paths


def remember_workspace(workspace: Path) -> None:
    """Move a workspace to the front of the bounded global recent list."""
    workspace = workspace.resolve()
    recent = [workspace]
    recent.extend(path for path in _read_recent_workspaces() if path != workspace)
    recent = recent[:RECENT_WORKSPACE_LIMIT]
    path = recent_workspaces_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([str(item) for item in recent], indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        # Recent history is convenience state and must never block switching.
        return


def ensure_user_resource_dirs(app_home: Path | str | None = None) -> None:
    """Create Code Squid's standard loose-resource and Mod directories."""
    for directory in (
        user_skills_dir(app_home),
        user_hooks_dir(app_home),
        user_tools_dir(app_home),
        user_mods_dir(app_home),
    ):
        directory.mkdir(parents=True, exist_ok=True)

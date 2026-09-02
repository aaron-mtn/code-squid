"""Code Squid cross-workspace session registration and discovery policy."""

import json
from pathlib import Path

from core.app_paths import session_indexes_path, workspace_sessions_dir
from squid_core.storage.session_index import (
    latest_session_id as _latest_session_id,
    list_sessions as _list_sessions,
    load_session_entries as _load_session_entries,
    session_dir_for as _session_dir_for,
)


# Remember a workspace index without moving session data out of the workspace.
def register_session_index(repo_root: Path) -> None:
    index_path = session_indexes_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_root = str(repo_root.resolve())

    known_roots = _registered_repo_roots(index_path) if index_path.exists() else []
    if resolved_root in known_roots:
        return

    with index_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps({"repo_root": resolved_root}) + "\n")


# Return the folder that contains all saved session directories.
def sessions_dir(repo_root: Path) -> Path:
    return workspace_sessions_dir(repo_root)


# Load session metadata files, newest first.
#
# Broken or hand-edited folders are skipped so one bad session does not make
# the whole viewer unusable.
def list_sessions(repo_root: Path) -> list[dict]:
    return _list_sessions(sessions_dir(repo_root))


# Load sessions across every workspace index registered by Code Squid.
#
# Workspace-local storage remains the source of truth. A missing, moved, or
# unreadable workspace is skipped so one stale registry entry cannot break the
# global session viewer.
def list_all_sessions() -> list[dict]:
    index_path = session_indexes_path()
    if not index_path.exists():
        return []

    sessions = []
    for repo_root in _registered_repo_roots(index_path):
        try:
            for metadata in list_sessions(Path(repo_root)):
                normalized = dict(metadata)
                if not normalized.get("repo_root"):
                    normalized["repo_root"] = repo_root
                sessions.append(normalized)
        except OSError:
            continue

    return sorted(
        sessions,
        key=lambda item: item.get("updated_at", ""),
        reverse=True,
    )


# Return the newest session ID, or None when no sessions have metadata.
def latest_session_id(repo_root: Path) -> str | None:
    return _latest_session_id(sessions_dir(repo_root))


# Return the path for one exact session ID.
def session_dir_for(repo_root: Path, session_id: str) -> Path:
    return _session_dir_for(sessions_dir(repo_root), session_id)


# Load raw transcript entries from a saved session.
def load_session_entries(repo_root: Path, session_id: str) -> list[dict]:
    return _load_session_entries(sessions_dir(repo_root), session_id)


def _registered_repo_roots(index_path: Path) -> list[str]:
    roots = []
    seen = set()

    with index_path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            repo_root = entry.get("repo_root") if isinstance(entry, dict) else None
            if not isinstance(repo_root, str) or not repo_root or repo_root in seen:
                continue
            seen.add(repo_root)
            roots.append(repo_root)

    return roots

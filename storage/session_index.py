"""Reads Code Squid session folders without owning agent behavior."""

import json
import os
import re
from pathlib import Path
from typing import Any


# Return the small global registry that points at workspace-local session indexes.
def session_indexes_path() -> Path:
    configured_path = os.environ.get("CODE_SQUID_SESSION_INDEXES", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    return Path.home() / ".code-squid" / "session-indexes.jsonl"


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
    return repo_root / ".code-squid" / "sessions"


# Load session metadata files, newest first.
#
# Broken or hand-edited folders are skipped so one bad session does not make
# the whole viewer unusable.
def list_sessions(repo_root: Path) -> list[dict]:
    root = sessions_dir(repo_root)
    if not root.exists():
        return []

    sessions = []
    for session_dir in root.iterdir():
        if not session_dir.is_dir():
            continue

        metadata_path = session_dir / "metadata.json"
        if not metadata_path.exists():
            continue

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if isinstance(metadata, dict):
            sessions.append(metadata)

    return sorted(sessions, key=_updated_at, reverse=True)


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

    return sorted(sessions, key=_updated_at, reverse=True)


# Return the newest session ID, or None when no sessions have metadata.
def latest_session_id(repo_root: Path) -> str | None:
    sessions = list_sessions(repo_root)
    if not sessions:
        return None

    return sessions[0].get("session_id")


# Return the path for one exact session ID.
def session_dir_for(repo_root: Path, session_id: str) -> Path:
    if not isinstance(session_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]*",
        session_id,
    ):
        raise ValueError(f"Invalid session ID: {session_id!r}")

    root = sessions_dir(repo_root)
    resolved_root = root.resolve()
    path = root / session_id
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"Session path escapes sessions directory: {session_id!r}")

    if not path.is_dir():
        raise FileNotFoundError(f"Session not found: {session_id}")

    return path


# Load raw transcript entries from a saved session.
def load_session_entries(repo_root: Path, session_id: str) -> list[dict]:
    jsonl_path = session_dir_for(repo_root, session_id) / "session.jsonl"
    entries = []

    with jsonl_path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            entries.append(json.loads(line))

    return entries


def _updated_at(metadata: dict[str, Any]) -> str:
    updated_at = metadata.get("updated_at")
    if isinstance(updated_at, str):
        return updated_at

    return ""


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

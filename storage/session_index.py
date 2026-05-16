"""Reads Code Squid session folders without owning agent behavior."""

import json
from pathlib import Path
from typing import Any


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


# Return the newest session ID, or None when no sessions have metadata.
def latest_session_id(repo_root: Path) -> str | None:
    sessions = list_sessions(repo_root)
    if not sessions:
        return None

    return sessions[0].get("session_id")


# Return the path for one exact session ID.
def session_dir_for(repo_root: Path, session_id: str) -> Path:
    path = sessions_dir(repo_root) / session_id
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

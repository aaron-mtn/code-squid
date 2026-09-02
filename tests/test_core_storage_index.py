"""Tests for generic Squid Core session-directory inspection."""

import json
from pathlib import Path

from squid_core.storage.session_index import (
    latest_session_id,
    list_sessions,
    load_session_entries,
    session_dir_for,
)


def _write_session(sessions_dir: Path, session_id: str, updated_at: str) -> Path:
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps({"session_id": session_id, "updated_at": updated_at}),
        encoding="utf-8",
    )
    (session_dir / "session.jsonl").write_text(
        json.dumps({"id": "e_000001", "type": "message"}) + "\n",
        encoding="utf-8",
    )
    return session_dir


def test_helpers_inspect_an_explicit_sessions_directory(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "host-selected-sessions"
    _write_session(sessions_dir, "older", "2026-01-01T00:00:00+00:00")
    newest = _write_session(sessions_dir, "newer", "2026-01-02T00:00:00+00:00")

    assert [item["session_id"] for item in list_sessions(sessions_dir)] == [
        "newer",
        "older",
    ]
    assert latest_session_id(sessions_dir) == "newer"
    assert session_dir_for(sessions_dir, "newer") == newest
    assert load_session_entries(sessions_dir, "newer") == [
        {"id": "e_000001", "type": "message"}
    ]

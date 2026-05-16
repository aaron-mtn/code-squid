"""Tests for reading saved Code Squid session folders."""

import json
from pathlib import Path

import pytest

from storage.session_index import (
    latest_session_id,
    list_sessions,
    load_session_entries,
    session_dir_for,
    sessions_dir,
)


def write_session(repo_root: Path, session_id: str, metadata: dict) -> Path:
    session_dir = sessions_dir(repo_root) / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    (session_dir / "session.jsonl").write_text("", encoding="utf-8")
    return session_dir


def test_list_sessions_returns_metadata_sorted_by_updated_at_descending(tmp_path: Path) -> None:
    write_session(
        tmp_path,
        "older",
        {
            "session_id": "older",
            "updated_at": "2026-05-14T15:00:00+00:00",
        },
    )
    write_session(
        tmp_path,
        "newer",
        {
            "session_id": "newer",
            "updated_at": "2026-05-14T16:00:00+00:00",
        },
    )

    assert [session["session_id"] for session in list_sessions(tmp_path)] == ["newer", "older"]


def test_list_sessions_skips_invalid_and_missing_metadata_folders(tmp_path: Path) -> None:
    valid = {
        "session_id": "valid",
        "updated_at": "2026-05-14T16:00:00+00:00",
    }
    write_session(tmp_path, "valid", valid)

    missing_metadata = sessions_dir(tmp_path) / "missing-metadata"
    missing_metadata.mkdir(parents=True)

    invalid_metadata = sessions_dir(tmp_path) / "invalid-metadata"
    invalid_metadata.mkdir(parents=True)
    (invalid_metadata / "metadata.json").write_text("{broken", encoding="utf-8")

    assert list_sessions(tmp_path) == [valid]


def test_latest_session_id_returns_newest_session_id(tmp_path: Path) -> None:
    write_session(
        tmp_path,
        "older",
        {
            "session_id": "older",
            "updated_at": "2026-05-14T15:00:00+00:00",
        },
    )
    write_session(
        tmp_path,
        "newer",
        {
            "session_id": "newer",
            "updated_at": "2026-05-14T16:00:00+00:00",
        },
    )

    assert latest_session_id(tmp_path) == "newer"


def test_latest_session_id_returns_none_when_no_sessions_exist(tmp_path: Path) -> None:
    assert latest_session_id(tmp_path) is None


def test_session_dir_for_returns_exact_session_dir(tmp_path: Path) -> None:
    expected = write_session(
        tmp_path,
        "exact-id",
        {
            "session_id": "exact-id",
            "updated_at": "2026-05-14T16:00:00+00:00",
        },
    )
    write_session(
        tmp_path,
        "exact-id-suffix",
        {
            "session_id": "exact-id-suffix",
            "updated_at": "2026-05-14T17:00:00+00:00",
        },
    )

    assert session_dir_for(tmp_path, "exact-id") == expected


def test_session_dir_for_raises_file_not_found_error_for_missing_id(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        session_dir_for(tmp_path, "missing")


def test_load_session_entries_returns_entries_in_order_and_skips_blank_lines(
    tmp_path: Path,
) -> None:
    session_dir = write_session(
        tmp_path,
        "session",
        {
            "session_id": "session",
            "updated_at": "2026-05-14T16:00:00+00:00",
        },
    )
    first = {"id": "e_000001", "type": "message", "message": {"role": "user"}}
    second = {"id": "e_000002", "type": "message", "message": {"role": "assistant"}}
    (session_dir / "session.jsonl").write_text(
        f"{json.dumps(first)}\n\n{json.dumps(second)}\n",
        encoding="utf-8",
    )

    assert load_session_entries(tmp_path, "session") == [first, second]

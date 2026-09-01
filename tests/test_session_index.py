"""Tests for reading saved Code Squid session folders."""

import json
from pathlib import Path

import pytest

from storage.session_index import (
    latest_session_id,
    list_all_sessions,
    list_sessions,
    load_session_entries,
    register_session_index,
    session_dir_for,
    session_indexes_path,
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


def test_session_registry_uses_configured_override(
    isolated_session_indexes: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    register_session_index(tmp_path)

    assert session_indexes_path() == isolated_session_indexes
    registered = [
        json.loads(line)
        for line in isolated_session_indexes.read_text(
            encoding="utf-8",
        ).splitlines()
        if line.strip()
    ]
    assert {"repo_root": str(tmp_path.resolve())} in registered
    assert not (fake_home / ".code-squid" / "session-indexes.jsonl").exists()


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


def test_list_all_sessions_returns_registered_workspaces_newest_first(
    monkeypatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "global" / "session-indexes.jsonl"
    monkeypatch.setenv("CODE_SQUID_SESSION_INDEXES", str(index_path))
    older_workspace = tmp_path / "older-workspace"
    newer_workspace = tmp_path / "newer-workspace"
    write_session(
        older_workspace,
        "older",
        {
            "session_id": "older",
            "repo_root": str(older_workspace),
            "updated_at": "2026-05-14T15:00:00+00:00",
        },
    )
    write_session(
        newer_workspace,
        "newer",
        {
            "session_id": "newer",
            "repo_root": str(newer_workspace),
            "updated_at": "2026-05-14T16:00:00+00:00",
        },
    )
    register_session_index(older_workspace)
    register_session_index(newer_workspace)

    assert [session["session_id"] for session in list_all_sessions()] == [
        "newer",
        "older",
    ]


def test_list_all_sessions_skips_bad_registered_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "session-indexes.jsonl"
    monkeypatch.setenv("CODE_SQUID_SESSION_INDEXES", str(index_path))
    valid_workspace = tmp_path / "valid"
    broken_workspace = tmp_path / "broken"
    write_session(
        valid_workspace,
        "valid",
        {
            "session_id": "valid",
            "repo_root": str(valid_workspace),
            "updated_at": "2026-05-14T16:00:00+00:00",
        },
    )
    register_session_index(valid_workspace)
    register_session_index(broken_workspace)
    sessions_dir(broken_workspace).mkdir(parents=True)

    original_iterdir = Path.iterdir

    def fail_for_broken(path):
        if path == sessions_dir(broken_workspace):
            raise OSError("unreadable workspace")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_for_broken)

    assert [session["session_id"] for session in list_all_sessions()] == ["valid"]


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


@pytest.mark.parametrize(
    "session_id",
    ["../x", "..\\x", "/tmp/x", "nested/session", "nested\\session", ".."],
)
def test_session_dir_for_rejects_path_like_ids(
    tmp_path: Path,
    session_id: str,
) -> None:
    with pytest.raises(ValueError, match="Invalid session ID"):
        session_dir_for(tmp_path, session_id)


def test_session_dir_for_rejects_windows_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid session ID"):
        session_dir_for(tmp_path, r"C:\outside\session")


def test_session_dir_for_rejects_symlink_that_resolves_outside_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = sessions_dir(tmp_path)
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "linked-session"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        resolved_outside = outside.resolve()
        original_resolve = Path.resolve

        def resolve_link_outside(path: Path, *args, **kwargs) -> Path:
            if path == link:
                return resolved_outside
            return original_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve_link_outside)

    with pytest.raises(ValueError, match="escapes sessions directory"):
        session_dir_for(tmp_path, "linked-session")


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

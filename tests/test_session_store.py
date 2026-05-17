import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from storage.session_store import SessionStore


def read_metadata(store: SessionStore) -> dict:
    return json.loads(store.metadata_path.read_text(encoding="utf-8"))


def read_entries(store: SessionStore) -> list[dict]:
    return [
        json.loads(line)
        for line in store.jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_create_writes_initial_metadata_and_empty_jsonl(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "Fix Formatter Underscore Bug")
    metadata = read_metadata(store)

    assert store.metadata_path.exists()
    assert store.jsonl_path.exists()
    assert store.jsonl_path.read_text(encoding="utf-8") == ""
    assert metadata["status"] == "active"
    assert metadata["task"] == "Fix Formatter Underscore Bug"
    assert metadata["repo_root"] == str(tmp_path.resolve())
    assert metadata["session_id"]
    assert metadata["active_leaf_id"] is None


def test_session_id_uses_sortable_24_hour_timestamp_and_task_slug(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "Fix Formatter Underscore Bug")
    metadata = read_metadata(store)

    assert re.fullmatch(
        r"\d{8}-\d{6}-fix-formatter-underscore-bug",
        metadata["session_id"],
    )


def test_session_id_property_returns_metadata_session_id(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "property")

    assert store.session_id == read_metadata(store)["session_id"]


def test_append_message_writes_jsonl_entries_and_updates_active_leaf(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "append messages")

    first = store.append_message({"role": "user", "content": "hello"})
    second = store.append_message(
        {"role": "assistant", "content": "hi"},
        usage={"input_tokens": 3, "output_tokens": 2},
    )
    entries = read_entries(store)
    metadata = read_metadata(store)

    assert first == entries[0]
    assert second == entries[1]
    assert entries[0]["id"] == "e_000001"
    assert entries[1]["id"] == "e_000002"
    assert entries[0]["parent_id"] is None
    assert entries[1]["parent_id"] == "e_000001"
    assert metadata["active_leaf_id"] == "e_000002"
    assert entries[0]["usage"] is None
    assert entries[1]["usage"] == {"input_tokens": 3, "output_tokens": 2}


def test_load_messages_returns_message_dicts_in_order(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "load messages")
    messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
    ]

    for message in messages:
        store.append_message(message)

    assert store.load_messages() == messages


def test_open_returns_store_for_existing_session(tmp_path: Path) -> None:
    created = SessionStore.create(tmp_path, "open existing")

    opened = SessionStore.open(created.session_dir)

    assert opened.session_dir == created.session_dir
    assert opened.metadata_path == created.metadata_path
    assert opened.jsonl_path == created.jsonl_path
    assert read_metadata(opened) == read_metadata(created)


def test_open_raises_file_not_found_error_for_missing_session_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        SessionStore.open(tmp_path / "missing")

    missing_jsonl = tmp_path / "missing-jsonl"
    missing_jsonl.mkdir()
    (missing_jsonl / "metadata.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        SessionStore.open(missing_jsonl)

    missing_metadata = tmp_path / "missing-metadata"
    missing_metadata.mkdir()
    (missing_metadata / "session.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        SessionStore.open(missing_metadata)


def test_update_status_accepts_known_terminal_statuses(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "status")

    for status in ["complete", "failed", "abandoned", "interrupted"]:
        store.update_status(status)
        assert read_metadata(store)["status"] == status


def test_update_status_rejects_unknown_status(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "status")

    with pytest.raises(ValueError):
        store.update_status("paused")


def test_duplicate_session_id_gets_suffix_instead_of_overwriting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import storage.session_store as session_store

    class FixedDatetime:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 5, 14, 15, 30, 12, tzinfo=tz)

    monkeypatch.setattr(session_store, "datetime", FixedDatetime)

    first = SessionStore.create(tmp_path, "Fix Formatter Underscore Bug")
    second = SessionStore.create(tmp_path, "Fix Formatter Underscore Bug")

    assert first.session_dir.exists()
    assert second.session_dir.exists()
    assert first.session_dir != second.session_dir
    assert read_metadata(first)["session_id"] == "20260514-153012-fix-formatter-underscore-bug"
    assert re.fullmatch(
        r"20260514-153012-fix-formatter-underscore-bug-[0-9a-f]{4}",
        read_metadata(second)["session_id"],
    )

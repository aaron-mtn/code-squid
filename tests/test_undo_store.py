"""Tests for the latest-only undo buffer."""

import json
from pathlib import Path

import pytest

from storage.undo_store import UndoStore


def read_metadata(store: UndoStore) -> dict:
    return json.loads(store.metadata_path.read_text(encoding="utf-8"))


def test_create_creates_metadata_index_and_files_folder(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path, session_id="session-1")
    metadata = read_metadata(store)

    assert store.undo_dir == tmp_path / ".code-squid" / "undo"
    assert store.metadata_path.is_file()
    assert store.index_path.is_file()
    assert store.files_dir.is_dir()
    assert json.loads(store.index_path.read_text(encoding="utf-8")) == []
    assert metadata["repo_root"] == str(tmp_path.resolve())
    assert metadata["session_id"] == "session-1"
    assert metadata["status"] == "active"
    assert metadata["created_at"]
    assert metadata["updated_at"]


def test_create_replaces_previous_undo_folder(tmp_path: Path) -> None:
    first = UndoStore.create(tmp_path)
    leftover = first.files_dir / "000001"
    leftover.write_bytes(b"old")

    second = UndoStore.create(tmp_path)

    assert second.undo_dir == first.undo_dir
    assert not leftover.exists()
    assert second.load_index() == []


def test_open_opens_existing_undo_folder(tmp_path: Path) -> None:
    created = UndoStore.create(tmp_path)

    opened = UndoStore.open(tmp_path)

    assert opened.undo_dir == created.undo_dir
    assert opened.metadata_path == created.metadata_path
    assert opened.index_path == created.index_path
    assert opened.files_dir == created.files_dir


def test_open_raises_file_not_found_error_when_required_files_are_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        UndoStore.open(tmp_path)

    missing_index = UndoStore.create(tmp_path)
    missing_index.index_path.unlink()

    with pytest.raises(FileNotFoundError):
        UndoStore.open(tmp_path)

    missing_metadata = UndoStore.create(tmp_path)
    missing_metadata.metadata_path.unlink()

    with pytest.raises(FileNotFoundError):
        UndoStore.open(tmp_path)

    missing_files = UndoStore.create(tmp_path)
    missing_files.files_dir.rmdir()

    with pytest.raises(FileNotFoundError):
        UndoStore.open(tmp_path)


def test_snapshot_file_rejects_relative_paths(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)

    with pytest.raises(ValueError):
        store.snapshot_file("relative.py")


def test_snapshot_file_snapshots_existing_file_bytes(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)
    target = tmp_path / "target.bin"
    target.write_bytes(b"\x00original\xff")

    record = store.snapshot_file(str(target))

    assert record == {
        "path": str(target),
        "existed": True,
        "snapshot_path": "files/000001",
    }
    assert (store.files_dir / "000001").read_bytes() == b"\x00original\xff"
    assert store.load_index() == [record]


def test_snapshot_file_records_missing_files_with_existed_false(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)
    target = tmp_path / "new-file.py"

    record = store.snapshot_file(str(target))

    assert record == {
        "path": str(target),
        "existed": False,
        "snapshot_path": None,
    }
    assert store.load_index() == [record]
    assert list(store.files_dir.iterdir()) == []


def test_snapshot_file_does_not_duplicate_snapshot_for_same_path(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)
    target = tmp_path / "target.py"
    target.write_bytes(b"first")

    first = store.snapshot_file(str(target))
    target.write_bytes(b"second")
    second = store.snapshot_file(str(target))

    assert second == first
    assert store.load_index() == [first]
    assert (store.files_dir / "000001").read_bytes() == b"first"
    assert not (store.files_dir / "000002").exists()


def test_load_index_returns_records(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)
    target = tmp_path / "target.py"
    target.write_text("content", encoding="utf-8")
    record = store.snapshot_file(str(target))

    assert store.load_index() == [record]


def test_restore_restores_original_bytes_for_existing_files(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)
    target = tmp_path / "target.bin"
    target.write_bytes(b"before")
    store.snapshot_file(str(target))
    target.write_bytes(b"after")

    results = store.restore()

    assert target.read_bytes() == b"before"
    assert results == [
        {
            "path": str(target),
            "restored": True,
            "deleted": False,
        }
    ]


def test_restore_deletes_files_that_did_not_exist_before_snapshot(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)
    target = tmp_path / "new-file.py"
    store.snapshot_file(str(target))
    target.write_text("created later", encoding="utf-8")

    results = store.restore()

    assert not target.exists()
    assert results == [
        {
            "path": str(target),
            "restored": False,
            "deleted": True,
        }
    ]


def test_restore_updates_metadata_status_to_restored(tmp_path: Path) -> None:
    store = UndoStore.create(tmp_path)
    before = read_metadata(store)["updated_at"]

    store.restore()
    metadata = read_metadata(store)

    assert metadata["status"] == "restored"
    assert metadata["updated_at"] >= before

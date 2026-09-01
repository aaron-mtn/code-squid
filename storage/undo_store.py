# storage/undo_store.py

"""Stores the latest Code Squid undo buffer on disk."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.atomic_json import atomic_write_json


class UndoStore:
    """Persists one latest-only undo buffer."""

    # The undo folder is intentionally fixed:
    #
    #   <repo_root>/.code-squid/undo/
    #
    # Creating a new store replaces whatever was there before.
    def __init__(self, undo_dir: Path) -> None:
        self.undo_dir = undo_dir
        self.metadata_path = undo_dir / "metadata.json"
        self.index_path = undo_dir / "index.json"
        self.files_dir = undo_dir / "files"

    @classmethod
    def create(cls, repo_root: Path, session_id: str | None = None) -> "UndoStore":
        repo_root = repo_root.resolve()
        undo_dir = repo_root / ".code-squid" / "undo"

        if undo_dir.exists():
            shutil.rmtree(undo_dir)

        files_dir = undo_dir / "files"
        files_dir.mkdir(parents=True)

        now = _utc_now()
        store = cls(undo_dir)
        store._write_metadata(
            {
                "created_at": now,
                "updated_at": now,
                "repo_root": str(repo_root),
                "session_id": session_id,
                "status": "active",
            }
        )
        store._write_index([])
        return store

    @classmethod
    def open(cls, repo_root: Path) -> "UndoStore":
        undo_dir = repo_root.resolve() / ".code-squid" / "undo"
        store = cls(undo_dir)

        if not store.metadata_path.is_file():
            raise FileNotFoundError(f"Missing undo metadata: {store.metadata_path}")

        if not store.index_path.is_file():
            raise FileNotFoundError(f"Missing undo index: {store.index_path}")

        if not store.files_dir.is_dir():
            raise FileNotFoundError(f"Missing undo files folder: {store.files_dir}")

        return store

    # Capture the file's current bytes once.
    #
    # Repeated calls for the same path return the original record so one undo
    # buffer keeps the first pre-change state for each file.
    def snapshot_file(self, path: str) -> dict:
        original_path = Path(path)
        if not original_path.is_absolute():
            raise ValueError(f"Undo snapshots require an absolute path: {path}")

        index = self.load_index()
        for record in index:
            if record.get("path") == path:
                return record

        if original_path.exists():
            snapshot_name = f"{len(index) + 1:06d}"
            snapshot_path = self.files_dir / snapshot_name
            shutil.copyfile(original_path, snapshot_path)
            record = {
                "path": path,
                "existed": True,
                "snapshot_path": f"files/{snapshot_name}",
            }
        else:
            record = {
                "path": path,
                "existed": False,
                "snapshot_path": None,
            }

        index.append(record)
        self._write_index(index)
        self._touch_metadata()
        return record

    def load_index(self) -> list[dict]:
        with self.index_path.open(encoding="utf-8") as file:
            return json.load(file)

    def has_snapshot(self, path: str) -> bool:
        return any(record.get("path") == path for record in self.load_index())

    def discard_snapshot(self, path: str) -> bool:
        index = self.load_index()

        for position, record in enumerate(index):
            if record.get("path") != path:
                continue

            snapshot_path = record.get("snapshot_path")
            if snapshot_path is not None:
                (self.undo_dir / snapshot_path).unlink(missing_ok=True)

            index.pop(position)
            self._write_index(index)
            self._touch_metadata()
            return True

        return False

    def discard_snapshot_if_unchanged(self, path: str) -> bool:
        record = next(
            (record for record in self.load_index() if record.get("path") == path),
            None,
        )
        if record is None:
            return False

        original_path = Path(path)
        if record["existed"]:
            try:
                snapshot_path = self.undo_dir / record["snapshot_path"]
                unchanged = original_path.read_bytes() == snapshot_path.read_bytes()
            except OSError:
                return False
        else:
            unchanged = not original_path.exists()

        if not unchanged:
            return False
        return self.discard_snapshot(path)

    def restore(self) -> list[dict]:
        results = []

        for record in self.load_index():
            original_path = Path(record["path"])
            result = {
                "path": record["path"],
                "restored": False,
                "deleted": False,
            }

            if record["existed"]:
                snapshot_path = self.undo_dir / record["snapshot_path"]
                original_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(snapshot_path, original_path)
                result["restored"] = True
            elif original_path.exists():
                original_path.unlink()
                result["deleted"] = True

            results.append(result)

        metadata = self._read_metadata()
        metadata["status"] = "restored"
        metadata["updated_at"] = _utc_now()
        self._write_metadata(metadata)
        return results

    def _read_metadata(self) -> dict[str, Any]:
        with self.metadata_path.open(encoding="utf-8") as file:
            return json.load(file)

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        atomic_write_json(self.metadata_path, metadata)

    def _write_index(self, index: list[dict]) -> None:
        atomic_write_json(self.index_path, index)

    def _touch_metadata(self) -> None:
        metadata = self._read_metadata()
        metadata["updated_at"] = _utc_now()
        self._write_metadata(metadata)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

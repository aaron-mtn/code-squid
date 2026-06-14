# storage/session_store.py

"""Owns disk persistence for one Code Squid session; must not own agent policy, loop control, or in-memory session behavior."""

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.session_index import register_session_index


# Status values allowed in metadata.json.
# Keep this list small until the app has real UX that needs more states.
ALLOWED_STATUSES = {"active", "complete", "failed", "abandoned", "interrupted"}


class SessionStore:
    """Persists one Code Squid session to disk."""

    # Store the paths for one session folder.
    #
    # A session folder currently contains:
    # - metadata.json: run-level facts like status, task, and active leaf
    # - session.jsonl: append-only transcript entries
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.metadata_path = session_dir / "metadata.json"
        self.jsonl_path = session_dir / "session.jsonl"

    # Create a brand-new session store under:
    #
    #   <repo_root>/.code-squid/sessions/<session_id>/
    #
    # This only creates storage files. It does not modify core/session.py,
    # start the agent loop, or load prior messages.
    @classmethod
    def create(cls, repo_root: Path, task: str) -> "SessionStore":
        # Resolve the repo root once so metadata gets a stable absolute path.
        repo_root = repo_root.resolve()

        # Keep Code Squid's local state inside the repo/workspace.
        sessions_dir = repo_root / ".code-squid" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Session IDs are human-readable so users can browse folders without
        # decoding UUID soup.
        session_id = _unique_session_id(sessions_dir, task)
        session_dir = sessions_dir / session_id
        session_dir.mkdir()

        # Store machine-friendly timestamp truth in metadata.
        # Later CLI rendering can decide whether to show 12-hour display time.
        now = _utc_now()
        metadata = {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "repo_root": str(repo_root),
            "task": task,
            "status": "active",
            "active_leaf_id": None,
        }

        # Write the initial metadata and create an empty JSONL transcript.
        store = cls(session_dir)
        store._write_metadata(metadata)
        store.jsonl_path.write_text("", encoding="utf-8")
        try:
            register_session_index(repo_root)
        except Exception:
            # Global discovery is supplementary. A local session must still be
            # usable when the home-level registry cannot be written.
            pass
        return store

    # Open an existing session folder without creating or modifying files.
    @classmethod
    def open(cls, session_dir: Path) -> "SessionStore":
        store = cls(session_dir)

        if not store.metadata_path.is_file():
            raise FileNotFoundError(f"Missing session metadata: {store.metadata_path}")

        if not store.jsonl_path.is_file():
            raise FileNotFoundError(f"Missing session transcript: {store.jsonl_path}")

        return store

    # Append one transcript message as a JSONL entry.
    #
    # The optional usage field is reserved for future token/cost tracking.
    # For now most entries will store usage as None.
    def append_message(self, message: dict, usage: dict | None = None) -> dict:
        # Read metadata so the new entry can link to the previous active leaf.
        metadata = self._read_metadata()
        previous_leaf_id = metadata["active_leaf_id"]

        # Entry IDs are intentionally boring and linear for v1.
        # Branching can use the parent_id chain later, but today it is just
        # a simple linked list through the transcript.
        entry_id = f"e_{self._next_entry_number():06d}"
        entry = {
            "id": entry_id,
            "parent_id": previous_leaf_id,
            "type": "message",
            "timestamp": _utc_now(),
            "message": message,
            "usage": usage,
        }

        # JSONL keeps appends simple and avoids rewriting the whole transcript.
        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")

        # Move the active leaf to the newly appended entry.
        metadata["active_leaf_id"] = entry_id
        metadata["updated_at"] = _utc_now()
        self._write_metadata(metadata)

        return entry

    # Append one compaction event as a JSONL entry.
    def append_compaction(self, metadata: dict) -> dict:
        session_metadata = self._read_metadata()
        previous_leaf_id = session_metadata["active_leaf_id"]

        entry_id = f"e_{self._next_entry_number():06d}"
        entry = {
            "id": entry_id,
            "parent_id": previous_leaf_id,
            "type": "compaction",
            "timestamp": _utc_now(),
            "metadata": metadata,
        }

        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")

        session_metadata["active_leaf_id"] = entry_id
        session_metadata["updated_at"] = _utc_now()
        self._write_metadata(session_metadata)

        return entry

    # Load transcript messages from session.jsonl in order.
    #
    # This returns only the message dicts because core/session.py expects an
    # in-memory list of provider-style transcript messages.
    def load_messages(self) -> list[dict]:
        messages = []

        with self.jsonl_path.open(encoding="utf-8") as file:
            for line in file:
                # Ignore blank lines so hand-edited files do not immediately
                # explode on harmless whitespace.
                if not line.strip():
                    continue

                entry = json.loads(line)
                if entry.get("type") == "message":
                    messages.append(entry["message"])

        return messages

    # Update the run-level session status in metadata.json.
    #
    # This is intentionally strict so typos do not silently create new states.
    def update_status(self, status: str) -> None:
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"Unknown session status: {status}")

        metadata = self._read_metadata()
        metadata["status"] = status
        metadata["updated_at"] = _utc_now()
        self._write_metadata(metadata)

    @property
    def session_id(self) -> str:
        return self._read_metadata()["session_id"]

    # Return the next linear entry number for session.jsonl.
    #
    # This scans the JSONL file for now because it is simple and reliable.
    # If sessions get huge later, metadata can grow a next_entry_number field.
    def _next_entry_number(self) -> int:
        count = 0

        with self.jsonl_path.open(encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    count += 1

        return count + 1

    # Read metadata.json as a dictionary.
    def _read_metadata(self) -> dict[str, Any]:
        with self.metadata_path.open(encoding="utf-8") as file:
            return json.load(file)

    # Write metadata.json in a stable, readable format.
    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        with self.metadata_path.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)
            file.write("\n")


# Build a unique, human-readable session ID.
#
# Format:
#   YYYYMMDD-HHMMSS-<task-slug>
#
# If two sessions start in the same second with the same task slug, append a
# short random suffix instead of overwriting the existing folder.
def _unique_session_id(sessions_dir: Path, task: str) -> str:
    base_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_slugify(task)}"
    session_id = base_id

    while (sessions_dir / session_id).exists():
        session_id = f"{base_id}-{secrets.token_hex(2)}"

    return session_id


# Convert the task text into a filesystem-friendly slug.
#
# Examples:
#   "Fix Formatter Underscore Bug" -> "fix-formatter-underscore-bug"
#   "!!!" -> "session"
def _slugify(task: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")

    if not slug:
        return "session"

    # Cap long tasks so session folder names stay readable.
    return slug[:50].strip("-") or "session"


# Return a timezone-aware UTC timestamp for durable metadata.
#
# User-facing display can later render this however it wants.
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

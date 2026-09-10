"""Own disk persistence mechanics for one Squid Core session."""

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from squid_core.storage.atomic_json import atomic_write_json


# Status values allowed in metadata.json.
# Keep this list small until the app has real UX that needs more states.
ALLOWED_STATUSES = {"active", "complete", "failed", "abandoned", "interrupted"}


class SessionStore:
    """Persist one Squid Core session to an explicitly supplied directory."""

    # Store the paths for one session folder.
    #
    # A session folder currently contains:
    # - metadata.json: run-level facts like status, task, and active leaf
    # - session.jsonl: append-only transcript entries
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.metadata_path = session_dir / "metadata.json"
        self.jsonl_path = session_dir / "session.jsonl"

    @classmethod
    def create(
        cls,
        sessions_dir: Path,
        task: str,
        *,
        workspace_root: Path | None = None,
    ) -> "SessionStore":
        """Create a session below ``sessions_dir`` without app path policy."""

        sessions_dir = Path(sessions_dir)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Session IDs are human-readable so users can browse folders without
        # decoding UUID soup.
        session_id = _unique_session_id(sessions_dir, task)
        session_dir = sessions_dir / session_id
        session_dir.mkdir()

        # Store machine-friendly timestamp truth in metadata.
        # Later CLI rendering can decide whether to show 12-hour display time.
        now = _utc_now()
        metadata: dict[str, Any] = {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
            "task": task,
            "status": "active",
            "active_leaf_id": None,
        }
        if workspace_root is not None:
            # The host may retain workspace identity for viewers without Core
            # needing to know where that host stores sessions.
            metadata["repo_root"] = str(Path(workspace_root).resolve())

        # Write the initial metadata and create an empty JSONL transcript.
        store = cls(session_dir)
        store._write_metadata(metadata)
        store.jsonl_path.write_text("", encoding="utf-8")
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

    # Append a provider-derived assistant reply snapshot. This is diagnostic
    # only: load_messages() deliberately ignores it, so it is never replayed.
    def append_model_reply(self, reply: dict) -> dict:
        return self._append_non_message_entry("model_reply", {"reply": reply})

    # Append validation/rejection details linked to the model_reply snapshot.
    def append_reply_rejection(
        self,
        reply: dict,
        *,
        reason: str,
        consecutive_invalid_attempt: int,
        raw_reply_id: str,
    ) -> dict:
        fields = {
            "reason": reason,
            "error": reply.get("format_error") or reason,
            "consecutive_invalid_attempt": consecutive_invalid_attempt,
            "raw_reply_id": raw_reply_id,
        }
        for name in ("recoverable_tool_name", "recoverable_raw_arguments"):
            if name in reply:
                fields[name] = reply[name]
        return self._append_non_message_entry("reply_rejection", fields)

    def append_compaction_event(self, event: dict) -> dict:
        """Append one first-class compaction lifecycle event."""
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type.startswith("compaction_"):
            raise ValueError("compaction event type must start with 'compaction_'")

        # Keep lifecycle fields at the top level like other diagnostic events;
        # this makes chronological JSONL inspection and filtering straightforward.
        return self._append_non_message_entry(
            event_type,
            {name: value for name, value in event.items() if name != "type"},
        )

    # Append one non-transcript run-context event as a JSONL entry.
    def append_run_context(
        self,
        *,
        skill_name: str | None,
        allowed_tools: list[str],
        prompt_overrides: list[str],
        mod_id: str | None = None,
    ) -> dict:
        session_metadata = self._read_metadata()
        previous_leaf_id = session_metadata["active_leaf_id"]

        entry_id = f"e_{self._next_entry_number():06d}"
        entry = {
            "id": entry_id,
            "parent_id": previous_leaf_id,
            "type": "run_context",
            "timestamp": _utc_now(),
            "skill_name": skill_name,
            "allowed_tools": sorted(allowed_tools),
            "prompt_overrides": sorted(prompt_overrides),
        }

        # Mod identity is optional wrapper metadata. Core persists only the
        # stable identifier and remains unaware of presentation concerns.
        if mod_id is not None:
            entry["mod_id"] = mod_id

        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")

        session_metadata["active_leaf_id"] = entry_id
        session_metadata["updated_at"] = _utc_now()
        self._write_metadata(session_metadata)

        return entry

    def append_system_message_reconciliation(self, message: dict) -> dict:
        """Persist the system message that supersedes earlier run specializations."""
        return self._append_non_message_entry(
            "system_message_reconciliation",
            {"message": message},
        )

    # Load the effective transcript messages from session.jsonl in order.
    #
    # Reconciliation events replace only the active system message; other
    # non-message events remain outside the provider-style transcript.
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
                elif entry.get("type") == "system_message_reconciliation":
                    # Keep storage append-only while making the newest run's
                    # specialization prompt durable across process restarts.
                    messages = [
                        entry["message"],
                        *(
                            message
                            for message in messages
                            if message.get("role") != "system"
                        ),
                    ]

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

    def _append_non_message_entry(self, entry_type: str, fields: dict) -> dict:
        """Append a linked event that is not itself a transcript message."""
        metadata = self._read_metadata()
        entry_id = f"e_{self._next_entry_number():06d}"
        entry = {
            "id": entry_id,
            "parent_id": metadata["active_leaf_id"],
            "type": entry_type,
            "timestamp": _utc_now(),
            **fields,
        }

        with self.jsonl_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry) + "\n")

        metadata["active_leaf_id"] = entry_id
        metadata["updated_at"] = _utc_now()
        self._write_metadata(metadata)
        return entry

    # Read metadata.json as a dictionary.
    def _read_metadata(self) -> dict[str, Any]:
        with self.metadata_path.open(encoding="utf-8") as file:
            return json.load(file)

    # Write metadata.json in a stable, readable format.
    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        atomic_write_json(self.metadata_path, metadata)


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

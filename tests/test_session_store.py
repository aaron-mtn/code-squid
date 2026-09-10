import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from squid_core.storage import SessionStore


def read_metadata(store: SessionStore) -> dict:
    return json.loads(store.metadata_path.read_text(encoding="utf-8"))


def read_entries(store: SessionStore) -> list[dict]:
    return [
        json.loads(line)
        for line in store.jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_create_writes_initial_metadata_and_empty_jsonl(tmp_path: Path) -> None:
    store = SessionStore.create(
        tmp_path,
        "Fix Formatter Underscore Bug",
        workspace_root=tmp_path,
    )
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


def test_load_messages_ignores_compaction_entries(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "compact")
    messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
    ]

    store.append_message(messages[0])
    store.append_compaction_event({"type": "compaction_check", "will_compact": False})
    store.append_message(messages[1])

    assert store.load_messages() == messages


def test_append_run_context_writes_sorted_non_message_entry_and_updates_active_leaf(
    tmp_path: Path,
) -> None:
    store = SessionStore.create(tmp_path, "context")

    entry = store.append_run_context(
        skill_name="user-review",
        allowed_tools=["run_command", "read_file"],
        prompt_overrides=["TOOL_USAGE_GUIDANCE", "FINAL_SUMMARY_REQUIREMENTS"],
    )
    entries = read_entries(store)
    metadata = read_metadata(store)

    assert entry == entries[0]
    assert entries[0]["id"] == "e_000001"
    assert entries[0]["parent_id"] is None
    assert entries[0]["type"] == "run_context"
    assert entries[0]["skill_name"] == "user-review"
    assert entries[0]["allowed_tools"] == ["read_file", "run_command"]
    assert entries[0]["prompt_overrides"] == [
        "FINAL_SUMMARY_REQUIREMENTS",
        "TOOL_USAGE_GUIDANCE",
    ]
    assert metadata["active_leaf_id"] == "e_000001"


def test_load_messages_ignores_run_context_entries(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "context")
    messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
    ]

    store.append_message(messages[0])
    store.append_run_context(
        skill_name=None,
        allowed_tools=["write_file", "read_file"],
        prompt_overrides=[],
    )
    store.append_message(messages[1])

    assert store.load_messages() == messages


def test_append_compaction_event_writes_first_class_jsonl_entry(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "compact lifecycle")

    entry = store.append_compaction_event(
        {"type": "compaction_summary", "content": "exact summary"}
    )

    assert entry["type"] == "compaction_summary"
    assert entry["content"] == "exact summary"
    assert read_entries(store) == [entry]
    assert read_metadata(store)["active_leaf_id"] == entry["id"]
    assert store.load_messages() == []


def test_system_reconciliation_survives_reload_and_preserves_non_system_history(
    tmp_path: Path,
) -> None:
    store = SessionStore.create(tmp_path, "switch specialization")
    history = [
        {"role": "system", "content": "Skill A instructions"},
        {"role": "user", "content": "original task"},
        {"role": "assistant", "content": "original result"},
        {"role": "user", "content": "follow up"},
    ]
    for message in history:
        store.append_message(message)

    replacement = {"role": "system", "content": "Skill B instructions"}
    event = store.append_system_message_reconciliation(replacement)

    assert event["type"] == "system_message_reconciliation"
    assert SessionStore.open(store.session_dir).load_messages() == [
        replacement,
        *history[1:],
    ]
    assert sum(
        message["role"] == "system"
        for message in SessionStore.open(store.session_dir).load_messages()
    ) == 1


def test_append_run_context_persists_optional_mod_id(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "mod context")

    with_mod = store.append_run_context(
        skill_name="story-maker",
        allowed_tools=[],
        prompt_overrides=[],
        mod_id="story-maker",
    )
    without_mod = store.append_run_context(
        skill_name=None,
        allowed_tools=[],
        prompt_overrides=[],
    )

    assert with_mod["mod_id"] == "story-maker"
    assert "mod_id" not in without_mod


def test_create_without_workspace_omits_application_metadata(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "Generic session")

    assert "repo_root" not in read_metadata(store)


def test_create_does_not_register_a_code_squid_global_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "global" / "indexes.jsonl"
    monkeypatch.setenv("CODE_SQUID_SESSION_INDEXES", str(index_path))

    SessionStore.create(tmp_path / "sessions", "Unregistered session")

    assert not index_path.exists()


def test_run_contexts_can_persist_different_mod_ids_in_one_session(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "mod sequence")

    for mod_id in ("story-maker", "reviewer", "story-maker"):
        store.append_run_context(
            skill_name="shared-skill",
            allowed_tools=[],
            prompt_overrides=[],
            mod_id=mod_id,
        )

    contexts = [entry for entry in read_entries(store) if entry["type"] == "run_context"]
    assert [entry["mod_id"] for entry in contexts] == [
        "story-maker",
        "reviewer",
        "story-maker",
    ]


def test_diagnostic_entries_are_linked_and_ignored_by_load_messages(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "diagnostics")
    user = store.append_message({"role": "user", "content": "one"})
    raw = store.append_model_reply(
        {
            "provider": "openrouter",
            "model": "example/model",
            "assistant": {
                "content": "",
                "raw_tool_calls": [
                    {
                        "id": "call_bad",
                        "function": {"name": "read_file", "arguments": '{"path":'},
                    }
                ],
            },
        }
    )
    rejection = store.append_reply_rejection(
        {
            "format_error": "Tool arguments were not valid JSON",
            "recoverable_tool_name": "read_file",
            "recoverable_raw_arguments": '{"path":',
        },
        reason="malformed_tool_call",
        consecutive_invalid_attempt=1,
        raw_reply_id=raw["id"],
    )

    assert raw["type"] == "model_reply"
    assert raw["parent_id"] == user["id"]
    assert rejection["type"] == "reply_rejection"
    assert rejection["parent_id"] == raw["id"]
    assert rejection["raw_reply_id"] == raw["id"]
    assert store.load_messages() == [{"role": "user", "content": "one"}]


def test_compaction_parent_id_links_to_previous_active_leaf(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path, "compact")

    first = store.append_message({"role": "user", "content": "hello"})
    compaction = store.append_compaction_event(
        {"type": "compaction_applied", "summary_chars": 12}
    )

    assert compaction["parent_id"] == first["id"]


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
    import squid_core.storage.session_store as session_store

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

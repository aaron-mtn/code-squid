"""Focused coverage for text-first PDF reads and session page rendering."""

from __future__ import annotations

import importlib
import json
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from code_squid.compaction_context import CodeSquidCompactionContextProvider
from squid_core.settings import ToolResultTrimmingSettings
from squid_core.storage import SessionStore
from squid_core.tool_result_trimming import render_messages_for_model
from squid_core.tools import ToolResults
from squid_core.tools.builtins.read_file import execute as read_file


pdf_reader_module = importlib.import_module("squid_core.file_readers.pdf")


def _write_pdf(path: Path, texts: list[str | None]) -> None:
    path.unlink(missing_ok=True)
    document = pymupdf.open()
    for text in texts:
        page = document.new_page(width=200, height=200)
        if text is not None:
            page.insert_text((24, 50), text)
    document.save(path)
    document.close()


def _write_scanned_pdf(path: Path) -> None:
    stream = BytesIO()
    Image.new("RGB", (40, 30), color=(20, 80, 180)).save(stream, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=200, height=200)
    page.insert_image(pymupdf.Rect(20, 20, 180, 140), stream=stream.getvalue())
    document.save(path)
    document.close()


def _pdf_read(store: SessionStore, path: Path, **kwargs) -> dict:
    return read_file(
        path.parent,
        str(path),
        ensure_generated_image=store.ensure_generated_image,
        **kwargs,
    )


def _tool_turn(call_id: str, path: Path, result: dict) -> list[dict]:
    action = {
        "tool": "read_file",
        "tool_call_id": call_id,
        "args": {"path": str(path)},
    }
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps(action["args"]),
                    },
                }
            ],
        },
        ToolResults().message_from_action_result(action, result),
    ]




















def test_pdf_render_locations_survive_replay_and_compaction_context(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "pdf replay")
    source = tmp_path / "durable.pdf"
    _write_pdf(source, ["durable"])
    result = _pdf_read(store, source)
    messages = _tool_turn("pdf-read", source, result)
    for message in messages:
        store.append_message(message)

    resumed = SessionStore(store.session_dir)
    canonical = resumed.load_canonical_messages()
    context = CodeSquidCompactionContextProvider(
        resumed.load_canonical_messages
    )([])
    rendered_path = result["rendered_pages"][0]["path"]

    assert canonical == messages
    assert context is not None
    assert "Rendered PDF pages available to read as images" in context
    assert rendered_path in context
    assert Path(rendered_path).is_file()
    assert "base64" not in json.dumps(canonical)
    assert "base64" not in context

    store.append_compaction_event(
        {
            "type": "compaction_applied",
            "messages_before": len(messages),
            "messages_after": 1,
            "replay": {
                "version": 1,
                "protected_message_count": 0,
                "preserved_message_count": 0,
                "compacted_message": {"role": "assistant", "content": context},
            },
        }
    )
    compacted_messages = SessionStore(store.session_dir).load_messages()
    assert rendered_path in compacted_messages[0]["content"]

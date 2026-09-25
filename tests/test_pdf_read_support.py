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


read_file_module = importlib.import_module("squid_core.tools.builtins.read_file")


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


def test_text_pdf_extracts_text_and_renders_selected_page_range(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "pdf range")
    source = tmp_path / "manual.pdf"
    _write_pdf(source, ["first", "second", "third"])

    result = _pdf_read(
        store,
        source,
        pages=[{"start_page": 2, "end_page": 3}],
    )

    assert result["ok"] is True
    assert result["media_type"] == "pdf"
    assert result["total_pages"] == 3
    assert result["returned_page_ranges"] == [{"start_page": 2, "end_page": 3}]
    assert "<<< PDF PAGE 2 >>>" in result["content"]
    assert "second" in result["content"]
    assert "<<< PDF PAGE 3 >>>" in result["content"]
    assert "first" not in result["content"]
    assert [item["page"] for item in result["rendered_pages"]] == [2, 3]
    assert not (store.assets_dir / "manual rendered images" / "page-1.png").exists()
    for item in result["rendered_pages"]:
        rendered = Path(item["path"])
        assert rendered.parent.name == "manual rendered images"
        assert rendered.name == f"page-{item['page']}.png"
        assert rendered.is_file()


def test_image_only_pdf_remains_usable_and_rendered_png_uses_normal_read_path(
    tmp_path: Path,
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "scanned pdf")
    source = tmp_path / "scan.pdf"
    _write_scanned_pdf(source)

    pdf_result = _pdf_read(store, source)
    rendered_path = pdf_result["rendered_pages"][0]["path"]
    image_result = read_file(
        tmp_path,
        rendered_path,
        snapshot_asset=store.snapshot_asset,
    )

    assert pdf_result["ok"] is True
    assert "[no extractable text on this page]" in pdf_result["content"]
    assert image_result["ok"] is True
    assert image_result["media_type"] == "image"
    assert store.load_asset(image_result["image"]["asset_id"])


def test_pdf_page_render_is_reused_across_resumed_store_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "reuse")
    source = tmp_path / "cached.pdf"
    _write_pdf(source, ["cached page"])
    first = _pdf_read(store, source)
    original_render = read_file_module._render_pdf_page

    def unexpected_render(*_args, **_kwargs):
        raise AssertionError("an unchanged persisted page should not rerender")

    monkeypatch.setattr(read_file_module, "_render_pdf_page", unexpected_render)
    resumed_store = SessionStore(store.session_dir)
    second = _pdf_read(resumed_store, source)
    monkeypatch.setattr(read_file_module, "_render_pdf_page", original_render)

    assert first["rendered_pages"][0]["reused"] is False
    assert second["rendered_pages"][0]["reused"] is True
    assert second["rendered_pages"][0]["path"] == first["rendered_pages"][0]["path"]


def test_same_stem_pdfs_receive_stable_numbered_render_folders(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "same stem")
    sources = [tmp_path / name / "manual.pdf" for name in ("one", "two", "three")]
    for source, text in zip(sources, ("first", "second", "third"), strict=True):
        source.parent.mkdir()
        _write_pdf(source, [text])

    first = _pdf_read(store, sources[0])
    first_path = Path(first["rendered_pages"][0]["path"])
    first_folder = first_path.parent
    first_files = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in first_folder.iterdir()
    }
    reread = _pdf_read(store, sources[0])
    second = _pdf_read(store, sources[1])
    third = _pdf_read(store, sources[2])

    assert first_folder.name == "manual rendered images"
    assert Path(reread["rendered_pages"][0]["path"]) == first_path
    assert reread["rendered_pages"][0]["reused"] is True
    assert Path(second["rendered_pages"][0]["path"]).parent.name == (
        "manual rendered images 2"
    )
    assert Path(third["rendered_pages"][0]["path"]).parent.name == (
        "manual rendered images 3"
    )
    assert {
        Path(result["rendered_pages"][0]["path"]).name
        for result in (first, reread, second, third)
    } == {"page-1.png"}
    assert first_files == {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in first_folder.iterdir()
    }


def test_pdf_rejects_corruption_file_size_and_excess_page_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "limits")
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"not a PDF")
    corrupt = _pdf_read(store, source)
    assert corrupt["ok"] is False
    assert "invalid or unreadable PDF" in corrupt["error"]

    _write_pdf(source, ["one"])
    monkeypatch.setattr(read_file_module, "MAX_PDF_BYTES", 1)
    oversized = _pdf_read(store, source)
    assert oversized["ok"] is False
    assert "maximum supported size" in oversized["error"]

    monkeypatch.setattr(read_file_module, "MAX_PDF_BYTES", 64 * 1024 * 1024)
    _write_pdf(source, [None] * 21)
    too_many = _pdf_read(store, source)
    assert too_many["ok"] is False
    assert "request pages explicitly" in too_many["error"]
    explicit_too_many = _pdf_read(
        store,
        source,
        pages=[{"start_page": 1, "end_page": 21}],
    )
    assert explicit_too_many["ok"] is False
    assert "maximum is 20 pages" in explicit_too_many["error"]


def test_pdf_page_api_is_distinct_from_text_ranges_and_bounds_render_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "page api")
    source = tmp_path / "large-page.pdf"
    _write_pdf(source, ["bounded"])

    line_range = _pdf_read(
        store,
        source,
        ranges=[{"start_line": 1, "end_line": 1}],
    )
    assert line_range["ok"] is False
    assert "use pages" in line_range["error"]

    invalid_page = _pdf_read(
        store,
        source,
        pages=[{"start_page": 0, "end_page": 1}],
    )
    assert invalid_page["ok"] is False
    assert "start_page must be >= 1" in invalid_page["error"]

    text = tmp_path / "ordinary.txt"
    text.write_text("ordinary", encoding="utf-8")
    non_pdf = read_file(
        tmp_path,
        str(text),
        pages=[{"start_page": 1, "end_page": 1}],
    )
    assert non_pdf["ok"] is False
    assert "only for PDF files" in non_pdf["error"]

    monkeypatch.setattr(read_file_module, "MAX_PDF_RENDER_PIXELS", 10_000)
    rendered = _pdf_read(store, source)
    with Image.open(rendered["rendered_pages"][0]["path"]) as image:
        assert image.width * image.height <= 10_000


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


def test_pdf_request_rendering_exposes_text_and_paths_without_image_injection(
    tmp_path: Path,
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "pdf request")
    source = tmp_path / "visible.pdf"
    _write_pdf(source, ["visible text"])
    result = _pdf_read(store, source)

    rendered = render_messages_for_model(
        _tool_turn("pdf-visible", source, result),
        ToolResultTrimmingSettings(),
    )

    assert [message["role"] for message in rendered] == ["assistant", "tool"]
    tool_content = rendered[1]["content"]
    assert "READ_FILE PDF OK" in tool_content
    assert "visible text" in tool_content
    assert result["rendered_pages"][0]["path"] in tool_content
    assert "image_asset" not in json.dumps(rendered)
    assert "base64" not in json.dumps(rendered)


def test_old_pdf_text_can_trim_without_losing_rendered_page_location(
    tmp_path: Path,
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "old pdf request")
    source = tmp_path / "older.pdf"
    _write_pdf(source, ["long PDF text " * 20])
    result = _pdf_read(store, source)
    messages = _tool_turn("old-pdf", source, result)
    messages.extend(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "new-command",
                        "type": "function",
                        "function": {"name": "run_command", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "new-command",
                "content": json.dumps(
                    {"ok": True, "tool": "run_command", "output": "done"}
                ),
            },
        ]
    )

    rendered = render_messages_for_model(
        messages,
        ToolResultTrimmingSettings(
            recent_full_results=1,
            read_old_content_chars=40,
        ),
    )

    old_pdf_content = rendered[1]["content"]
    assert "truncated: yes" in old_pdf_content
    assert "[older payload truncated]" in old_pdf_content
    assert result["rendered_pages"][0]["path"] in old_pdf_content

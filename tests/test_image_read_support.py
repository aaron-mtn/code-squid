"""Focused coverage for session-backed image reads and provider translation."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from squid_core.hooks.redundant_read import RepeatedReadNudge
from squid_core.hooks.runner import ToolResultContext
from squid_core.hooks.too_many_reads import TooManyReadsNudge
from squid_core.model_adapter import ModelAdapter, ModelRequestError
from squid_core.providers.ollama import (
    OllamaProvider,
    _redacted_trace_payload as redact_ollama_trace,
    convert_messages,
)
from squid_core.providers.openai_compatible import (
    OpenAICompatibleProvider,
    _redacted_trace_payload as redact_openai_trace,
)
from squid_core.settings import ToolResultTrimmingSettings
from squid_core.storage import SessionStore
from squid_core.tool_result_trimming import render_messages_for_model
from squid_core.tools import ToolResults
from squid_core.tools.builtins.read_file import execute as read_file
from squid_core.tools.executor import ToolExecutor


read_file_module = importlib.import_module("squid_core.tools.builtins.read_file")
atomic_json_module = importlib.import_module("squid_core.storage.atomic_json")


def image_bytes(image_format: str, *, size: tuple[int, int] = (3, 2)) -> bytes:
    """Create one tiny in-memory fixture without committing binary assets."""

    stream = BytesIO()
    Image.new("RGB", size, color=(220, 30, 40)).save(stream, format=image_format)
    return stream.getvalue()


def test_existing_text_and_range_reads_are_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("one\ntwo\nthree\n", encoding="utf-8")

    whole = read_file(tmp_path, str(source))
    ranged = read_file(
        tmp_path,
        str(source),
        ranges=[{"start_line": 2, "end_line": 2}],
    )

    assert whole["ok"] is True
    assert whole["content"] == "one\ntwo\nthree\n"
    assert whole["ranged"] is False
    assert ranged["ok"] is True
    assert "two" in ranged["content"]
    assert ranged["ranged"] is True


@pytest.mark.parametrize(
    ("suffix", "image_format", "mime_type", "canonical_suffix"),
    [
        (".png", "PNG", "image/png", ".png"),
        (".jpg", "JPEG", "image/jpeg", ".jpg"),
        (".jpeg", "JPEG", "image/jpeg", ".jpg"),
        (".webp", "WEBP", "image/webp", ".webp"),
    ],
)
def test_supported_image_read_snapshots_exact_bytes_and_metadata(
    tmp_path: Path,
    suffix: str,
    image_format: str,
    mime_type: str,
    canonical_suffix: str,
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "image")
    source = tmp_path / f"fixture{suffix}"
    original = image_bytes(image_format)
    source.write_bytes(original)

    result = read_file(
        tmp_path,
        str(source),
        snapshot_asset=store.snapshot_asset,
    )

    digest = hashlib.sha256(original).hexdigest()
    assert result == {
        "ok": True,
        "tool": "read_file",
        "path": str(source),
        "media_type": "image",
        "image": {
            "version": 1,
            "asset_id": f"{digest}{canonical_suffix}",
            "sha256": digest,
            "mime_type": mime_type,
            "format": image_format,
            "width": 3,
            "height": 2,
            "size_bytes": len(original),
        },
    }
    assert store.load_asset(result["image"]["asset_id"]) == original


def test_image_read_rejects_ranges_corruption_and_safety_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "errors")
    source = tmp_path / "fixture.png"
    source.write_bytes(image_bytes("PNG", size=(2, 2)))

    ranged = read_file(
        tmp_path,
        str(source),
        ranges=[{"start_line": 1, "end_line": 1}],
        snapshot_asset=store.snapshot_asset,
    )
    assert ranged["ok"] is False
    assert "line ranges" in ranged["error"]

    source.write_bytes(b"not an image")
    corrupt = read_file(tmp_path, str(source), snapshot_asset=store.snapshot_asset)
    assert corrupt["ok"] is False
    assert "invalid or corrupt image" in corrupt["error"]

    source.write_bytes(image_bytes("PNG", size=(2, 2)))
    monkeypatch.setattr(read_file_module, "MAX_IMAGE_BYTES", 1)
    oversized = read_file(tmp_path, str(source), snapshot_asset=store.snapshot_asset)
    assert oversized["ok"] is False
    assert "maximum supported size" in oversized["error"]

    monkeypatch.setattr(read_file_module, "MAX_IMAGE_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr("squid_core.image_content.MAX_IMAGE_PIXELS", 3)
    excessive_pixels = read_file(
        tmp_path,
        str(source),
        snapshot_asset=store.snapshot_asset,
    )
    assert excessive_pixels["ok"] is False
    assert "maximum supported count" in excessive_pixels["error"]


def test_image_read_rejects_extension_mismatch_and_snapshot_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fixture.png"
    source.write_bytes(image_bytes("JPEG"))

    mismatch = read_file(tmp_path, str(source), snapshot_asset=lambda *_args: "unused")
    assert mismatch["ok"] is False
    assert "does not match" in mismatch["error"]

    source.write_bytes(image_bytes("PNG"))

    def fail_snapshot(_data: bytes, _extension: str) -> str:
        raise OSError("disk unavailable")

    failed = read_file(tmp_path, str(source), snapshot_asset=fail_snapshot)
    assert failed["ok"] is False
    assert "could not snapshot image into the session" in failed["error"]

    unsupported = tmp_path / "fixture.gif"
    unsupported.write_bytes(image_bytes("GIF"))
    rejected = read_file(tmp_path, str(unsupported), snapshot_asset=lambda *_args: "unused")
    assert rejected["ok"] is False
    assert rejected["error"] == "unsupported image extension: .gif"


def test_image_snapshot_uses_same_directory_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "atomic")
    original_replace = atomic_json_module._replace_with_permission_retry
    observed: list[tuple[Path, Path]] = []

    def observe_replace(source: Path, destination: Path) -> None:
        assert source.exists()
        assert not destination.exists()
        observed.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr(
        atomic_json_module,
        "_replace_with_permission_retry",
        observe_replace,
    )
    asset_id = store.snapshot_asset(image_bytes("PNG"), ".png")

    assert len(observed) == 1
    temporary_path, destination = observed[0]
    assert temporary_path.parent == store.assets_dir
    assert destination == store.assets_dir / asset_id
    assert destination.exists()
    assert not temporary_path.exists()


def test_image_snapshot_deduplicates_and_survives_workspace_change(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "deduplicate")
    source = tmp_path / "fixture.png"
    original = image_bytes("PNG")
    source.write_bytes(original)

    first = read_file(tmp_path, str(source), snapshot_asset=store.snapshot_asset)
    second = read_file(tmp_path, str(source), snapshot_asset=store.snapshot_asset)
    source.write_bytes(image_bytes("PNG", size=(4, 4)))

    assert first["image"]["asset_id"] == second["image"]["asset_id"]
    assert len(list(store.assets_dir.iterdir())) == 1
    assert store.load_asset(first["image"]["asset_id"]) == original


def test_asset_loading_rejects_paths_missing_files_and_corruption(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "safe assets")
    data = image_bytes("PNG")
    asset_id = store.snapshot_asset(data, ".png")

    with pytest.raises(ValueError, match="invalid session asset ID"):
        store.load_asset("../outside.png")
    (store.assets_dir / asset_id).unlink()
    with pytest.raises(FileNotFoundError, match="Missing session image asset"):
        store.load_asset(asset_id)

    asset_id = store.snapshot_asset(data, ".png")
    (store.assets_dir / asset_id).write_bytes(b"changed")
    with pytest.raises(OSError, match="Corrupt session image asset"):
        store.load_asset(asset_id)


def test_asset_directory_containment_fails_closed(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "containment")
    outside = tmp_path / "outside-assets"
    outside.mkdir()
    store.assets_dir = outside

    with pytest.raises(ValueError, match="escapes the session directory"):
        store.snapshot_asset(image_bytes("PNG"), ".png")


def image_tool_turn(result: dict, *, call_id: str = "image_call") -> list[dict]:
    action = {"tool": "read_file", "tool_call_id": call_id, "args": {}}
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        ToolResults().message_from_action_result(action, result),
    ]


def test_request_rendering_keeps_tool_text_and_injects_after_sibling_batch(
    tmp_path: Path,
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "batch")
    source = tmp_path / "fixture.png"
    source.write_bytes(image_bytes("PNG"))
    result = read_file(tmp_path, str(source), snapshot_asset=store.snapshot_asset)
    assistant = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "image", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            {"id": "command", "type": "function", "function": {"name": "run_command", "arguments": "{}"}},
        ],
    }
    messages = [
        assistant,
        ToolResults().message_from_action_result(
            {"tool_call_id": "image"}, result
        ),
        ToolResults().message_from_action_result(
            {"tool_call_id": "command"},
            {"ok": True, "tool": "run_command", "output": "done"},
        ),
    ]

    rendered = render_messages_for_model(messages, ToolResultTrimmingSettings())

    assert [message["role"] for message in rendered] == [
        "assistant",
        "tool",
        "tool",
        "user",
    ]
    assert isinstance(rendered[1]["content"], str)
    assert "READ_FILE IMAGE OK" in rendered[1]["content"]
    assert rendered[3]["content"][1]["type"] == "image_asset"
    assert "base64" not in json.dumps(rendered)


class _FakeCompletions:
    def __init__(self) -> None:
        self.payload = None

    def create(self, **payload):
        self.payload = payload
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="seen", tool_calls=[]),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )


def lm_studio_provider() -> tuple[OpenAICompatibleProvider, _FakeCompletions]:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.provider_name = "lm_studio"
    provider.temperature = None
    provider.reasoning_mode = None
    provider.reasoning_token_budget = None
    provider._image_capability_cache = {"vision-model": True}
    completions = _FakeCompletions()
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return provider, completions


def test_openai_image_materializes_after_request_observation(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "openai")
    data = image_bytes("PNG")
    asset_id = store.snapshot_asset(data, ".png")
    internal = {
        "role": "user",
        "content": [
            {"type": "text", "text": "inspect"},
            {
                "type": "image_asset",
                "asset_id": asset_id,
                "mime_type": "image/png",
                "description": "[image: fixture.png]",
            },
        ],
    }
    provider, completions = lm_studio_provider()
    observed = []
    adapter = ModelAdapter(
        provider,
        "vision-model",
        provider_name="lm_studio",
        request_observer=observed.append,
    )
    adapter.set_asset_loader(store.load_asset)

    adapter.respond([internal], [])

    assert observed[0]["messages"] == [internal]
    data_url = completions.payload["messages"][0]["content"][1]["image_url"]["url"]
    assert base64.b64decode(data_url.split(",", 1)[1]) == data
    assert "base64" not in json.dumps(observed)
    assert "base64" not in json.dumps(redact_openai_trace(completions.payload))


def test_provider_failure_after_snapshot_leaves_replayable_asset(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "transport failure")
    source = tmp_path / "fixture.png"
    original = image_bytes("PNG")
    source.write_bytes(original)
    result = read_file(tmp_path, str(source), snapshot_asset=store.snapshot_asset)
    messages = render_messages_for_model(
        image_tool_turn(result), ToolResultTrimmingSettings()
    )

    provider, completions = lm_studio_provider()

    def fail_transport(**_payload):
        raise OSError("provider disconnected")

    completions.create = fail_transport
    adapter = ModelAdapter(provider, "vision-model", provider_name="lm_studio")
    adapter.set_asset_loader(store.load_asset)

    with pytest.raises(ModelRequestError, match="provider disconnected"):
        adapter.respond(messages, [])
    assert store.load_asset(result["image"]["asset_id"]) == original


def test_lm_studio_capability_is_read_from_model_metadata() -> None:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.provider_name = "lm_studio"
    provider._lm_studio_models = lambda: [
        {"key": "vision", "loaded_instances": [], "capabilities": {"vision": True}},
        {"key": "text", "loaded_instances": [], "capabilities": {"vision": False}},
    ]

    assert provider.supports_image_input("vision") is True
    assert provider.supports_image_input("text") is False

    adapter = ModelAdapter(provider, "text", provider_name="lm_studio")
    adapter.set_asset_loader(lambda _asset_id: b"unused")
    with pytest.raises(ModelRequestError, match="does not support image input"):
        adapter.respond(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_asset",
                            "asset_id": "asset.png",
                            "mime_type": "image/png",
                        }
                    ],
                }
            ],
            [],
        )


def test_generic_openai_provider_fails_closed_for_images() -> None:
    provider, _completions = lm_studio_provider()
    provider.provider_name = "openai_compatible"
    adapter = ModelAdapter(provider, "unknown", provider_name="openai_compatible")
    adapter.set_asset_loader(lambda _asset_id: b"data")
    message = {
        "role": "user",
        "content": [{"type": "image_asset", "asset_id": "x", "mime_type": "image/png"}],
    }

    with pytest.raises(ModelRequestError, match="does not support image input"):
        adapter.respond([message], [])


def test_ollama_translation_and_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    data = image_bytes("PNG")
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": "inspect"},
            {"type": "image_asset", "asset_id": "asset.png", "mime_type": "image/png"},
        ],
    }
    converted = convert_messages([message], asset_loader=lambda _asset_id: data)
    assert converted[0]["content"] == "inspect"
    assert base64.b64decode(converted[0]["images"][0]) == data
    assert "base64" not in json.dumps(redact_ollama_trace({"messages": converted}))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"capabilities":["completion","vision"]}'

    monkeypatch.setattr("squid_core.providers.ollama.request.urlopen", lambda *_a, **_k: Response())
    assert OllamaProvider().supports_image_input("vision-model") is True

    class TextResponse(Response):
        def read(self):
            return b'{"capabilities":["completion"]}'

    monkeypatch.setattr(
        "squid_core.providers.ollama.request.urlopen",
        lambda *_a, **_k: TextResponse(),
    )
    text_provider = OllamaProvider()
    assert text_provider.supports_image_input("text-model") is False
    adapter = ModelAdapter(text_provider, "text-model", provider_name="ollama")
    adapter.set_asset_loader(lambda _asset_id: data)
    with pytest.raises(ModelRequestError, match="does not support image input"):
        adapter.respond([message], [])


def test_canonical_persistence_replay_and_logs_keep_only_asset_reference(
    tmp_path: Path,
) -> None:
    store = SessionStore.create(tmp_path / "sessions", "replay")
    source = tmp_path / "fixture.png"
    original = image_bytes("PNG")
    source.write_bytes(original)
    result = read_file(tmp_path, str(source), snapshot_asset=store.snapshot_asset)
    messages = image_tool_turn(result)
    for message in messages:
        store.append_message(message)
    store.append_compaction_event(
        {
            "type": "compaction_applied",
            "messages_before": len(messages),
            "messages_after": 3,
            "replay": {
                "version": 1,
                "protected_message_count": 0,
                "preserved_message_count": 2,
                "compacted_message": {
                    "role": "assistant",
                    "content": "# Compacted Working Context\nPreserved recent image read.",
                },
            },
        }
    )
    rendered = render_messages_for_model(
        store.load_messages(), ToolResultTrimmingSettings()
    )
    store.append_model_view({"model": "vision", "provider": "test", "messages": rendered, "tools": []})
    source.write_bytes(image_bytes("PNG", size=(8, 8)))

    assert any(
        isinstance(message.get("content"), list)
        and any(block.get("type") == "image_asset" for block in message["content"])
        for message in rendered
    )
    assert store.load_asset(result["image"]["asset_id"]) == original

    # A later compaction may remove the old image turn from effective context,
    # but its canonical descriptor and immutable asset remain available on disk.
    store.append_compaction_event(
        {
            "type": "compaction_applied",
            "messages_before": 3,
            "messages_after": 1,
            "replay": {
                "version": 1,
                "protected_message_count": 0,
                "preserved_message_count": 0,
                "compacted_message": {
                    "role": "assistant",
                    "content": "# Compacted Working Context\nOld image turn omitted.",
                },
            },
        }
    )
    compacted_render = render_messages_for_model(
        store.load_messages(), ToolResultTrimmingSettings()
    )
    assert "image_asset" not in json.dumps(compacted_render)
    assert store.load_asset(result["image"]["asset_id"]) == original
    for path in (store.jsonl_path, store.model_view_path, store.model_transcript_path):
        persisted = path.read_text(encoding="utf-8")
        assert "data:image" not in persisted
        assert base64.b64encode(original).decode("ascii") not in persisted
    assert "[image:" in store.model_transcript_path.read_text(encoding="utf-8")


def test_missing_replay_asset_and_image_hooks_fail_safely(tmp_path: Path) -> None:
    store = SessionStore.create(tmp_path / "sessions", "missing")
    data = image_bytes("PNG")
    asset_id = store.snapshot_asset(data, ".png")
    (store.assets_dir / asset_id).unlink()
    provider, _completions = lm_studio_provider()
    adapter = ModelAdapter(provider, "vision-model", provider_name="lm_studio")
    adapter.set_asset_loader(store.load_asset)
    message = {
        "role": "user",
        "content": [{"type": "image_asset", "asset_id": asset_id, "mime_type": "image/png"}],
    }
    with pytest.raises(ModelRequestError, match="Missing session image asset"):
        adapter.respond([message], [])

    result = {
        "ok": True,
        "tool": "read_file",
        "path": str(tmp_path / "image.png"),
        "media_type": "image",
        "image": {},
    }
    context = ToolResultContext(
        session_id="session",
        repo_root=str(tmp_path),
        action={"tool": "read_file", "args": {"path": result["path"]}},
        result=result,
    )
    assert RepeatedReadNudge().tool_result(context) is None
    assert TooManyReadsNudge().tool_result(context) is None


def test_workspace_boundary_blocks_image_before_asset_snapshot(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(image_bytes("PNG"))
    store = SessionStore.create(tmp_path / "sessions", "boundary")
    session = SimpleNamespace(mark_file_read=lambda _path: None, mark_file_written=lambda _path: None)
    executor = ToolExecutor(
        workspace,
        session,
        snapshot_asset=store.snapshot_asset,
    )

    result = executor.execute({"tool": "read_file", "args": {"path": str(outside)}})

    assert result["ok"] is False
    assert "outside the workspace root" in result["error"]
    assert not store.assets_dir.exists()

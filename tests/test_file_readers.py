"""Focused coverage for the shared file-reader invocation contract."""

from pathlib import Path

from squid_core.file_readers.context import FileReadContext
from squid_core.file_readers.registry import read_with_registered_reader
from squid_core.settings import ReadFileSettings


def test_registry_invokes_registered_reader_with_unchanged_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A newly registered reader must not require a dispatcher branch."""

    from squid_core.file_readers import registry

    context = FileReadContext(
        file_path=tmp_path / "sample.future",
        path=str(tmp_path / "sample.future"),
        ranges=None,
        pages=None,
        settings=ReadFileSettings(),
        snapshot_asset=None,
        ensure_generated_image=None,
    )
    seen = []

    def read_future(received: FileReadContext) -> dict:
        seen.append(received)
        return {"ok": True, "format": "future"}

    monkeypatch.setitem(registry._READERS_BY_SUFFIX, ".future", read_future)

    assert read_with_registered_reader(context) == {
        "ok": True,
        "format": "future",
    }
    assert seen == [context]

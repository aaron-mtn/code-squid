"""Tests for atomic writes of small JSON state files."""

import json
from pathlib import Path

import pytest

from squid_core.storage.atomic_json import atomic_write_json


def test_atomic_write_json_writes_existing_format(tmp_path: Path) -> None:
    destination = tmp_path / "state.json"

    atomic_write_json(destination, {"enabled": True, "items": [1, 2]})

    assert destination.read_text(encoding="utf-8") == (
        '{\n  "enabled": true,\n  "items": [\n    1,\n    2\n  ]\n}\n'
    )
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "enabled": True,
        "items": [1, 2],
    }


def test_serialization_failure_leaves_previous_file_intact(tmp_path: Path) -> None:
    destination = tmp_path / "state.json"
    previous = '{\n  "status": "valid"\n}\n'
    destination.write_text(previous, encoding="utf-8")

    with pytest.raises(TypeError):
        atomic_write_json(destination, {"invalid": object()})

    assert destination.read_text(encoding="utf-8") == previous
    assert list(tmp_path.iterdir()) == [destination]


def test_replace_failure_does_not_install_partial_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "state.json"
    previous = '{\n  "status": "valid"\n}\n'
    destination.write_text(previous, encoding="utf-8")

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("squid_core.storage.atomic_json.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_json(destination, {"status": "new"})

    assert destination.read_text(encoding="utf-8") == previous
    assert json.loads(destination.read_text(encoding="utf-8")) == {"status": "valid"}
    assert list(tmp_path.iterdir()) == [destination]

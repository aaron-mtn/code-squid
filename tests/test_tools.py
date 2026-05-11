import importlib
from pathlib import Path
from subprocess import TimeoutExpired

import pytest

from tools.read_file import execute as read_file
from tools.run_command import execute as run_command
from tools.write_file import execute as write_file


run_command_module = importlib.import_module("tools.run_command")


def test_read_file_rejects_relative_path_and_succeeds_with_absolute_path(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("hello", encoding="utf-8")

    relative_result = read_file(tmp_path, "input.txt")
    absolute_result = read_file(tmp_path, str(file_path))

    assert relative_result == {
        "ok": False,
        "tool": "read_file",
        "path": "input.txt",
        "error": "read_file requires an absolute path",
    }
    assert absolute_result == {
        "ok": True,
        "tool": "read_file",
        "path": str(file_path),
        "content": "hello",
    }


def test_write_file_rejects_relative_path_succeeds_with_absolute_path_and_is_compact(tmp_path: Path) -> None:
    file_path = tmp_path / "output.txt"

    relative_result = write_file(tmp_path, "output.txt", "written")
    absolute_result = write_file(tmp_path, str(file_path), "written")

    assert relative_result == {
        "ok": False,
        "tool": "write_file",
        "path": "output.txt",
        "error": "write_file requires an absolute path",
    }
    assert absolute_result["ok"] is True
    assert absolute_result["tool"] == "write_file"
    assert absolute_result["path"] == str(file_path)
    assert absolute_result["summary"] == "Wrote 7 characters"
    assert absolute_result["characters_written"] == 7
    assert "content" not in absolute_result
    assert file_path.read_text(encoding="utf-8") == "written"


def test_run_command_timeout_returns_normal_failure_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def raise_timeout(*args, **kwargs):
        raise TimeoutExpired(cmd="sleep 1", timeout=0.01, output="partial output")

    monkeypatch.setattr(run_command_module.subprocess, "run", raise_timeout)

    result = run_command(tmp_path, "sleep 1")

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["tool"] == "run_command"
    assert result["command"] == "sleep 1"

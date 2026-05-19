import importlib
from pathlib import Path
from subprocess import TimeoutExpired

import pytest

from tools.read_file import execute as read_file
from tools.read_file import tool_definition as read_file_definition
from tools._truncation import truncate_head_tail
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
        "content_truncated": False,
        "content_original_chars": 5,
        "content_returned_chars": 5,
        "start_line": 1,
        "end_line": 1,
        "total_lines": 1,
        "ranged": False,
    }


def test_read_file_supports_start_and_end_line_range(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=2, end_line=3)

    assert result == {
        "ok": True,
        "tool": "read_file",
        "path": str(file_path),
        "content": "two\nthree\n",
        "content_truncated": False,
        "content_original_chars": 10,
        "content_returned_chars": 10,
        "start_line": 2,
        "end_line": 3,
        "total_lines": 4,
        "ranged": True,
    }


def test_read_file_supports_start_line_without_end_line(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=2)

    assert result["content"] == "two\nthree\n"
    assert result["start_line"] == 2
    assert result["end_line"] == 3
    assert result["total_lines"] == 3
    assert result["ranged"] is True
    assert result["content_truncated"] is False
    assert result["content_original_chars"] == len(result["content"])
    assert result["content_returned_chars"] == len(result["content"])


def test_read_file_supports_end_line_without_start_line(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), end_line=2)

    assert result["content"] == "one\ntwo\n"
    assert result["start_line"] == 1
    assert result["end_line"] == 2
    assert result["total_lines"] == 3
    assert result["ranged"] is True
    assert result["content_truncated"] is False
    assert result["content_original_chars"] == len(result["content"])
    assert result["content_returned_chars"] == len(result["content"])


def test_read_file_truncates_large_full_read_with_shared_helper(tmp_path: Path) -> None:
    file_path = tmp_path / "large.txt"
    original_content = "a" * 7000 + "\nmiddle\n" + "z" * 7000
    file_path.write_text(original_content, encoding="utf-8")

    result = read_file(tmp_path, str(file_path))
    expected_content, expected_metadata = truncate_head_tail(original_content)

    assert result["content"] == expected_content
    assert result["content_truncated"] is True
    assert result["content_original_chars"] == expected_metadata["original_chars"]
    assert result["content_returned_chars"] == expected_metadata["returned_chars"]


def test_read_file_does_not_truncate_large_ranged_read(tmp_path: Path) -> None:
    file_path = tmp_path / "large-range.txt"
    ranged_content = "x" * 13000 + "\n"
    file_path.write_text(f"before\n{ranged_content}after\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=2, end_line=2)

    assert result["content"] == ranged_content
    assert result["content_truncated"] is False
    assert result["content_original_chars"] == len(ranged_content)
    assert result["content_returned_chars"] == len(ranged_content)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"start_line": 0}, "start_line must be >= 1"),
        ({"end_line": 0}, "end_line must be >= 1"),
        ({"start_line": 3, "end_line": 2}, "end_line must be >= start_line"),
    ],
)
def test_read_file_rejects_invalid_ranges(tmp_path: Path, kwargs: dict, error: str) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), **kwargs)

    assert result == {
        "ok": False,
        "tool": "read_file",
        "path": str(file_path),
        "error": error,
    }


def test_read_file_range_past_eof_is_empty_and_sets_empty_range_end_line(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("one\ntwo\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=5, end_line=8)

    assert result == {
        "ok": True,
        "tool": "read_file",
        "path": str(file_path),
        "content": "",
        "content_truncated": False,
        "content_original_chars": 0,
        "content_returned_chars": 0,
        "start_line": 5,
        "end_line": 4,
        "total_lines": 2,
        "ranged": True,
    }


def test_read_file_definition_accepts_optional_line_range_arguments() -> None:
    parameters = read_file_definition()["function"]["parameters"]

    assert parameters["required"] == ["path"]
    assert parameters["properties"]["start_line"]["type"] == "integer"
    assert parameters["properties"]["end_line"]["type"] == "integer"


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

import importlib
from pathlib import Path
import shlex
from subprocess import TimeoutExpired
import sys

import pytest

from squid_core.tools.builtins.read_file import execute as read_file
from squid_core.tools.builtins.read_file import tool_definition as read_file_definition
from squid_core.tools.builtins._truncation import truncate_head_tail
from squid_core.tools.builtins import TOOLS
from squid_core.tools.builtins.run_command import execute as run_command
from squid_core.tools.builtins.apply_patch import execute as apply_patch
from squid_core.tools.builtins.write_file import execute as write_file
from squid_core.settings import ReadFileSettings


run_command_module = importlib.import_module("squid_core.tools.builtins.run_command")


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


def test_run_command_uses_selected_repo_root_as_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = (
        f"& '{sys.executable}'"
        if sys.platform == "win32"
        else shlex.quote(sys.executable)
    )

    result = run_command(
        workspace,
        f'{executable} -c "from pathlib import Path; print(Path.cwd())"',
    )

    assert result["ok"] is True
    assert result["output"] == f"{workspace.resolve()}\n"
    assert result["verification"] is False


def test_run_command_exposes_and_returns_explicit_verification_intent(
    tmp_path: Path,
) -> None:
    parameters = TOOLS["run_command"]["definition"]()["function"]["parameters"]

    assert parameters["properties"]["verification"] == {
        "type": "boolean",
        "description": "Whether this command is being run to verify the current changes",
        "default": False,
    }

    executable = (
        f"& '{sys.executable}'"
        if sys.platform == "win32"
        else shlex.quote(sys.executable)
    )
    result = run_command(
        tmp_path,
        f'{executable} -c "print(\'verified\')"',
        verification=True,
    )

    assert result["ok"] is True
    assert result["verification"] is True


def test_read_file_supports_start_and_end_line_range(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=2, end_line=3)

    assert result["content"] == "one\ntwo\nthree\nfour\n"
    assert result["start_line"] == 1
    assert result["end_line"] == 4
    assert result["total_lines"] == 4
    assert result["ranged"] is True


def test_read_file_supports_start_line_without_end_line(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=2)

    assert result["content"] == "one\ntwo\nthree\n"
    assert result["start_line"] == 1
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

    assert result["content"] == "one\ntwo\nthree\n"
    assert result["start_line"] == 1
    assert result["end_line"] == 3
    assert result["total_lines"] == 3
    assert result["ranged"] is True
    assert result["content_truncated"] is False
    assert result["content_original_chars"] == len(result["content"])
    assert result["content_returned_chars"] == len(result["content"])


@pytest.mark.parametrize("line_count", [999, 1000])
def test_read_file_returns_full_content_at_or_under_line_limit(
    tmp_path: Path, line_count: int
) -> None:
    file_path = tmp_path / f"{line_count}-lines.txt"
    # Exceed the old shared character limit so this also proves that line count
    # is now the only limit on full-file reads.
    original_content = "".join(
        f"line {number}: {'x' * 20}\n" for number in range(1, line_count + 1)
    )
    file_path.write_text(original_content, encoding="utf-8")

    result = read_file(tmp_path, str(file_path))

    assert result["content"] == original_content
    assert result["content_truncated"] is False
    assert result["content_original_chars"] == len(original_content)
    assert result["content_returned_chars"] == len(original_content)
    assert "returned_line_ranges" not in result
    assert "truncation_guidance" not in result


def test_read_file_truncates_large_full_read_by_lines_and_reports_ranges(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "1001-lines.txt"
    lines = [f"line {number}\n" for number in range(1, 1002)]
    original_content = "".join(lines)
    expected_content = "".join((*lines[:500], *lines[-500:]))
    file_path.write_text(original_content, encoding="utf-8")

    result = read_file(tmp_path, str(file_path))

    assert result["content"] == expected_content
    assert len(result["content"].splitlines()) == 1000
    assert result["content_truncated"] is True
    assert result["content_original_chars"] == len(original_content)
    assert result["content_returned_chars"] == len(expected_content)
    assert result["start_line"] == 1
    assert result["end_line"] == 1001
    assert result["total_lines"] == 1001
    assert result["returned_line_ranges"] == [
        {"start_line": 1, "end_line": 500},
        {"start_line": 502, "end_line": 1001},
    ]
    assert result["truncation_guidance"] == (
        "Full-file read truncated to 1000 of 1001 lines; returned lines 1-500 and "
        "502-1001. Use start_line and end_line to inspect the missing relevant section."
    )


def test_read_file_does_not_truncate_large_ranged_read(tmp_path: Path) -> None:
    file_path = tmp_path / "large-range.txt"
    lines = [f"line {number}\n" for number in range(1, 1201)]
    original_content = "".join(lines)
    file_path.write_text(original_content, encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=1, end_line=1200)

    assert result["content"] == original_content
    assert result["content_truncated"] is False
    assert result["content_original_chars"] == len(original_content)
    assert result["content_returned_chars"] == len(original_content)
    assert "returned_line_ranges" not in result
    assert "truncation_guidance" not in result


def test_small_middle_range_expands_with_balanced_context(tmp_path: Path) -> None:
    file_path = tmp_path / "middle.txt"
    lines = [f"line {number}\n" for number in range(1, 1001)]
    file_path.write_text("".join(lines), encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=520, end_line=560)

    assert result["start_line"] == 466
    assert result["end_line"] == 615
    assert len(result["content"].splitlines()) == 150
    assert result["content"].startswith("line 466\n")
    assert result["content"].endswith("line 615\n")


def test_small_range_near_beginning_shifts_expansion_inside_file(tmp_path: Path) -> None:
    file_path = tmp_path / "beginning.txt"
    lines = [f"line {number}\n" for number in range(1, 301)]
    file_path.write_text("".join(lines), encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=10, end_line=20)

    assert (result["start_line"], result["end_line"]) == (1, 150)
    assert result["content"] == "".join(lines[:150])


def test_small_range_near_end_shifts_expansion_inside_file(tmp_path: Path) -> None:
    file_path = tmp_path / "end.txt"
    lines = [f"line {number}\n" for number in range(1, 301)]
    file_path.write_text("".join(lines), encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=290, end_line=300)

    assert (result["start_line"], result["end_line"]) == (151, 300)
    assert result["content"] == "".join(lines[150:])


def test_range_at_or_above_minimum_is_unchanged(tmp_path: Path) -> None:
    file_path = tmp_path / "large-enough.txt"
    lines = [f"line {number}\n" for number in range(1, 401)]
    file_path.write_text("".join(lines), encoding="utf-8")

    result = read_file(tmp_path, str(file_path), start_line=100, end_line=249)

    assert (result["start_line"], result["end_line"]) == (100, 249)
    assert result["content"] == "".join(lines[99:249])


def test_read_file_uses_supplied_sizing_settings_and_keeps_truncation_metadata(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "custom-limit.txt"
    lines = [f"line {number}\n" for number in range(1, 12)]
    original_content = "".join(lines)
    file_path.write_text(original_content, encoding="utf-8")

    result = read_file(
        tmp_path,
        str(file_path),
        settings=ReadFileSettings(default_max_lines=10, minimum_range_lines=4),
    )

    assert result["content"] == "".join((*lines[:5], *lines[-5:]))
    assert result["content_truncated"] is True
    assert result["content_original_chars"] == len(original_content)
    assert result["content_returned_chars"] == len(result["content"])
    assert result["returned_line_ranges"] == [
        {"start_line": 1, "end_line": 5},
        {"start_line": 7, "end_line": 11},
    ]


def test_run_command_keeps_shared_character_truncation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = "x" * 12001

    class Completed:
        returncode = 0
        stdout = output

    monkeypatch.setattr(
        run_command_module.subprocess,
        "run",
        lambda *args, **kwargs: Completed(),
    )

    result = run_command(tmp_path, "generate lots of output")
    expected_output, expected_metadata = truncate_head_tail(output)

    assert result["output"] == expected_output
    assert result["output_truncated"] is True
    assert result["output_original_chars"] == expected_metadata["original_chars"]
    assert result["output_returned_chars"] == expected_metadata["returned_chars"]


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


def test_apply_patch_replaces_one_exact_occurrence_and_is_compact(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("before middle after", encoding="utf-8")

    result = apply_patch(tmp_path, str(file_path), "middle", "center")

    assert result == {
        "ok": True,
        "tool": "apply_patch",
        "path": str(file_path),
        "replacements": 1,
        "start_line": 1,
        "end_line_before": 1,
        "end_line_after": 1,
        "chars_before": 19,
        "chars_after": 19,
    }
    assert file_path.read_text(encoding="utf-8") == "before center after"
    assert "content" not in result


def test_apply_patch_fails_when_old_text_missing_and_does_not_modify_file(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("original", encoding="utf-8")

    result = apply_patch(tmp_path, str(file_path), "missing", "replacement")

    assert result == {
        "ok": False,
        "tool": "apply_patch",
        "path": str(file_path),
        "error": "old_text_not_found",
        "occurrences": 0,
    }
    assert file_path.read_text(encoding="utf-8") == "original"


def test_apply_patch_fails_when_old_text_is_not_unique_and_does_not_modify_file(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("same different same", encoding="utf-8")

    result = apply_patch(tmp_path, str(file_path), "same", "changed")

    assert result["ok"] is False
    assert result["tool"] == "apply_patch"
    assert result["path"] == str(file_path)
    assert result["error"] == "old_text_not_unique"
    assert result["occurrences"] == 2
    assert len(result["matches"]) == 2
    assert file_path.read_text(encoding="utf-8") == "same different same"


def test_apply_patch_missing_text_returns_closest_same_sized_window(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    original = "header\nalpha = 1\nbeta = 20\ngamma = 3\nfooter\n"
    file_path.write_text(original, encoding="utf-8")

    result = apply_patch(
        tmp_path,
        str(file_path),
        "alpha = 1\nbeta = 2\ngamma = 3",
        "replacement",
    )

    assert result["error"] == "old_text_not_found"
    assert result["closest_match"] == {
        "start_line": 2,
        "end_line": 4,
        "similarity": pytest.approx(0.982, abs=0.001),
        "content": "alpha = 1\nbeta = 20\ngamma = 3\n",
    }
    assert file_path.read_text(encoding="utf-8") == original


def test_apply_patch_missing_text_omits_low_confidence_context(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    original = "one\ntwo\nthree\n"
    file_path.write_text(original, encoding="utf-8")

    result = apply_patch(tmp_path, str(file_path), "completely\nunrelated", "replacement")

    assert result["error"] == "old_text_not_found"
    assert "closest_match" not in result
    assert file_path.read_text(encoding="utf-8") == original


def test_apply_patch_duplicate_diagnostics_have_exact_bounded_ranges(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    original = "\n".join(
        [
            "line 1",
            "target",
            "value",
            "line 4",
            "line 5",
            "target",
            "value",
            "line 8",
            "target",
            "value",
            "line 11",
            "line 12",
            "target",
            "value",
        ]
    )
    file_path.write_text(original, encoding="utf-8")

    result = apply_patch(tmp_path, str(file_path), "target\nvalue", "changed")

    assert result["error"] == "old_text_not_unique"
    assert result["occurrences"] == 4
    assert len(result["matches"]) == 3
    assert [
        (match["start_line"], match["end_line"]) for match in result["matches"]
    ] == [(2, 3), (6, 7), (9, 10)]
    assert result["matches"][0] == {
        "start_line": 2,
        "end_line": 3,
        "context_start_line": 1,
        "context_end_line": 5,
        "context": "line 1\ntarget\nvalue\nline 4\nline 5\n",
    }
    assert all(
        match["context_end_line"] - match["context_start_line"] + 1 <= 6
        for match in result["matches"]
    )
    assert file_path.read_text(encoding="utf-8") == original


def test_apply_patch_success_reports_affected_multiline_ranges(tmp_path: Path) -> None:
    file_path = tmp_path / "input.txt"
    file_path.write_text("before\nold one\nold two\nafter\n", encoding="utf-8")

    result = apply_patch(
        tmp_path,
        str(file_path),
        "old one\nold two",
        "new one\nnew two\nnew three",
    )

    assert result["start_line"] == 2
    assert result["end_line_before"] == 3
    assert result["end_line_after"] == 4
    assert file_path.read_text(encoding="utf-8") == (
        "before\nnew one\nnew two\nnew three\nafter\n"
    )


def test_builtin_tool_descriptions_contain_only_mechanical_guidance() -> None:
    descriptions = [entry["definition"]()["function"]["description"] for entry in TOOLS.values()]

    assert len(descriptions) == 4
    assert all("action note" not in description.lower() for description in descriptions)
    assert all("before calling" not in description.lower() for description in descriptions)


def test_apply_patch_requires_absolute_path(tmp_path: Path) -> None:
    result = apply_patch(tmp_path, "input.txt", "old", "new")

    assert result == {
        "ok": False,
        "tool": "apply_patch",
        "path": "input.txt",
        "error": "path_not_absolute",
    }


def test_apply_patch_schema_distinguishes_normal_and_candidate_calls() -> None:
    parameters = TOOLS["apply_patch"]["definition"]()["function"]["parameters"]

    assert parameters["properties"] == {
        "path": {
            "type": "string",
            "description": "Absolute path to the file",
        },
        "old_text": {
            "type": "string",
            "description": "Exact text currently in the file",
        },
        "new_text": {
            "type": "string",
            "description": "Replacement text",
        },
        "match_id": {
            "type": "string",
            "description": "Run-local candidate ID returned by a failed patch",
        },
    }
    assert parameters["anyOf"] == [
        {"required": ["path", "old_text", "new_text"]},
        {"required": ["match_id"]},
    ]
    assert parameters["additionalProperties"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"path": "x", "old_text": "old"},
    ],
)
def test_apply_patch_rejects_malformed_request_forms(
    tmp_path: Path,
    kwargs: dict,
) -> None:
    result = apply_patch(tmp_path, **kwargs)

    assert result["ok"] is False
    assert result["error"] == "invalid_arguments"


def test_run_command_timeout_returns_normal_failure_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def raise_timeout(*args, **kwargs):
        raise TimeoutExpired(cmd="sleep 1", timeout=0.01, output="partial output")

    monkeypatch.setattr(run_command_module.subprocess, "run", raise_timeout)

    result = run_command(tmp_path, "sleep 1", verification=True)

    assert result["ok"] is False
    assert result["timed_out"] is True
    assert result["tool"] == "run_command"
    assert result["command"] == "sleep 1"
    assert result["verification"] is True
    assert result["failure_class"] == "timeout"


def test_run_command_classifies_powershell_invalid_separator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from squid_core.platform_context import PlatformContext

    class Completed:
        returncode = 1
        stdout = (
            "At line:1 char:10\n"
            "+ Get-Date && Get-Date\n"
            "+          ~~\n"
            "The token '&&' is not a valid statement separator in this version.\n"
        )

    context = PlatformContext("Windows", "PowerShell", "powershell", "\\", True)
    monkeypatch.setattr(run_command_module.subprocess, "run", lambda *args, **kwargs: Completed())

    result = run_command(tmp_path, "Get-Date && Get-Date", platform_context=context)

    assert result["failure_class"] == "shell_syntax_error"
    assert result["shell"] == "PowerShell"
    assert result["platform"] == "Windows"
    assert result["output"] == Completed.stdout


def test_run_command_classifies_recognizable_missing_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from squid_core.platform_context import PlatformContext

    class Completed:
        returncode = 1
        stdout = (
            "missing-tool : The term 'missing-tool' is not recognized as the name "
            "of a cmdlet, function, script file, or operable program.\n"
            "    + CategoryInfo : ObjectNotFound: (missing-tool:String) [], "
            "CommandNotFoundException\n"
        )

    context = PlatformContext("Windows", "PowerShell", "powershell", "\\", True)
    monkeypatch.setattr(run_command_module.subprocess, "run", lambda *args, **kwargs: Completed())

    result = run_command(tmp_path, "missing-tool", platform_context=context)

    assert result["failure_class"] == "command_not_found"


def test_run_command_keeps_ordinary_project_failure_generic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from squid_core.platform_context import PlatformContext

    class Completed:
        returncode = 1
        stdout = "FAILED tests/test_widget.py - AssertionError: command not found in message\n"

    context = PlatformContext("Linux", "bash", "/bin/bash", "/", False)
    monkeypatch.setattr(run_command_module.subprocess, "run", lambda *args, **kwargs: Completed())

    result = run_command(tmp_path, "pytest -q", platform_context=context)

    assert result["failure_class"] == "process_failed"
    assert result["output"] == Completed.stdout


def test_run_command_uses_selected_powershell_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from squid_core.platform_context import PlatformContext

    calls = []

    class Completed:
        returncode = 0
        stdout = "ok\n"

    monkeypatch.setattr(
        run_command_module,
        "detect_platform_context",
        lambda: PlatformContext("Windows", "PowerShell", r"C:\Program Files\PowerShell\pwsh.exe", "\\", True),
    )
    monkeypatch.setattr(
        run_command_module.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Completed(),
    )

    result = run_command(tmp_path, "Get-ChildItem")

    args, kwargs = calls[0]
    assert args[0] == [
        r"C:\Program Files\PowerShell\pwsh.exe",
        "-NoProfile",
        "-Command",
        "Get-ChildItem",
    ]
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == tmp_path
    assert kwargs["timeout"] == 15
    assert result["ok"] is True


def test_run_command_uses_supplied_context_without_redetecting(monkeypatch, tmp_path: Path) -> None:
    from squid_core.platform_context import PlatformContext

    calls = []

    class Completed:
        returncode = 0
        stdout = "ok\n"

    def fail_detection():
        raise AssertionError("platform should not be redetected")

    context = PlatformContext("Linux", "bash", "/bin/bash", "/", False)
    monkeypatch.setattr(run_command_module, "detect_platform_context", fail_detection)
    monkeypatch.setattr(
        run_command_module.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Completed(),
    )

    result = run_command(tmp_path, "printf ok", platform_context=context)

    assert calls[0][0][0] == "printf ok"
    assert calls[0][1]["shell"] is True
    assert result["ok"] is True

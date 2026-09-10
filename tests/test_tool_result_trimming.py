"""Tests for request-only trimming of older canonical tool results."""

import copy
import json
from types import SimpleNamespace

from squid_core.agent_loop import AgentLoop
from squid_core.settings import ToolResultTrimmingSettings
from squid_core.tool_result_trimming import render_messages_for_model
from squid_core.tools import ToolResults


def _tool_turn(call_id: str, name: str, result: dict) -> list[dict]:
    action = {
        "tool": name,
        "tool_call_id": call_id,
        "args": {},
    }
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
            ],
        },
        ToolResults().message_from_action_result(action, result),
    ]


def _result(message: dict) -> dict:
    return json.loads(message["content"])


def test_newest_results_remain_exactly_model_visible() -> None:
    messages = [
        *_tool_turn(
            "old",
            "read_file",
            {"ok": True, "tool": "read_file", "content": "o" * 40},
        ),
        *_tool_turn(
            "recent-1",
            "read_file",
            {"ok": True, "tool": "read_file", "content": "a" * 40},
        ),
        *_tool_turn(
            "recent-2",
            "run_command",
            {"ok": True, "tool": "run_command", "output": "b" * 40},
        ),
    ]
    settings = ToolResultTrimmingSettings(
        recent_full_results=2,
        read_old_content_chars=10,
    )

    rendered = render_messages_for_model(messages, settings)

    assert rendered[-3:] == messages[-3:]
    assert rendered[-1]["content"] == messages[-1]["content"]
    assert rendered[-3]["content"] == messages[-3]["content"]


def test_old_read_content_is_bounded_and_metadata_survives() -> None:
    canonical_result = {
        "ok": True,
        "tool": "read_file",
        "path": "C:/repo/example.py",
        "content": "0123456789" * 10,
        "content_truncated": True,
        "content_original_chars": 400,
        "content_returned_chars": 100,
        "start_line": 1,
        "end_line": 20,
        "total_lines": 40,
        "returned_line_ranges": [{"start_line": 1, "end_line": 20}],
    }
    messages = _tool_turn("read", "read_file", canonical_result)

    rendered = render_messages_for_model(
        messages,
        ToolResultTrimmingSettings(recent_full_results=0, read_old_content_chars=30),
    )
    result = _result(rendered[-1])

    assert len(result["content"]) == 30
    assert result["path"] == canonical_result["path"]
    assert result["start_line"] == 1
    assert result["end_line"] == 20
    assert result["total_lines"] == 40
    assert result["content_truncated"] is True
    assert result["returned_line_ranges"] == canonical_result["returned_line_ranges"]


def test_zero_read_limit_omits_source_but_preserves_metadata() -> None:
    messages = _tool_turn(
        "read",
        "read_file",
        {
            "ok": True,
            "tool": "read_file",
            "path": "C:/repo/secret.py",
            "content": "SOURCE_TEXT_MUST_DISAPPEAR",
            "start_line": 7,
            "end_line": 9,
            "total_lines": 12,
        },
    )

    result = _result(
        render_messages_for_model(
            messages,
            ToolResultTrimmingSettings(recent_full_results=0, read_old_content_chars=0),
        )[-1]
    )

    assert "SOURCE_TEXT_MUST_DISAPPEAR" not in result["content"]
    assert "omitted" in result["content"]
    assert result["path"] == "C:/repo/secret.py"
    assert (result["start_line"], result["end_line"], result["total_lines"]) == (
        7,
        9,
        12,
    )


def test_old_command_output_is_bounded_with_failure_metadata() -> None:
    messages = _tool_turn(
        "command",
        "run_command",
        {
            "ok": False,
            "tool": "run_command",
            "command": "pytest",
            "output": "failure\n" * 100,
            "returncode": 2,
            "timed_out": False,
            "failure_class": "process_failed",
            "shell": "powershell",
            "platform": "windows",
        },
    )

    result = _result(
        render_messages_for_model(
            messages,
            ToolResultTrimmingSettings(
                recent_full_results=0, command_old_output_chars=45
            ),
        )[-1]
    )

    assert len(result["output"]) == 45
    assert result["returncode"] == 2
    assert result["failure_class"] == "process_failed"
    assert result["shell"] == "powershell"
    assert result["platform"] == "windows"


def test_old_failed_patch_bounds_diagnostics_without_losing_candidate_ids() -> None:
    messages = _tool_turn(
        "patch",
        "apply_patch",
        {
            "ok": False,
            "tool": "apply_patch",
            "path": "C:/repo/example.py",
            "error": "old_text_not_unique",
            "candidates": [
                {
                    "match_id": "m1",
                    "start_line": 10,
                    "end_line": 12,
                    "context": "large diagnostic " * 100,
                    "text": "candidate source " * 100,
                }
            ],
        },
    )

    result = _result(
        render_messages_for_model(
            messages,
            ToolResultTrimmingSettings(
                recent_full_results=0, patch_old_diagnostic_chars=35
            ),
        )[-1]
    )
    candidate = result["candidates"][0]

    assert candidate["match_id"] == "m1"
    assert candidate["start_line"] == 10
    assert candidate["end_line"] == 12
    retained_diagnostics = candidate.get("context", "") + candidate.get("text", "")
    assert len(retained_diagnostics) <= 35
    assert result["model_diagnostic_note"] == "[older patch diagnostic omitted]"


def test_rendering_never_mutates_canonical_messages_or_results() -> None:
    canonical_result = {
        "ok": True,
        "tool": "read_file",
        "path": "C:/repo/example.py",
        "content": "unchanged canonical source" * 20,
    }
    messages = _tool_turn("read", "read_file", canonical_result)
    before = copy.deepcopy(messages)

    rendered = render_messages_for_model(
        messages,
        ToolResultTrimmingSettings(recent_full_results=0, read_old_content_chars=10),
    )

    assert messages == before
    assert canonical_result["content"] == "unchanged canonical source" * 20
    assert rendered[-1] is not messages[-1]


def test_agent_loop_sends_trimmed_view_but_keeps_session_history_canonical() -> None:
    messages = _tool_turn(
        "read",
        "read_file",
        {"ok": True, "tool": "read_file", "content": "canonical source" * 50},
    )
    before = copy.deepcopy(messages)

    class RecordingAdapter:
        def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
            self.messages = messages
            return {"message": {"role": "assistant", "content": "done"}}

    adapter = RecordingAdapter()
    loop = AgentLoop(
        session=SimpleNamespace(messages=messages, repo_root="C:/repo"),
        model_adapter=adapter,
        tool_executor=object(),
        tool_results=ToolResults(),
        agent=object(),
        display=object(),
        action_preflight=object(),
        tool_result_trimming=ToolResultTrimmingSettings(
            recent_full_results=0, read_old_content_chars=25
        ),
    )

    loop._respond([])

    assert messages == before
    assert len(_result(adapter.messages[-1])["content"]) == 25


def test_disabled_trimming_reproduces_current_messages() -> None:
    messages = _tool_turn(
        "read",
        "read_file",
        {"ok": True, "tool": "read_file", "content": "full source" * 100},
    )

    rendered = render_messages_for_model(
        messages,
        ToolResultTrimmingSettings(enabled=False, recent_full_results=0),
    )

    assert rendered == messages
    assert rendered[-1]["content"] == messages[-1]["content"]


def test_trimming_preserves_assistant_tool_result_pairing() -> None:
    messages = _tool_turn(
        "paired-call",
        "run_command",
        {"ok": True, "tool": "run_command", "output": "x" * 100},
    )

    rendered = render_messages_for_model(
        messages,
        ToolResultTrimmingSettings(
            recent_full_results=0, command_old_output_chars=20
        ),
    )

    assert rendered[0]["tool_calls"][0]["id"] == "paired-call"
    assert rendered[1]["tool_call_id"] == "paired-call"
    assert len(_result(rendered[1])["output"]) == 20


def test_old_write_payload_is_omitted_when_present_but_status_survives() -> None:
    messages = _tool_turn(
        "write",
        "write_file",
        {
            "ok": True,
            "tool": "write_file",
            "path": "C:/repo/example.py",
            "characters_written": 500,
            "content": "written source" * 40,
        },
    )

    result = _result(
        render_messages_for_model(
            messages,
            ToolResultTrimmingSettings(recent_full_results=0),
        )[-1]
    )

    assert "written source" not in result["content"]
    assert "omitted" in result["content"]
    assert result["ok"] is True
    assert result["path"] == "C:/repo/example.py"
    assert result["characters_written"] == 500


def test_unknown_tools_are_left_unchanged() -> None:
    messages = _tool_turn(
        "future",
        "future_tool",
        {"ok": True, "tool": "future_tool", "payload": "x" * 10_000},
    )

    rendered = render_messages_for_model(
        messages,
        ToolResultTrimmingSettings(recent_full_results=0),
    )

    assert rendered == messages
    assert rendered[-1] is messages[-1]

"""Tests for Code Squid's authoritative compaction context provider."""

import json

from code_squid.compaction_context import (
    _MAX_OUTPUT_EXCERPT_CHARS,
    _output_excerpt,
    authoritative_compaction_context,
)


def _tool_event(
    call_id: str,
    tool: str,
    arguments: dict,
    result: dict,
) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool,
                        "arguments": json.dumps(arguments),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(result),
        },
    ]


def _verification(
    call_id: str,
    command: str,
    *,
    ok: bool,
    output: str = "",
) -> list[dict]:
    return _tool_event(
        call_id,
        "run_command",
        {"command": command, "verification": True},
        {
            "ok": ok,
            "tool": "run_command",
            "command": command,
            "verification": True,
            "output": output,
            "returncode": 0 if ok else 1,
        },
    )


def _mutation(call_id: str, path: str = "script.js") -> list[dict]:
    return _tool_event(
        call_id,
        "apply_patch",
        {"path": path},
        {
            "ok": True,
            "tool": "apply_patch",
            "path": path,
            "replacements": 1,
            "start_line": 2,
            "end_line_after": 3,
        },
    )


def test_latest_verification_pass_is_authoritative() -> None:
    context = authoritative_compaction_context(
        _verification("verify-1", "node --check script.js", ok=True)
    )

    assert context is not None
    assert "Latest verification:" in context
    assert "`node --check script.js`" in context
    assert "- PASSED" in context
    assert "No known direct mutation occurred after this verification." in context


def test_short_failed_command_output_is_preserved_as_is() -> None:
    output = (
        "C:\\repo\\script.js:1847\n\n"
        "SyntaxError: Unexpected end of input\n"
        "    at wrapSafe (...)\n"
        "    at checkSyntax (...)\n\n"
        "Node.js v22.14.0"
    )

    context = authoritative_compaction_context(
        _verification("verify-1", "node --check script.js", ok=False, output=output)
    )

    assert context is not None
    assert "- FAILED" in context
    assert output in context
    assert "Latest unresolved tool failure:" in context


def test_long_failed_command_output_preserves_bounded_head_and_tail() -> None:
    output = "BEGINNING\n" + ("middle output\n" * 100) + "END"

    excerpt = _output_excerpt({"output": output})
    context = authoritative_compaction_context(
        _verification("verify-1", "npm test", ok=False, output=output)
    )

    assert excerpt.startswith("BEGINNING\n")
    assert excerpt.endswith("END")
    assert "\n... omitted ...\n" in excerpt
    assert len(excerpt) <= _MAX_OUTPUT_EXCERPT_CHARS
    assert context is not None
    assert excerpt in context


def test_successful_verification_omits_ordinary_command_output() -> None:
    output = "All 127 tests passed in 4.2 seconds"

    context = authoritative_compaction_context(
        _verification("verify-1", "pytest", ok=True, output=output)
    )

    assert context is not None
    assert "- PASSED" in context
    assert output not in context


def test_mutation_after_verification_marks_verification_stale() -> None:
    context = authoritative_compaction_context(
        [
            *_verification("verify-1", "node --check script.js", ok=True),
            *_mutation("patch-1"),
        ]
    )

    assert context is not None
    assert "Latest known direct mutation:" in context
    assert "known direct mutation occurred after this verification" in context
    assert "does not describe the latest known directly edited state" in context


def test_verification_after_mutation_is_current_for_known_direct_mutations() -> None:
    context = authoritative_compaction_context(
        [
            *_mutation("patch-1"),
            *_verification("verify-1", "node --check script.js", ok=True),
        ]
    )

    assert context is not None
    assert "No known direct mutation occurred after this verification." in context


def test_later_verification_supersedes_earlier_verification() -> None:
    context = authoritative_compaction_context(
        [
            *_verification(
                "verify-1",
                "node --check old.js",
                ok=False,
                output="SyntaxError: old failure",
            ),
            *_verification("verify-2", "npm test", ok=True),
        ]
    )

    assert context is not None
    assert "`npm test`" in context
    assert "old failure" not in context
    assert "Latest unresolved tool failure:" not in context


def test_successful_retry_removes_recovered_tool_failure() -> None:
    failed = _tool_event(
        "patch-1",
        "apply_patch",
        {"path": "script.js"},
        {
            "ok": False,
            "tool": "apply_patch",
            "path": "script.js",
            "error": "old_text_not_found",
        },
    )

    context = authoritative_compaction_context([*failed, *_mutation("patch-2")])

    assert context is not None
    assert "Latest unresolved tool failure:" not in context
    assert "old_text_not_found" not in context


def test_context_does_not_claim_filesystem_truth_or_task_state() -> None:
    context = authoritative_compaction_context(_mutation("patch-1"))

    assert context is not None
    assert "known direct mutation" in context
    assert "changed files" not in context.lower()
    assert "task complete" not in context.lower()
    assert "next step" not in context.lower()

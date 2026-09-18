"""Tests for Code Squid's authoritative compaction context provider."""

import json
from types import SimpleNamespace

from code_squid.compaction_context import (
    CodeSquidCompactionContextProvider,
    _MAX_OUTPUT_EXCERPT_CHARS,
    _output_excerpt,
    authoritative_compaction_context,
)
from squid_core.compaction import Compactor


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


def _read(call_id: str, path: str = "script.js", *, ok: bool = True) -> list[dict]:
    return _tool_event(
        call_id,
        "read_file",
        {"path": path},
        {
            "ok": ok,
            "tool": "read_file",
            "path": path,
            **({"content": "contents"} if ok else {"error": "not found"}),
        },
    )


def test_provider_removes_matching_canonical_suffix() -> None:
    summarized = _mutation("patch-1")
    preserved = _verification("verify-1", "pytest", ok=True)
    provider = CodeSquidCompactionContextProvider(
        lambda: [*summarized, *preserved]
    )

    context = provider(preserved)

    assert context is not None
    assert "apply_patch: 1 successful, 0 failed" in context
    assert "Latest verification:\n\n- No verification occurred." in context
    assert "`pytest`" not in context


def test_provider_returns_none_when_preserved_tail_does_not_match() -> None:
    provider = CodeSquidCompactionContextProvider(lambda: _mutation("patch-1"))

    assert provider(_read("read-1")) is None


def test_read_only_history_reports_activity_and_explicit_none_states() -> None:
    context = authoritative_compaction_context(
        [*_read("read-1"), *_read("read-2"), *_read("read-3", ok=False)]
    )

    assert context is not None
    assert "read_file: 2 successful, 1 failed" in context
    assert "apply_patch: 0 successful, 0 failed" in context
    assert "write_file: 0 successful, 0 failed" in context
    assert "run_command: 0 successful, 0 failed" in context
    assert "No known direct mutation occurred." in context
    assert "No verification occurred." in context
    assert "No files changed" not in context
    assert "The work is unverified" not in context


def test_preserved_recent_tool_activity_is_excluded_from_facts() -> None:
    summarized = _read("read-old", "old.py")
    preserved = _mutation("patch-recent", "recent.py")
    provider = CodeSquidCompactionContextProvider(
        lambda: [*summarized, *preserved]
    )

    context = provider(preserved)

    assert context is not None
    assert "read_file: 1 successful, 0 failed" in context
    assert "apply_patch: 0 successful, 0 failed" in context
    assert "recent.py" not in context
    assert "No known direct mutation occurred." in context


def test_repeated_compactions_use_original_canonical_messages() -> None:
    class Adapter:
        def __init__(self) -> None:
            self.requests = []

        def complete_text(self, messages: list[dict]) -> dict:
            self.requests.append(messages)
            return {"content": "summary", "usage": None}

    compaction_settings = SimpleNamespace(
        enabled=True,
        trigger_input_tokens=1,
        compact_fraction=0.5,
        min_recent_chunks=1,
    )
    canonical_messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        *_mutation("patch-1", "first.py"),
        *_read("read-1", "middle.py"),
        {"role": "user", "content": "recent request"},
    ]
    current_session = SimpleNamespace(messages=list(canonical_messages))
    provider = CodeSquidCompactionContextProvider(lambda: canonical_messages)

    first_adapter = Adapter()
    Compactor(
        compaction_settings,
        first_adapter,
        context_provider=provider,
    ).maybe_compact(current_session)

    new_messages = [
        *_mutation("patch-2", "second.py"),
        *_read("read-2", "recent.py"),
        {"role": "user", "content": "newest request"},
    ]
    canonical_messages.extend(new_messages)
    current_session.messages.extend(new_messages)

    second_adapter = Adapter()
    Compactor(
        compaction_settings,
        second_adapter,
        context_provider=provider,
    ).maybe_compact(current_session)

    second_prompt = second_adapter.requests[0][1]["content"]
    assert "`first.py`" in second_prompt
    assert "second.py" not in second_prompt
    assert "recent.py" not in second_prompt
    assert "`first.py`" in current_session.messages[2]["content"]


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

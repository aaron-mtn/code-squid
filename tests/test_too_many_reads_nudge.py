"""Focused coverage for the behavioral too-many-reads nudge."""

from dataclasses import dataclass

import pytest

from squid_core.hooks import (
    BeforeRunContext,
    CompactionAppliedContext,
    HookRunner,
    TOO_MANY_READS_GUIDANCE,
    TOO_MANY_READS_STRONG_GUIDANCE,
    TooManyReadsNudge,
)


@dataclass(frozen=True)
class _Context:
    action: dict
    result: dict


def _result(
    hook: TooManyReadsNudge,
    tool: str,
    *,
    ok: bool = True,
    output: str = "source",
):
    return hook.tool_result(
        _Context(
            action={"tool": tool, "args": {}},
            result={"ok": ok, "tool": tool, "output": output},
        )
    )


def _successful_reads(hook: TooManyReadsNudge, count: int):
    return [_result(hook, "read_file") for _ in range(count)]


def test_third_successful_read_produces_first_nudge() -> None:
    responses = _successful_reads(TooManyReadsNudge(), 3)

    assert responses[:2] == [None, None]
    assert responses[2].additional_context == TOO_MANY_READS_GUIDANCE


def test_fifth_and_later_successful_reads_produce_strong_nudge() -> None:
    hook = TooManyReadsNudge()
    responses = _successful_reads(hook, 6)

    assert responses[4].additional_context == TOO_MANY_READS_STRONG_GUIDANCE
    assert responses[5].additional_context == TOO_MANY_READS_STRONG_GUIDANCE


def test_neutral_commands_do_not_make_reads_consecutive() -> None:
    hook = TooManyReadsNudge()
    assert _result(hook, "read_file") is None
    assert _result(hook, "run_command") is None
    assert _result(hook, "read_file") is None
    assert _result(hook, "run_command") is None

    assert _result(hook, "read_file").additional_context == TOO_MANY_READS_GUIDANCE


@pytest.mark.parametrize("mutation", ["apply_patch", "write_file"])
def test_successful_mutation_resets_read_count(mutation: str) -> None:
    hook = TooManyReadsNudge()
    _successful_reads(hook, 2)
    assert _result(hook, mutation) is None

    assert _successful_reads(hook, 2) == [None, None]
    assert _result(hook, "read_file").additional_context == TOO_MANY_READS_GUIDANCE


def test_failed_mutation_does_not_reset_read_count() -> None:
    hook = TooManyReadsNudge()
    _successful_reads(hook, 2)
    assert _result(hook, "apply_patch", ok=False) is None

    assert _result(hook, "read_file").additional_context == TOO_MANY_READS_GUIDANCE


def test_failed_read_neither_increments_nor_resets() -> None:
    hook = TooManyReadsNudge()
    _successful_reads(hook, 2)
    assert _result(hook, "read_file", ok=False) is None

    assert _result(hook, "read_file").additional_context == TOO_MANY_READS_GUIDANCE


def test_compaction_does_not_reset_read_count() -> None:
    hook = TooManyReadsNudge()
    runner = HookRunner([hook])
    _successful_reads(hook, 2)
    runner.compaction_applied(CompactionAppliedContext(None, "."))

    assert _result(hook, "read_file").additional_context == TOO_MANY_READS_GUIDANCE


def test_before_run_resets_read_count() -> None:
    hook = TooManyReadsNudge()
    _successful_reads(hook, 2)
    hook.before_run(BeforeRunContext(None, ".", "task"))

    assert _successful_reads(hook, 2) == [None, None]


def test_hook_does_not_modify_read_tool_output() -> None:
    hook = TooManyReadsNudge(first_nudge_reads=1, strong_nudge_reads=2)
    result = {"ok": True, "tool": "read_file", "output": "unaltered source"}

    response = hook.tool_result(
        _Context(action={"tool": "read_file", "args": {}}, result=result)
    )

    assert response.updated_tool_output is None
    assert response.block is False
    assert result == {
        "ok": True,
        "tool": "read_file",
        "output": "unaltered source",
    }


@pytest.mark.parametrize(
    ("first", "strong"),
    [(0, 2), (2, 2), (3, 2)],
)
def test_thresholds_are_validated(first: int, strong: int) -> None:
    with pytest.raises(ValueError):
        TooManyReadsNudge(first_nudge_reads=first, strong_nudge_reads=strong)

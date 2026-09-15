"""Focused regressions for self-contained post-verification guidance."""

from dataclasses import dataclass

import pytest

from squid_core.hooks import (
    BeforeRunContext,
    HookRunner,
    POST_VERIFICATION_GUIDANCE,
    PostVerificationNudge,
    RepeatedReadNudge,
    ToolResultContext,
)


@dataclass(frozen=True)
class _Context:
    action: dict
    result: dict


def _context(
    tool: str,
    *,
    ok: bool = True,
    command: str | None = None,
    verification: bool | None = None,
    **result_fields,
) -> _Context:
    args = {}
    result = {"ok": ok, "tool": tool, **result_fields}
    if command is not None:
        args["command"] = command
        result["command"] = command
    if verification is not None:
        args["verification"] = verification
        result["verification"] = verification
    return _Context(action={"tool": tool, "args": args}, result=result)


def _runner(threshold: int = 3) -> tuple[HookRunner, PostVerificationNudge]:
    nudge = PostVerificationNudge(threshold=threshold)
    return HookRunner([nudge]), nudge


def _observe(runner: HookRunner, context: _Context):
    return runner.tool_result(
        ToolResultContext(None, ".", context.action, context.result)
    )


def test_successful_explicit_verification_activates_tracking() -> None:
    runner, nudge = _runner()
    response = _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    assert nudge._verification_current is True
    assert nudge._verification_signatures == {"pytest focused.py"}
    assert nudge._no_progress_count == 0
    assert response.additional_context == ""


def test_failed_explicit_verification_disables_tracking() -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))
    response = _observe(
        runner,
        _context(
            "run_command",
            ok=False,
            command="pytest broader.py",
            verification=True,
        ),
    )
    assert nudge._verification_current is False
    # Failed checks do not erase signatures for an unchanged implementation.
    assert nudge._verification_signatures == {"pytest focused.py"}
    assert nudge._no_progress_count == 0
    assert response.additional_context == ""


@pytest.mark.parametrize("tool", ["apply_patch", "write_file"])
def test_successful_mutation_invalidates_verification(tool: str) -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))
    _observe(runner, _context(tool))
    assert nudge._verification_current is False
    assert nudge._verification_signatures == set()
    assert nudge._no_progress_count == 0


def test_failed_mutation_does_not_invalidate_verification() -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("apply_patch", ok=False))
    assert nudge._verification_current is True
    assert nudge._verification_signatures == {"pytest focused.py"}


def test_new_successful_verification_signature_resets_streak() -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))
    response = _observe(
        runner,
        _context("run_command", command="pytest", verification=True),
    )
    assert nudge._verification_signatures == {"pytest focused.py", "pytest"}
    assert nudge._no_progress_count == 0
    assert response.additional_context == ""


def test_duplicate_successful_verification_increments_streak() -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="  pytest focused.py\r\n", verification=True),
    )
    response = _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    assert nudge._verification_signatures == {"pytest focused.py"}
    assert nudge._no_progress_count == 1
    assert response.additional_context == ""


def test_successful_reads_after_verification_increment_streak() -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))
    assert nudge._no_progress_count == 1


def test_already_covered_read_counts_without_stacking_guidance() -> None:
    runner, nudge = _runner(threshold=1)
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    response = _observe(runner, _context("read_file", already_covered=True))
    assert nudge._no_progress_count == 1
    assert response.additional_context == ""


def test_later_action_uses_count_accumulated_by_already_covered_read() -> None:
    runner, nudge = _runner(threshold=2)
    verification = _context(
        "run_command", command="pytest focused.py", verification=True
    )
    _observe(runner, verification)
    _observe(runner, _context("read_file", already_covered=True))
    response = _observe(runner, verification)
    assert response.additional_context == POST_VERIFICATION_GUIDANCE
    assert nudge._no_progress_count == 0


def test_repeated_read_guidance_is_not_stacked_with_post_verification() -> None:
    post_verification = PostVerificationNudge(threshold=2)
    runner = HookRunner([RepeatedReadNudge(), post_verification])
    verification = _context(
        "run_command", command="pytest focused.py", verification=True
    )
    read = _Context(
        action={"tool": "read_file", "args": {"path": "a.py"}},
        result={
            "ok": True,
            "tool": "read_file",
            "path": "a.py",
            "content": "source",
            "start_line": 1,
            "end_line": 10,
        },
    )
    _observe(runner, verification)
    _observe(runner, read)

    repeated_read = _observe(runner, read)

    assert repeated_read.updated_tool_output["already_covered"] is True
    assert (
        "You already read this unchanged section"
        in repeated_read.additional_context
    )
    assert POST_VERIFICATION_GUIDANCE not in repeated_read.additional_context
    assert post_verification._no_progress_count == 2

    later = _observe(runner, verification)
    assert later.additional_context == POST_VERIFICATION_GUIDANCE


def test_threshold_guidance_and_reset_remain_equivalent() -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    assert _observe(runner, _context("read_file")).additional_context == ""
    assert _observe(runner, _context("read_file")).additional_context == ""
    response = _observe(runner, _context("read_file"))
    assert response.additional_context == POST_VERIFICATION_GUIDANCE
    assert response.updated_tool_output["ok"] is True
    assert nudge._no_progress_count == 0


def test_new_run_resets_all_post_verification_state() -> None:
    runner, nudge = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))
    runner.before_run(BeforeRunContext(None, ".", "test"))
    assert nudge._verification_current is False
    assert nudge._verification_signatures == set()
    assert nudge._no_progress_count == 0


def test_non_verification_command_is_conservatively_unclassified() -> None:
    runner, nudge = _runner(threshold=1)
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    response = _observe(
        runner,
        _context("run_command", command="custom command", verification=False),
    )
    assert response.additional_context == ""
    assert nudge._verification_current is True
    assert nudge._no_progress_count == 0

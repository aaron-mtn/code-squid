"""Focused regressions for post-verification progress and guidance."""

from dataclasses import dataclass

from squid_core.hooks import (
    HookRunner,
    POST_VERIFICATION_GUIDANCE,
    PostVerificationNudge,
    ToolResultContext,
    VerificationState,
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


def _runner(threshold: int = 3) -> tuple[HookRunner, VerificationState]:
    state = VerificationState()
    return HookRunner([state, PostVerificationNudge(state, threshold=threshold)]), state


def _observe(runner: HookRunner, context: _Context):
    return runner.tool_result(
        ToolResultContext(None, ".", context.action, context.result)
    )


def test_successful_verification_is_current_without_a_nudge() -> None:
    runner, state = _runner()
    _observe(runner, _context("apply_patch"))

    response = _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )

    assert state.verification_current is True
    assert state.verification_signatures == frozenset({"pytest focused.py"})
    assert state.post_verify_no_progress_count == 0
    assert response.additional_context == ""


def test_distinct_successful_verification_is_progress_and_resets_counter() -> None:
    runner, state = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))

    response = _observe(
        runner,
        _context("run_command", command="pytest", verification=True),
    )

    assert state.verification_signatures == frozenset(
        {"pytest focused.py", "pytest"}
    )
    assert state.post_verify_no_progress_count == 0
    assert response.additional_context == ""


def test_duplicate_successful_verification_counts_as_no_progress() -> None:
    runner, state = _runner()
    verification = _context(
        "run_command", command="  pytest focused.py\r\n", verification=True
    )
    _observe(runner, verification)

    response = _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )

    assert state.post_verify_no_progress_count == 1
    assert response.additional_context == ""


def test_three_observational_reads_emit_strong_advisory() -> None:
    runner, state = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )

    assert _observe(runner, _context("read_file")).additional_context == ""
    assert _observe(runner, _context("read_file")).additional_context == ""
    response = _observe(runner, _context("read_file"))

    assert response.additional_context == POST_VERIFICATION_GUIDANCE
    assert response.updated_tool_output["ok"] is True
    assert state.post_verify_no_progress_count == 0


def test_edit_after_read_invalidates_verification_and_resets_state() -> None:
    runner, state = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))

    _observe(runner, _context("apply_patch"))

    assert state.verification_current is False
    assert state.verification_signatures == frozenset()
    assert state.post_verify_no_progress_count == 0


def test_failed_verification_is_actionable_and_resets_idle_streak() -> None:
    runner, state = _runner()
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

    assert state.verification_current is False
    assert state.post_verify_no_progress_count == 0
    assert response.additional_context == ""


def test_state_resets_cleanly_between_runs() -> None:
    runner, state = _runner()
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )
    _observe(runner, _context("read_file"))

    state.before_run(None)

    assert state.verification_current is False
    assert state.verification_signatures == frozenset()
    assert state.post_verify_no_progress_count == 0


def test_masked_repeated_read_defers_to_existing_specific_guidance() -> None:
    runner, state = _runner(threshold=1)
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )

    response = _observe(runner, _context("read_file", already_covered=True))

    assert response.additional_context == ""
    assert state.post_verify_no_progress_count == 0


def test_non_verification_command_is_conservatively_unclassified() -> None:
    runner, state = _runner(threshold=1)
    _observe(
        runner,
        _context("run_command", command="pytest focused.py", verification=True),
    )

    response = _observe(
        runner,
        _context("run_command", command="custom command", verification=False),
    )

    assert response.additional_context == ""
    assert state.verification_current is True
    assert state.post_verify_no_progress_count == 0

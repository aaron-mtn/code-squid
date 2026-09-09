"""Focused coverage for the conservative runtime no-progress nudge."""

from dataclasses import dataclass

from squid_core.hooks import RepeatedFailureNudge


GUIDANCE = "Choose a materially different next action."


@dataclass(frozen=True)
class _Context:
    action: dict | None = None
    result: dict | None = None


def _failure(
    hook: RepeatedFailureNudge,
    *,
    args: dict | None = None,
    error: str = "not_found",
) -> None:
    hook.tool_result(
        _Context(
            action={"tool": "edit", "args": args or {"path": "a.py", "old": "x"}},
            result={"ok": False, "error": error},
        )
    )


def _next_nudge(hook: RepeatedFailureNudge):
    return hook.before_model_turn(_Context())


def test_one_failure_does_not_trigger_a_nudge() -> None:
    hook = RepeatedFailureNudge(GUIDANCE)

    _failure(hook)

    assert _next_nudge(hook) is None


def test_three_equivalent_failures_trigger_one_transient_nudge() -> None:
    hook = RepeatedFailureNudge(GUIDANCE)

    for _ in range(3):
        _failure(hook)

    nudge = _next_nudge(hook)
    assert nudge is not None
    assert nudge.body == GUIDANCE
    assert _next_nudge(hook) is None


def test_materially_changed_retry_breaks_the_repetition_pattern() -> None:
    hook = RepeatedFailureNudge(GUIDANCE)

    _failure(hook)
    _failure(hook, args={"path": "a.py", "old": "more specific x"})
    _failure(hook)

    assert _next_nudge(hook) is None


def test_different_inspections_and_successful_verification_do_not_trigger() -> None:
    hook = RepeatedFailureNudge(GUIDANCE)

    for start in (1, 20, 40):
        hook.tool_result(
            _Context(
                action={"tool": "read", "args": {"path": "a.py", "start": start}},
                result={"ok": True, "output": "current content"},
            )
        )

    assert _next_nudge(hook) is None


def test_successful_progress_resets_a_failure_streak() -> None:
    hook = RepeatedFailureNudge(GUIDANCE)
    _failure(hook)
    _failure(hook)

    hook.tool_result(
        _Context(
            action={"tool": "edit", "args": {"path": "a.py", "old": "x"}},
            result={"ok": True},
        )
    )
    _failure(hook)

    assert _next_nudge(hook) is None


def test_changed_failure_category_breaks_the_repetition_pattern() -> None:
    hook = RepeatedFailureNudge(GUIDANCE)

    _failure(hook)
    _failure(hook, error="permission_denied")
    _failure(hook)

    assert _next_nudge(hook) is None


def test_a_nudge_requires_a_fresh_threshold_before_repeating() -> None:
    hook = RepeatedFailureNudge(GUIDANCE)
    for _ in range(3):
        _failure(hook)
    assert _next_nudge(hook) is not None

    _failure(hook)
    assert _next_nudge(hook) is None

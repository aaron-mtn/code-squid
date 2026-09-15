"""Focused coverage for explicit run-local verification state."""

from dataclasses import dataclass

from squid_core.hooks import VerificationState


@dataclass(frozen=True)
class _Context:
    action: dict
    result: dict


def _observe(
    state: VerificationState,
    tool: str,
    *,
    ok: bool,
    verification: bool | None = None,
) -> None:
    result = {"ok": ok, "tool": tool}
    if verification is not None:
        result["verification"] = verification
    state.tool_result(_Context(action={"tool": tool}, result=result))


def test_successful_explicit_verification_sets_state() -> None:
    state = VerificationState()

    _observe(state, "run_command", ok=True, verification=True)

    assert state.verified_since_last_mutation is True


def test_failed_explicit_verification_does_not_set_state() -> None:
    state = VerificationState()

    _observe(state, "run_command", ok=False, verification=True)

    assert state.verified_since_last_mutation is False


def test_ordinary_successful_command_does_not_set_state() -> None:
    state = VerificationState()

    _observe(state, "run_command", ok=True, verification=False)

    assert state.verified_since_last_mutation is False

    _observe(state, "run_command", ok=True, verification=True)
    _observe(state, "run_command", ok=True, verification=False)

    assert state.verified_since_last_mutation is True


def test_reads_do_not_clear_verification_state() -> None:
    state = VerificationState()
    _observe(state, "run_command", ok=True, verification=True)

    _observe(state, "read_file", ok=True)

    assert state.verified_since_last_mutation is True


def test_successful_apply_patch_clears_verification_state() -> None:
    state = VerificationState()
    _observe(state, "run_command", ok=True, verification=True)

    _observe(state, "apply_patch", ok=True)

    assert state.verified_since_last_mutation is False


def test_successful_write_file_clears_verification_state() -> None:
    state = VerificationState()
    _observe(state, "run_command", ok=True, verification=True)

    _observe(state, "write_file", ok=True)

    assert state.verified_since_last_mutation is False


def test_failed_mutation_does_not_clear_verification_state() -> None:
    state = VerificationState()
    _observe(state, "run_command", ok=True, verification=True)

    _observe(state, "apply_patch", ok=False)

    assert state.verified_since_last_mutation is True

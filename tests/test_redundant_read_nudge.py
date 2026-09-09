"""Focused coverage for the conservative redundant-read reliability nudge."""

from dataclasses import dataclass
import os

from squid_core.hooks import HookResponse, RedundantReadNudge


@dataclass(frozen=True)
class _Context:
    action: dict
    result: dict


def _read(
    hook: RedundantReadNudge,
    path: str = "a.py",
    *,
    start: int | None = None,
    end: int | None = None,
    ok: bool = True,
    returned_ranges: list[dict] | None = None,
) -> HookResponse | None:
    args = {"path": path}
    if start is not None:
        args["start_line"] = start
    if end is not None:
        args["end_line"] = end

    result = {"ok": ok, "path": path}
    if ok:
        result.update(
            {
                "start_line": start or 1,
                "end_line": end or 200,
                "ranged": start is not None or end is not None,
            }
        )
    if returned_ranges is not None:
        result["returned_line_ranges"] = returned_ranges

    return hook.tool_result(
        _Context(
            action={"tool": "read_file", "args": args},
            result=result,
        )
    )


def _mutate(
    hook: RedundantReadNudge,
    tool: str,
    path: str,
    *,
    ok: bool = True,
) -> HookResponse | None:
    return hook.tool_result(
        _Context(
            action={"tool": tool, "args": {"path": path}},
            result={"ok": ok, "path": path},
        )
    )


def test_successful_ranged_read_records_actual_fallback_coverage() -> None:
    hook = RedundantReadNudge()

    _read(hook, start=10, end=20)

    assert hook._coverage[os.path.normcase(os.path.normpath("a.py"))] == [(10, 20)]


def test_full_file_truncated_read_records_only_returned_line_ranges() -> None:
    hook = RedundantReadNudge()
    returned = [
        {"start_line": 1, "end_line": 500},
        {"start_line": 591, "end_line": 1090},
    ]

    _read(hook, returned_ranges=returned)

    assert hook._coverage[os.path.normcase(os.path.normpath("a.py"))] == [
        (1, 500),
        (591, 1090),
    ]


def test_small_fully_covered_reads_nudge_only_on_second_occurrence() -> None:
    hook = RedundantReadNudge()
    _read(hook, returned_ranges=[{"start_line": 1, "end_line": 500}])

    assert _read(hook, start=20, end=40) is None
    assert _read(hook, start=50, end=70) == HookResponse(
        additional_context=(
            "You've repeatedly read small regions of this unchanged file that "
            "were already returned recently. Use the existing context unless "
            "a fresh read is needed for a specific reason."
        )
    )


def test_partial_overlap_is_not_fully_covered() -> None:
    hook = RedundantReadNudge()
    _read(hook, start=1, end=20)

    assert _read(hook, start=15, end=25) is None
    assert hook._redundant_count == 0


def test_nudge_resets_threshold_window() -> None:
    hook = RedundantReadNudge()
    _read(hook, start=1, end=100)
    assert _read(hook, start=1, end=10) is None
    assert _read(hook, start=11, end=20) is not None

    assert _read(hook, start=21, end=30) is None
    assert _read(hook, start=31, end=40) is not None


def test_useful_read_resets_redundant_count() -> None:
    hook = RedundantReadNudge()
    _read(hook, start=1, end=100)
    _read(hook, start=1, end=10)

    _read(hook, start=101, end=110)

    assert _read(hook, start=11, end=20) is None


def test_read_larger_than_small_threshold_never_counts() -> None:
    hook = RedundantReadNudge()
    _read(hook, returned_ranges=[{"start_line": 1, "end_line": 500}])

    assert _read(hook, start=1, end=101) is None
    assert _read(hook, start=1, end=101) is None
    assert hook._redundant_count == 0


def test_failed_read_does_not_add_coverage() -> None:
    hook = RedundantReadNudge()

    _read(hook, start=1, end=20, ok=False)

    assert hook._coverage == {}
    assert _read(hook, start=1, end=20) is None
    assert hook._redundant_count == 0


def test_successful_write_file_invalidates_only_its_target() -> None:
    hook = RedundantReadNudge()
    _read(hook, "a.py", start=1, end=20)
    _read(hook, "b.py", start=1, end=20)

    _mutate(hook, "write_file", "a.py")

    assert os.path.normcase(os.path.normpath("a.py")) not in hook._coverage
    assert os.path.normcase(os.path.normpath("b.py")) in hook._coverage
    assert _read(hook, "a.py", start=1, end=10) is None


def test_successful_apply_patch_invalidates_coverage() -> None:
    hook = RedundantReadNudge()
    _read(hook, start=1, end=20)

    _mutate(hook, "apply_patch", "a.py")

    assert hook._coverage == {}
    assert _read(hook, start=1, end=10) is None


def test_failed_mutation_does_not_invalidate_coverage() -> None:
    hook = RedundantReadNudge()
    _read(hook, start=1, end=20)

    _mutate(hook, "apply_patch", "a.py", ok=False)

    assert _read(hook, start=1, end=10) is None
    assert _read(hook, start=11, end=20) is not None


def test_before_run_resets_coverage_and_redundant_count() -> None:
    hook = RedundantReadNudge()
    _read(hook, start=1, end=20)
    _read(hook, start=1, end=10)

    hook.before_run(None)

    assert hook._coverage == {}
    assert hook._redundant_count == 0
    assert _read(hook, start=1, end=10) is None

"""Focused coverage for the repeated-read runtime nudge."""

from dataclasses import dataclass
from pathlib import Path

from squid_core.hooks import HookResponse, RepeatedReadNudge


GUIDANCE = (
    "You recently inspected most of this unchanged file range. Reuse the existing "
    "result unless you need exact current text for an edit or a specific unresolved "
    "detail."
)


@dataclass(frozen=True)
class _Context:
    action: dict
    result: dict


def _read(
    hook: RepeatedReadNudge,
    path: Path,
    *,
    returned_start: int = 1,
    returned_end: int = 100,
    requested_start: int | None = None,
    requested_end: int | None = None,
    returned_ranges: list[dict] | None = None,
    ok: bool = True,
) -> HookResponse | None:
    args = {"path": str(path)}
    if requested_start is not None:
        args["start_line"] = requested_start
    if requested_end is not None:
        args["end_line"] = requested_end

    result = {"ok": ok, "tool": "read_file", "path": str(path)}
    if ok:
        result.update({"start_line": returned_start, "end_line": returned_end})
    if returned_ranges is not None:
        result["returned_line_ranges"] = returned_ranges
    return hook.tool_result(
        _Context(action={"tool": "read_file", "args": args}, result=result)
    )


def _mutate(
    hook: RepeatedReadNudge,
    tool: str,
    path: Path,
    *,
    ok: bool = True,
) -> HookResponse | None:
    return hook.tool_result(
        _Context(
            action={"tool": tool, "args": {"path": str(path)}},
            result={"ok": ok, "tool": tool, "path": str(path)},
        )
    )


def test_exact_repeated_returned_range_nudges_on_third_inspection(
    tmp_path: Path,
) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"

    assert _read(hook, path) is None
    assert _read(hook, path) is None
    assert _read(hook, path) == HookResponse(additional_context=GUIDANCE)


def test_nudge_is_emitted_only_at_configured_threshold(tmp_path: Path) -> None:
    hook = RepeatedReadNudge(threshold=3)
    path = tmp_path / "a.py"
    _read(hook, path)

    assert _read(hook, path) is None
    assert _read(hook, path) is None
    assert _read(hook, path) == HookResponse(additional_context=GUIDANCE)


def test_heavily_overlapping_returned_ranges_count_as_redundant(
    tmp_path: Path,
) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path, returned_start=1, returned_end=100)

    assert _read(hook, path, returned_start=21, returned_end=120) is None
    assert _read(hook, path, returned_start=31, returned_end=130) is not None


def test_low_overlap_returned_range_does_not_count(tmp_path: Path) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path, returned_start=1, returned_end=100)

    assert _read(hook, path, returned_start=81, returned_end=180) is None
    assert hook._redundant_counts == {}


def test_overlap_uses_actual_result_range_not_requested_range(tmp_path: Path) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path, returned_start=1, returned_end=100)

    assert _read(
        hook,
        path,
        requested_start=500,
        requested_end=600,
        returned_start=1,
        returned_end=100,
    ) is None
    assert _read(
        hook,
        path,
        requested_start=700,
        requested_end=800,
        returned_start=1,
        returned_end=100,
    ) is not None


def test_truncated_full_file_tracks_each_returned_range_separately(
    tmp_path: Path,
) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "large.py"
    returned_ranges = [
        {"start_line": 1, "end_line": 500},
        {"start_line": 1501, "end_line": 2000},
    ]
    _read(hook, path, returned_end=2000, returned_ranges=returned_ranges)

    # The omitted middle must not become remembered coverage merely because
    # start_line/end_line span the whole file.
    assert _read(hook, path, returned_start=700, returned_end=800) is None
    assert _read(
        hook, path, returned_end=2000, returned_ranges=returned_ranges
    ) is None
    assert _read(
        hook, path, returned_end=2000, returned_ranges=returned_ranges
    ) is not None


def test_successful_apply_patch_invalidates_prior_reads(tmp_path: Path) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path)
    _read(hook, path)

    _mutate(hook, "apply_patch", path)

    assert _read(hook, path) is None
    assert _read(hook, path) is None


def test_successful_write_file_invalidates_prior_reads(tmp_path: Path) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path)
    _read(hook, path)

    _mutate(hook, "write_file", path)

    assert _read(hook, path) is None
    assert _read(hook, path) is None


def test_failed_mutation_does_not_invalidate_prior_reads(tmp_path: Path) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path)
    _read(hook, path)

    _mutate(hook, "apply_patch", path, ok=False)

    assert _read(hook, path) == HookResponse(additional_context=GUIDANCE)


def test_before_run_clears_history(tmp_path: Path) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path)
    _read(hook, path)

    hook.before_run(None)

    assert _read(hook, path) is None
    assert _read(hook, path) is None


def test_nudge_resets_repetition_streak(tmp_path: Path) -> None:
    hook = RepeatedReadNudge()
    path = tmp_path / "a.py"
    _read(hook, path)
    assert _read(hook, path) is None
    assert _read(hook, path) is not None

    assert _read(hook, path) is None
    assert _read(hook, path) is not None

"""Tests for product-owned recent-workspace persistence."""

from __future__ import annotations

import json
from pathlib import Path

from code_squid.app_paths import (
    RECENT_WORKSPACE_LIMIT,
    load_recent_workspaces,
    recent_workspaces_path,
    remember_workspace,
)


def test_recent_workspaces_are_normalized_deduplicated_and_capped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("CODE_SQUID_HOME", str(home))
    workspaces = [tmp_path / f"workspace-{index}" for index in range(12)]

    for workspace in workspaces:
        remember_workspace(workspace)
    remember_workspace(workspaces[5])

    persisted = json.loads(recent_workspaces_path().read_text(encoding="utf-8"))
    assert len(persisted) == RECENT_WORKSPACE_LIMIT
    assert persisted[0] == str(workspaces[5].resolve())
    assert len(persisted) == len(set(persisted))


def test_current_workspace_is_added_without_reordering_history(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CODE_SQUID_HOME", str(tmp_path / "home"))
    newest = tmp_path / "newest"
    current = tmp_path / "current"
    remember_workspace(newest)

    loaded = load_recent_workspaces(current)

    assert loaded == [newest.resolve(), current.resolve()]

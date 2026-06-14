"""Shared pytest isolation for Code Squid's user-level storage boundaries."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_session_indexes(monkeypatch, tmp_path_factory) -> Path:
    """Route every test's global session registry into pytest's temp root."""
    index_path = tmp_path_factory.getbasetemp() / "session-indexes.jsonl"
    monkeypatch.setenv("CODE_SQUID_SESSION_INDEXES", str(index_path))
    return index_path

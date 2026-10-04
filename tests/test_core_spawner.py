"""Generic run construction requires caller-owned model collaborators."""

import json
from dataclasses import replace
from pathlib import Path
from squid_core.model_response import ModelResponse
from types import SimpleNamespace

import pytest

import squid_core.spawner as core_spawner
from code_squid.agent.prompts import CODE_SQUID_PROMPT_DEFAULTS
from squid_core.settings import (
    CompactionSettings,
    ReadFileSettings,
    RuntimeSettings,
)
from squid_core.session import Session
from squid_core.agent import Agent
from squid_core.storage import SessionStore, UndoStore
from squid_core.tools import ToolResults


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        approval_mode="never",
        max_tool_steps=None,
        stream_assistant_text=False,
        compaction=CompactionSettings(
            enabled=False,
            trigger_input_tokens=25_000,
            compact_fraction=0.8,
            min_recent_chunks=2,
        ),
    )


def _storage_paths(tmp_path: Path) -> dict:
    return {
        "sessions_dir": tmp_path / "sessions",
        "undo_dir": tmp_path / "undo",
    }


def _provider_response(content: str = "done") -> ModelResponse:
    return ModelResponse(content, finish_reason="stop")












def test_code_squid_builder_supplies_application_prompt_defaults(
    monkeypatch, tmp_path: Path
) -> None:
    from code_squid.agent_setup import build_coding_task_run

    captured = {}

    class CapturingAgent:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("code_squid.agent_setup.Agent", CapturingAgent)

    build_coding_task_run(
        tmp_path,
        "Coding task",
        display=type("Display", (), {"debug": False})(),
        model_adapter=object(),
    )

    assert captured["prompt_defaults"] is CODE_SQUID_PROMPT_DEFAULTS

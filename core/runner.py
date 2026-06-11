# core/runner.py

"""Reusable wiring for starting a normal Code Squid coding task from Python.

This module owns the shared provider/model/tool/approval/compaction/loop setup
for new coding-task runs. ``main.py`` remains the standalone CLI entry point and
keeps CLI parsing, command dispatch, resume/show/undo/mode behavior,
interactive prompting, and user-facing error handling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent.coding import CodingAgent
from config.settings import Settings, load_settings
from core.agent_loop import AgentLoop, RunResult
from core.approval import ApprovalPolicy
from core.compaction import Compactor
from core.events import EventCallback
from core.model_adapter import ModelAdapter
from core.session import Session
from core.tool_executor import ToolExecutor
from core.tool_results import ToolResults
from providers.factory import build_provider, tool_call_content_mode
from storage.session_store import SessionStore
from storage.undo_store import UndoStore
from ui.terminal import StartupInfo, TerminalDisplay


FRIENDLY_MODES = {
    "always": "strict",
    "guarded": "balanced",
    "never": "yolo",
}


@dataclass(frozen=True)
class CodingTaskRun:
    session: Session
    session_store: SessionStore
    loop: AgentLoop


def run_coding_task(
    repo_root: Path | str,
    task: str,
    *,
    on_event: EventCallback | None = None,
    settings: Settings | None = None,
    display: TerminalDisplay | None = None,
) -> RunResult:
    """Simple call-and-run entry point for a new coding task.

    ``on_event`` is passed through to ``AgentLoop`` for external wrappers.
    """

    run = build_coding_task_run(
        repo_root=repo_root,
        task=task,
        on_event=on_event,
        settings=settings,
        display=display,
    )
    run.loop.display.run_started()
    return run.loop.run()


def build_coding_task_run(
    repo_root: Path | str,
    task: str,
    *,
    on_event: EventCallback | None = None,
    settings: Settings | None = None,
    display: TerminalDisplay | None = None,
) -> CodingTaskRun:
    """Construct a new coding-task run without starting it.

    CLI code uses this when it needs direct access to the session and
    ``SessionStore`` for interactive follow-ups after the first run.
    """

    repo_root = Path(repo_root).resolve()
    settings = load_settings(repo_root) if settings is None else settings
    display = _run_display(repo_root, settings) if display is None else display

    session = Session(repo_root=repo_root)
    session_store = SessionStore.create(repo_root=repo_root, task=task)
    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    agent = CodingAgent(task=task)
    loop = build_agent_loop(
        repo_root=repo_root,
        session=session,
        session_store=session_store,
        agent=agent,
        undo_store=undo_store,
        settings=settings,
        display=display,
        on_event=on_event,
    )

    return CodingTaskRun(
        session=session,
        session_store=session_store,
        loop=loop,
    )


def build_agent_loop(
    repo_root: Path,
    session: Session,
    session_store: SessionStore,
    agent: CodingAgent,
    undo_store: UndoStore,
    settings: Settings,
    display: TerminalDisplay,
    *,
    on_event: EventCallback | None = None,
) -> AgentLoop:
    """Build the shared provider/model/tool/approval/compaction/loop wiring."""

    provider = build_provider(settings, debug=display.debug)

    model_adapter = ModelAdapter(
        provider=provider,
        model_name=settings.model.name,
        tool_call_content_mode=tool_call_content_mode(settings),
    )
    compactor = Compactor(settings.compaction, model_adapter)

    tool_executor = ToolExecutor(
        repo_root=repo_root,
        session=session,
        undo_store=undo_store,
        allow_outside_workspace=settings.runtime.approval_mode == "never",
    )
    tool_results = ToolResults()
    approval_policy = ApprovalPolicy(
        mode=settings.runtime.approval_mode,
        prompter=display,
    )

    return AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=tool_executor,
        tool_results=tool_results,
        agent=agent,
        display=display,
        session_store=session_store,
        compactor=compactor,
        max_tool_steps=settings.runtime.max_tool_steps,
        approval_policy=approval_policy,
        stream_assistant_text=settings.runtime.stream_assistant_text,
        on_event=on_event,
    )


def startup_info(repo_root: Path, settings: Settings) -> StartupInfo:
    return StartupInfo(
        directory=repo_root,
        provider=settings.model.provider,
        model=settings.model.name,
        approval_mode=FRIENDLY_MODES[settings.runtime.approval_mode],
    )


def _run_display(repo_root: Path, settings: Settings) -> TerminalDisplay:
    trace = os.getenv("CODE_SQUID_TRACE") == "1"
    debug = settings.display.debug or trace
    return TerminalDisplay(
        debug=debug,
        show_transcript=trace,
        startup_info=startup_info(repo_root, settings),
    )

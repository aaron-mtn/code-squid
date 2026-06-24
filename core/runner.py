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
from typing import Callable

from agent.coding import CodingAgent
from config.settings import Settings, load_settings
from core.agent_loop import AgentLoop, RunResult
from core.approval import ApprovalPolicy
from core.compaction import Compactor
from core.events import EventCallback
from core.model_adapter import ModelAdapter
from core.session import Session
from core.skills import Skill, discover_builtin_skills
from core.tool_executor import ToolExecutor
from core.tool_results import ToolResults
from providers.factory import build_provider, tool_call_content_mode
from storage.session_store import SessionStore
from storage.undo_store import UndoStore
from tools import TOOLS
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
    should_cancel: Callable[[], bool] | None = None,
    settings: Settings | None = None,
    display: TerminalDisplay | None = None,
    skill_name: str | None = None,
) -> RunResult:
    """Simple call-and-run entry point for a new coding task.

    ``on_event`` is passed through to ``AgentLoop`` for external wrappers.
    """

    run = build_coding_task_run(
        repo_root=repo_root,
        task=task,
        on_event=on_event,
        should_cancel=should_cancel,
        settings=settings,
        display=display,
        skill_name=skill_name,
    )
    run.loop.display.run_started()
    return run.loop.run()


def build_coding_task_run(
    repo_root: Path | str,
    task: str,
    *,
    on_event: EventCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
    settings: Settings | None = None,
    display: TerminalDisplay | None = None,
    skill_name: str | None = None,
) -> CodingTaskRun:
    """Construct a new coding-task run without starting it.

    CLI code uses this when it needs direct access to the session and
    ``SessionStore`` for interactive follow-ups after the first run.
    """

    repo_root = Path(repo_root).resolve()
    settings = load_settings(repo_root) if settings is None else settings
    display = build_run_display(repo_root, settings, skill_name) if display is None else display

    session = Session(repo_root=repo_root)
    session_store = SessionStore.create(repo_root=repo_root, task=task)
    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    skill, active_tools = resolve_skill_tools(skill_name)
    append_run_context(session_store, skill, active_tools)
    agent = CodingAgent(task=task, skill=skill, tools=active_tools)
    loop = build_agent_loop(
        repo_root=repo_root,
        session=session,
        session_store=session_store,
        agent=agent,
        undo_store=undo_store,
        settings=settings,
        display=display,
        tools=active_tools,
        on_event=on_event,
        should_cancel=should_cancel,
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
    tools: dict | None = None,
    on_event: EventCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
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
        tools=tools,
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
        should_cancel=should_cancel,
    )


def resolve_skill_tools(skill_name: str | None) -> tuple[Skill | None, dict]:
    if skill_name is None:
        return None, TOOLS

    skills = discover_builtin_skills()
    skill = skills.get(skill_name)
    if skill is None:
        available = ", ".join(sorted(skills)) or "none"
        raise ValueError(f"Unknown skill: {skill_name}. Available skills: {available}")

    if not skill.allowed_tools:
        return skill, TOOLS

    unknown_tools = [tool_name for tool_name in skill.allowed_tools if tool_name not in TOOLS]
    if unknown_tools:
        unknown = ", ".join(unknown_tools)
        raise ValueError(f"Skill {skill.name} lists unknown tool(s): {unknown}")

    return skill, {tool_name: TOOLS[tool_name] for tool_name in skill.allowed_tools}


def append_run_context(
    session_store: SessionStore,
    skill: Skill | None,
    active_tools: dict,
) -> dict:
    return session_store.append_run_context(
        skill_name=skill.name if skill is not None else None,
        allowed_tools=sorted(active_tools),
        prompt_overrides=sorted(skill.prompt_sections) if skill is not None else [],
    )


def startup_info(
    repo_root: Path,
    settings: Settings,
    skill_name: str | None = None,
) -> StartupInfo:
    return StartupInfo(
        directory=repo_root,
        provider=settings.model.provider,
        model=settings.model.name,
        approval_mode=FRIENDLY_MODES[settings.runtime.approval_mode],
        skill_name=skill_name,
    )


def build_run_display(
    repo_root: Path,
    settings: Settings,
    skill_name: str | None = None,
) -> TerminalDisplay:
    trace = os.getenv("CODE_SQUID_TRACE") == "1"
    debug = settings.display.debug or trace
    return TerminalDisplay(
        debug=debug,
        show_transcript=trace,
        startup_info=startup_info(repo_root, settings, skill_name),
    )

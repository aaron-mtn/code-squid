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
from core.hook_loader import load_active_extension_hooks, load_user_hooks
from core.hooks import HookRunner
from core.model_adapter import ModelAdapter
from core.platform_context import PlatformContext, detect_platform_context
from core.session import Session
from core.skills import Skill, discover_skills
from core.tool_executor import ToolExecutor
from core.tool_results import ToolResults
from core.user_tools import build_user_tool_registry
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
    resolved_skill: Skill | None = None,
    resolved_tools: dict | None = None,
    hooks: list[object] | None = None,
    hook_runner: HookRunner | None = None,
    include_user_hooks: bool = False,
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
        resolved_skill=resolved_skill,
        resolved_tools=resolved_tools,
        hooks=hooks,
        hook_runner=hook_runner,
        include_user_hooks=include_user_hooks,
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
    resolved_skill: Skill | None = None,
    resolved_tools: dict | None = None,
    hooks: list[object] | None = None,
    hook_runner: HookRunner | None = None,
    include_user_hooks: bool = False,
) -> CodingTaskRun:
    """Construct a new coding-task run without starting it.

    CLI code uses this when it needs direct access to the session and
    ``SessionStore`` for interactive follow-ups after the first run.
    """

    if (resolved_skill is None) != (resolved_tools is None):
        raise ValueError("resolved_skill and resolved_tools must be supplied together")

    repo_root = Path(repo_root).resolve()
    settings = load_settings(repo_root) if settings is None else settings
    display_skill_name = resolved_skill.name if resolved_skill is not None else skill_name
    display = (
        build_run_display(repo_root, settings, display_skill_name)
        if display is None
        else display
    )

    session = Session(repo_root=repo_root)
    session_store = SessionStore.create(repo_root=repo_root, task=task)
    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    if resolved_skill is not None and resolved_tools is not None:
        skill, active_tools = resolved_skill, resolved_tools
    else:
        skill, active_tools = resolve_skill_tools(
            skill_name,
            repo_root=repo_root,
            session_id=session_store.session_id,
        )
    append_run_context(session_store, skill, active_tools)
    platform_context = detect_platform_context()
    agent = CodingAgent(
        task=task,
        skill=skill,
        tools=active_tools,
        platform_context=platform_context,
        workspace=str(repo_root),
    )
    hook_runner = build_hook_runner(
        hooks=hooks,
        hook_runner=hook_runner,
        include_user_hooks=include_user_hooks,
    )
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
        hook_runner=hook_runner,
        platform_context=platform_context,
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
    hooks: list[object] | None = None,
    hook_runner: HookRunner | None = None,
    include_user_hooks: bool = False,
    platform_context: PlatformContext | None = None,
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
        platform_context=platform_context,
    )
    tool_results = ToolResults()
    approval_policy = ApprovalPolicy(
        mode=settings.runtime.approval_mode,
        prompter=display,
    )
    hook_runner = build_hook_runner(
        hooks=hooks,
        hook_runner=hook_runner,
        include_user_hooks=include_user_hooks,
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
        hook_runner=hook_runner,
    )


def build_hook_runner(
    *,
    hooks: list[object] | None = None,
    hook_runner: HookRunner | None = None,
    include_user_hooks: bool = False,
) -> HookRunner:
    if hook_runner is not None:
        return hook_runner

    combined_hooks = list(hooks or [])
    if include_user_hooks:
        combined_hooks.extend(load_user_hooks())
    else:
        combined_hooks.extend(load_active_extension_hooks())

    return HookRunner(combined_hooks)


def resolve_skill_tools(
    skill_name: str | None,
    *,
    repo_root: Path | str | None = None,
    session_id: str | None = None,
) -> tuple[Skill | None, dict]:
    if skill_name is None:
        return None, TOOLS

    skills = discover_skills()
    skill = skills.get(skill_name)
    if skill is None:
        available = ", ".join(sorted(skills)) or "none"
        raise ValueError(f"Unknown skill: {skill_name}. Available skills: {available}")

    if not skill.allowed_tools and getattr(skill, "allowed_tools_explicit", False):
        return skill, {}

    if not skill.allowed_tools:
        return skill, TOOLS

    user_tools = build_user_tool_registry(repo_root=repo_root, session_id=session_id)
    available_tools = {**user_tools, **TOOLS}
    unknown_tools = [
        tool_name
        for tool_name in skill.allowed_tools
        if tool_name not in available_tools
    ]
    if unknown_tools:
        unknown = ", ".join(unknown_tools)
        raise ValueError(f"Skill {skill.name} lists unknown tool(s): {unknown}")

    return skill, {tool_name: available_tools[tool_name] for tool_name in skill.allowed_tools}


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

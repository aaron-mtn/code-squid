"""Generic construction helpers for a Squid Core agent run.

Applications select prompts, tools, presentation, and any application-specific
discovery policy before calling this module.  ``AgentLoop`` remains available
for callers that want to construct every collaborator themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config.settings import Settings
from squid_core.safety import ActionPreflight
from squid_core.agent_loop import AgentLoop, RunResult
from squid_core.safety import ApprovalPolicy
from squid_core.compaction import Compactor
from squid_core.events import EventCallback
from squid_core.hooks import HookRunner
from squid_core.model_adapter import ModelAdapter
from squid_core.platform_context import PlatformContext, detect_platform_context
from squid_core.session import Session
from squid_core.tools import ToolExecutor, ToolResults
from providers.factory import build_provider, tool_call_content_mode
from squid_core.agent import Agent
from storage.session_store import SessionStore
from storage.undo_store import UndoStore


SessionStoreFactory = Callable[[Path, str], SessionStore]
UndoStoreFactory = Callable[[Path, str], UndoStore]


class NullDisplay:
    """Small UI-neutral presentation collaborator used by generic runs."""

    debug = False

    def run_started(self) -> None:
        pass

    def thinking(self) -> None:
        pass

    def debug_reply(self, reply: dict) -> None:
        pass

    def final_message(self, content: str) -> None:
        pass

    def assistant_message(self, content: str) -> None:
        pass

    def reply_rejected(self, reason: str) -> None:
        pass

    def repeated_invalid_replies(self, reason: str, count: int) -> None:
        pass

    def action_started(self, action: dict) -> None:
        pass

    def tool_result(self, action: dict, result: dict) -> None:
        pass

    def step_limit_reached(self, max_tool_steps: int) -> None:
        pass


@dataclass(frozen=True)
class AgentRun:
    session: Session
    session_store: SessionStore
    loop: AgentLoop


def run_agent_task(repo_root: Path | str, task: str, *, settings: Settings, **kwargs) -> RunResult:
    """Build and run a generic task with optional selective replacements."""

    run = build_agent_run(repo_root, task, settings=settings, **kwargs)
    run.loop.display.run_started()
    return run.loop.run()


def build_agent_run(
    repo_root: Path | str,
    task: str,
    *,
    settings: Settings,
    prompt_defaults=None,
    skill=None,
    tools: dict | None = None,
    agent=None,
    provider=None,
    model_adapter=None,
    compactor=None,
    tool_executor=None,
    tool_results=None,
    approval_policy=None,
    action_preflight=None,
    hook_runner=None,
    display=None,
    approval_prompter=None,
    session: Session | None = None,
    session_store: SessionStore | None = None,
    undo_store: UndoStore | None = None,
    session_store_factory: SessionStoreFactory | None = None,
    undo_store_factory: UndoStoreFactory | None = None,
    on_event: EventCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
    platform_context: PlatformContext | None = None,
    provider_debug: bool | None = None,
) -> AgentRun:
    """Construct a generic run without application discovery or terminal UI.

    Supplied high-level collaborators are used directly.  In particular, a
    supplied model adapter bypasses provider construction and a supplied tool
    executor bypasses default undo-store and executor construction.
    """

    if session_store is not None and session_store_factory is not None:
        raise ValueError("session_store and session_store_factory are mutually exclusive")
    if undo_store is not None and undo_store_factory is not None:
        raise ValueError("undo_store and undo_store_factory are mutually exclusive")

    repo_root = Path(repo_root).resolve()
    session = session if session is not None else Session(repo_root=repo_root)
    if session_store is None:
        session_store = (
            SessionStore.create(repo_root=repo_root, task=task)
            if session_store_factory is None
            else session_store_factory(repo_root, task)
        )

    if undo_store is None and tool_executor is None:
        undo_store = (
            UndoStore.create(repo_root, session_id=session_store.session_id)
            if undo_store_factory is None
            else undo_store_factory(repo_root, session_store.session_id)
        )
    elif undo_store is None and undo_store_factory is not None:
        undo_store = undo_store_factory(repo_root, session_store.session_id)

    selected_tools = {} if tools is None else tools
    needs_platform = agent is None or tool_executor is None
    if platform_context is None and needs_platform:
        platform_context = detect_platform_context()
    if agent is None:
        agent = Agent(
            task=task,
            skill=skill,
            tools=selected_tools,
            platform_context=platform_context,
            workspace=str(repo_root),
            prompt_defaults=prompt_defaults,
        )

    loop = build_agent_loop(
        repo_root=repo_root,
        session=session,
        session_store=session_store,
        undo_store=undo_store,
        settings=settings,
        agent=agent,
        tools=selected_tools,
        provider=provider,
        model_adapter=model_adapter,
        compactor=compactor,
        tool_executor=tool_executor,
        tool_results=tool_results,
        approval_policy=approval_policy,
        action_preflight=action_preflight,
        hook_runner=hook_runner,
        display=display,
        approval_prompter=approval_prompter,
        on_event=on_event,
        should_cancel=should_cancel,
        platform_context=platform_context,
        provider_debug=provider_debug,
    )
    return AgentRun(session=session, session_store=session_store, loop=loop)


def build_agent_loop(
    repo_root: Path,
    session: Session,
    session_store: SessionStore,
    agent,
    undo_store: UndoStore | None,
    settings: Settings,
    *,
    tools: dict | None = None,
    display=None,
    approval_prompter=None,
    provider=None,
    model_adapter=None,
    compactor=None,
    tool_executor=None,
    tool_results=None,
    approval_policy=None,
    action_preflight=None,
    hook_runner=None,
    on_event: EventCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
    platform_context: PlatformContext | None = None,
    provider_debug: bool | None = None,
) -> AgentLoop:
    """Wire default Core collaborators around an Agent, with explicit seams."""

    repo_root = Path(repo_root).resolve()
    display = NullDisplay() if display is None else display
    if model_adapter is None:
        if provider is None:
            debug = settings.display.debug if provider_debug is None else provider_debug
            provider = build_provider(settings, debug=debug)
        model_adapter = ModelAdapter(
            provider=provider,
            model_name=settings.model.name,
            tool_call_content_mode=tool_call_content_mode(settings),
            provider_name=settings.model.provider,
        )
    if compactor is None:
        compactor = Compactor(settings.compaction, model_adapter)
    if tool_executor is None:
        tool_executor = ToolExecutor(
            repo_root=repo_root,
            session=session,
            undo_store=undo_store,
            allow_outside_workspace=settings.runtime.approval_mode == "never",
            tools={} if tools is None else tools,
            platform_context=platform_context,
        )
    if tool_results is None:
        tool_results = ToolResults()
    if approval_policy is None:
        approval_policy = ApprovalPolicy(
            mode=settings.runtime.approval_mode,
            prompter=approval_prompter,
        )
    if action_preflight is None:
        action_preflight = ActionPreflight(
            workspace_root=repo_root,
            approval_mode=settings.runtime.approval_mode,
        )
    if hook_runner is None:
        hook_runner = HookRunner()

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
        action_preflight=action_preflight,
        stream_assistant_text=settings.runtime.stream_assistant_text,
        on_event=on_event,
        should_cancel=should_cancel,
        hook_runner=hook_runner,
    )

"""Code Squid application wiring for normal coding tasks.

This layer owns Code Squid prompts, Skill/tool discovery, hooks, and application
paths. Generic collaborator construction lives in ``squid_core.spawner``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from code_squid.agent.prompts import CODE_SQUID_PROMPT_DEFAULTS
from code_squid.settings import Settings, load_settings
from squid_core.agent_loop import AgentLoop, RunResult
from squid_core.events import EventCallback
from code_squid.app_paths import (
    code_squid_home,
    session_indexes_path,
    workspace_sessions_dir,
    workspace_undo_dir,
)
from squid_core.hooks import (
    HookRunner,
    RepeatedFailureNudge,
    RepeatedReadNudge,
    VerificationState,
    load_user_hooks,
)
from squid_core.mods import ResolvedMod, resolve_mod
from squid_core.platform_context import PlatformContext, detect_platform_context
from squid_core.session import Session
from squid_core.skills import Skill, discover_skills
from squid_core.tools.user_tools import build_user_tool_registry
from squid_core.storage import SessionStore, UndoStore
from squid_core.storage.session_index import register_session_root
from squid_core.tools.builtins import TOOLS
from squid_core.agent import Agent
from squid_core.spawner import build_agent_loop as build_core_agent_loop


SessionStoreFactory = Callable[[Path, str], SessionStore]
UndoStoreFactory = Callable[[Path, str], UndoStore]

NO_PROGRESS_GUIDANCE = (
    "You have repeated this approach without making progress. Use the latest "
    "tool result and choose a materially different next action instead of "
    "retrying the same failure."
)
RUN_COMMAND_RECOVERY_GUIDANCE = (
    "Several recent commands have failed.\n\n"
    "Stop trying small variations of the same approach. Reassess the latest "
    "errors and use a simple command that matches the configured operating "
    "system and shell.\n\n"
    "Do not assume commands, syntax, or utilities from a different environment "
    "are available."
)


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
    display=None,
    skill_name: str | None = None,
    mod_name: str | None = None,
    app_home: Path | str | None = None,
    mod_id: str | None = None,
    resolved_skill: Skill | None = None,
    resolved_tools: dict | None = None,
    hooks: list[object] | None = None,
    hook_runner: HookRunner | None = None,
    include_user_hooks: bool = False,
    agent=None,
    provider=None,
    model_adapter=None,
    compactor=None,
    tool_executor=None,
    tool_results=None,
    approval_policy=None,
    action_preflight=None,
    approval_prompter=None,
    session: Session | None = None,
    session_store: SessionStore | None = None,
    undo_store: UndoStore | None = None,
    session_store_factory: SessionStoreFactory | None = None,
    undo_store_factory: UndoStoreFactory | None = None,
) -> RunResult:
    """Simple call-and-run entry point for a new coding task.

    ``on_event`` is passed through to ``AgentLoop`` for external wrappers. When
    no display is supplied, Squid Core uses its UI-neutral null presentation.
    """

    run = build_coding_task_run(
        repo_root=repo_root,
        task=task,
        on_event=on_event,
        should_cancel=should_cancel,
        settings=settings,
        display=display,
        skill_name=skill_name,
        mod_name=mod_name,
        app_home=app_home,
        mod_id=mod_id,
        resolved_skill=resolved_skill,
        resolved_tools=resolved_tools,
        hooks=hooks,
        hook_runner=hook_runner,
        include_user_hooks=include_user_hooks,
        agent=agent,
        provider=provider,
        model_adapter=model_adapter,
        compactor=compactor,
        tool_executor=tool_executor,
        tool_results=tool_results,
        approval_policy=approval_policy,
        action_preflight=action_preflight,
        approval_prompter=approval_prompter,
        session=session,
        session_store=session_store,
        undo_store=undo_store,
        session_store_factory=session_store_factory,
        undo_store_factory=undo_store_factory,
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
    display=None,
    skill_name: str | None = None,
    mod_name: str | None = None,
    app_home: Path | str | None = None,
    mod_id: str | None = None,
    resolved_skill: Skill | None = None,
    resolved_tools: dict | None = None,
    hooks: list[object] | None = None,
    hook_runner: HookRunner | None = None,
    include_user_hooks: bool = False,
    agent=None,
    provider=None,
    model_adapter=None,
    compactor=None,
    tool_executor=None,
    tool_results=None,
    approval_policy=None,
    action_preflight=None,
    approval_prompter=None,
    session: Session | None = None,
    session_store: SessionStore | None = None,
    undo_store: UndoStore | None = None,
    session_store_factory: SessionStoreFactory | None = None,
    undo_store_factory: UndoStoreFactory | None = None,
) -> CodingTaskRun:
    """Construct a new coding-task run without starting it.

    CLI code uses this when it needs direct access to the session and
    ``SessionStore`` for interactive follow-ups after the first run. Frontends
    supply their own display; omitted presentation uses Squid Core's default.
    """

    if (resolved_skill is None) != (resolved_tools is None):
        raise ValueError("resolved_skill and resolved_tools must be supplied together")
    if mod_name is not None and (skill_name is not None or resolved_skill is not None):
        raise ValueError("mod_name cannot be combined with skill_name or resolved components")

    repo_root = Path(repo_root).resolve()
    app_home = code_squid_home(app_home)
    settings = load_settings(repo_root) if settings is None else settings
    runtime_settings = settings.to_runtime_settings()
    selected_mod: ResolvedMod | None = None

    if session_store is not None and session_store_factory is not None:
        raise ValueError("session_store and session_store_factory are mutually exclusive")
    if undo_store is not None and undo_store_factory is not None:
        raise ValueError("undo_store and undo_store_factory are mutually exclusive")

    session = session if session is not None else Session(repo_root=repo_root)
    sessions_dir = workspace_sessions_dir(repo_root)
    undo_dir = workspace_undo_dir(repo_root)
    if session_store is None:
        session_store = (
            SessionStore.create(sessions_dir, task, workspace_root=repo_root)
            if session_store_factory is None
            else session_store_factory(repo_root, task)
        )
        try:
            # Cross-workspace discovery is supplementary application policy;
            # failure must not invalidate the newly created local session.
            register_session_root(session_indexes_path(), sessions_dir)
        except Exception:
            pass
    if undo_store is None and tool_executor is None:
        undo_store = (
            UndoStore.create(
                undo_dir,
                session_store.session_id,
                workspace_root=repo_root,
            )
            if undo_store_factory is None
            else undo_store_factory(repo_root, session_store.session_id)
        )
    elif undo_store is None and undo_store_factory is not None:
        undo_store = undo_store_factory(repo_root, session_store.session_id)
    if mod_name is not None:
        selected_mod = resolve_mod(
            mod_name,
            app_home,
            repo_root=repo_root,
            session_id=session_store.session_id,
        )
        skill, active_tools = selected_mod.skill, selected_mod.tools
    elif resolved_skill is not None and resolved_tools is not None:
        skill, active_tools = resolved_skill, resolved_tools
    else:
        skill, active_tools = resolve_skill_tools(
            skill_name,
            repo_root=repo_root,
            session_id=session_store.session_id,
            app_home=app_home,
        )
    selected_mod_id = selected_mod.metadata.name if selected_mod is not None else mod_id
    append_run_context(session_store, skill, active_tools, mod_id=selected_mod_id)
    platform_context = (
        detect_platform_context()
        if agent is None or tool_executor is None
        else None
    )
    if agent is None:
        agent = Agent(
            task=task,
            skill=skill,
            tools=active_tools,
            platform_context=platform_context,
            workspace=str(repo_root),
            prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS,
        )
    selected_hooks = list(hooks or [])
    if selected_mod is not None:
        selected_hooks.extend(selected_mod.hooks)
    hook_runner = build_hook_runner(
        hooks=selected_hooks,
        hook_runner=hook_runner,
        include_user_hooks=include_user_hooks,
        app_home=app_home,
    )
    loop = build_core_agent_loop(
        repo_root=repo_root,
        session=session,
        session_store=session_store,
        agent=agent,
        undo_store=undo_store,
        settings=runtime_settings,
        display=display,
        tools=active_tools,
        on_event=on_event,
        should_cancel=should_cancel,
        hook_runner=hook_runner,
        platform_context=platform_context,
        provider=provider,
        model_adapter=model_adapter,
        compactor=compactor,
        tool_executor=tool_executor,
        tool_results=tool_results,
        approval_policy=approval_policy,
        action_preflight=action_preflight,
        approval_prompter=display if approval_prompter is None else approval_prompter,
    )

    return CodingTaskRun(
        session=session,
        session_store=session_store,
        loop=loop,
    )


def build_hook_runner(
    *,
    hooks: list[object] | None = None,
    hook_runner: HookRunner | None = None,
    include_user_hooks: bool = False,
    app_home: Path | str | None = None,
) -> HookRunner:
    verification_state = VerificationState(source="Code Squid")
    repeated_read_hook = RepeatedReadNudge(
        source="Code Squid",
        verification_state=verification_state,
    )
    no_progress_hook = RepeatedFailureNudge(
        NO_PROGRESS_GUIDANCE,
        run_command_guidance=RUN_COMMAND_RECOVERY_GUIDANCE,
        source="Code Squid",
    )
    if hook_runner is not None:
        # Application policy remains active when callers replace the optional
        # Hook collection for tests or embedding.
        return HookRunner(
            [
                *hook_runner.hooks,
                verification_state,
                repeated_read_hook,
                no_progress_hook,
            ]
        )

    combined_hooks = list(hooks or [])
    if include_user_hooks:
        combined_hooks.extend(load_user_hooks(app_home=code_squid_home(app_home)))

    combined_hooks.extend(
        (verification_state, repeated_read_hook, no_progress_hook)
    )

    return HookRunner(combined_hooks)


def resolve_skill_tools(
    skill_name: str | None,
    *,
    repo_root: Path | str | None = None,
    session_id: str | None = None,
    app_home: Path | str | None = None,
) -> tuple[Skill | None, dict]:
    if skill_name is None:
        return None, TOOLS

    app_home = code_squid_home(app_home)
    skills = discover_skills(app_home=app_home)
    skill = skills.get(skill_name)
    if skill is None:
        available = ", ".join(sorted(skills)) or "none"
        raise ValueError(f"Unknown skill: {skill_name}. Available skills: {available}")

    if not skill.allowed_tools and getattr(skill, "allowed_tools_explicit", False):
        return skill, {}

    if not skill.allowed_tools:
        return skill, TOOLS

    user_tools = build_user_tool_registry(
        app_home=app_home,
        repo_root=repo_root,
        session_id=session_id,
    )
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
    mod_id: str | None = None,
) -> dict:
    return session_store.append_run_context(
        skill_name=skill.name if skill is not None else None,
        allowed_tools=sorted(active_tools),
        prompt_overrides=sorted(skill.prompt_sections) if skill is not None else [],
        mod_id=mod_id,
    )

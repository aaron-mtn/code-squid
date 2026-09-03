"""Run and session orchestration helpers for the Code Squid CLI."""

import os
from pathlib import Path

from code_squid.agent.prompts import CODE_SQUID_PROMPT_DEFAULTS
from code_squid.settings import Settings
from squid_core.agent_loop import AgentLoop, RunResult
from squid_core.model_adapter import ModelRequestError
from code_squid.agent_setup import (
    append_run_context,
    build_coding_task_run,
    resolve_skill_tools,
    startup_info,
)
from code_squid.app_paths import (
    workspace_error_log_path,
    workspace_sessions_dir,
    workspace_undo_dir,
)
from squid_core.session import Session
from squid_core.spawner import build_agent_loop
from squid_core.storage import SessionStore, UndoStore, write_error_log
from squid_core.storage.session_index import latest_session_id, session_dir_for
from code_squid.console.ui.display import TerminalDisplay
from squid_core.agent import Agent


def _session_dir_for_resume(repo_root: Path, session_id: str) -> Path | None:
    sessions_dir = workspace_sessions_dir(repo_root)
    if session_id == "latest":
        resolved_id = latest_session_id(sessions_dir)
        if resolved_id is None:
            print("No saved sessions.")
            return None

        session_id = resolved_id

    return session_dir_for(sessions_dir, session_id)


def _run_display(
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


def _run_loop(
    repo_root: Path,
    loop: AgentLoop,
    display: TerminalDisplay,
    session: Session,
    session_store: SessionStore,
) -> int:
    try:
        run_result = loop.run()
    except KeyboardInterrupt:
        session_store.update_status("interrupted")
        run_result = RunResult(status="interrupted", reason="user interrupted")
        display.interrupted()
        display.loop_finished(session, run_result)
        return 0
    except ModelRequestError as error:
        session_store.update_status("failed")
        log_path = write_error_log(workspace_error_log_path(repo_root), error)
        try:
            display_path = log_path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            display_path = log_path
        display.model_request_failed(display_path)
        return 1

    display.loop_finished(session, run_result)
    return 1 if run_result.status == "failed" else 0


def _run_new_session_task(
    repo_root: Path,
    task: str,
    settings: Settings,
    display: TerminalDisplay,
    skill_name: str | None = None,
) -> tuple[int, str | None]:
    display.run_started()

    run = build_coding_task_run(
        repo_root=repo_root,
        task=task,
        settings=settings,
        display=display,
        skill_name=skill_name,
    )

    status = _run_loop(repo_root, run.loop, display, run.session, run.session_store)
    return status, run.session_store.session_id


def _run_follow_up_task(
    repo_root: Path,
    session_id: str,
    follow_up_task: str,
    settings: Settings,
    display: TerminalDisplay,
    skill_name: str | None = None,
) -> tuple[int, str | None]:
    session_dir = _session_dir_for_resume(repo_root, session_id)
    if session_dir is None:
        return 0, None

    session_store = SessionStore.open(session_dir)
    session = Session(repo_root=repo_root)
    session.add_messages(*session_store.load_messages())

    display.run_started()
    skill, active_tools = resolve_skill_tools(skill_name)
    append_run_context(session_store, skill, active_tools)
    agent = Agent(
        task=follow_up_task,
        skill=skill,
        tools=active_tools,
        prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS,
    )
    follow_up_message = agent.follow_up_message(follow_up_task)
    session.add_message(follow_up_message)
    session_store.append_message(follow_up_message)
    session_store.update_status("active")

    undo_store = UndoStore.create(
        workspace_undo_dir(repo_root),
        session_id=session_store.session_id,
        workspace_root=repo_root,
    )
    loop = build_agent_loop(
        repo_root=repo_root,
        session=session,
        session_store=session_store,
        agent=agent,
        undo_store=undo_store,
        settings=settings.to_runtime_settings(),
        display=display,
        tools=active_tools,
    )
    status = _run_loop(repo_root, loop, display, session, session_store)
    return status, session_store.session_id

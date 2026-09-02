# cli/run.py

"""Run and session orchestration helpers for the Code Squid CLI."""

import os
from pathlib import Path

from agent.prompts import CODE_SQUID_PROMPT_DEFAULTS
from config.settings import Settings
from squid_core.agent_loop import AgentLoop, RunResult
from squid_core.model_adapter import ModelRequestError
from core.runner import (
    append_run_context,
    build_agent_loop,
    build_coding_task_run,
    resolve_skill_tools,
    startup_info,
)
from squid_core.session import Session
from storage.error_log import write_error_log
from storage.session_index import latest_session_id, session_dir_for
from storage.session_store import SessionStore
from storage.undo_store import UndoStore
from ui.terminal import TerminalDisplay
from squid_core.agent import Agent


def _session_dir_for_resume(repo_root: Path, session_id: str) -> Path | None:
    if session_id == "latest":
        resolved_id = latest_session_id(repo_root)
        if resolved_id is None:
            print("No saved sessions.")
            return None

        session_id = resolved_id

    return session_dir_for(repo_root, session_id)


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
        log_path = write_error_log(repo_root / ".code-squid", error)
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

    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    loop = build_agent_loop(
        repo_root=repo_root,
        session=session,
        session_store=session_store,
        agent=agent,
        undo_store=undo_store,
        settings=settings,
        display=display,
        tools=active_tools,
    )
    status = _run_loop(repo_root, loop, display, session, session_store)
    return status, session_store.session_id

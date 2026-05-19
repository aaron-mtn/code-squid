# main.py

"""Owns thin application wiring for standalone Code Squid; must not own core architecture, agent policy, or tool logic."""

import sys
from pathlib import Path

from agent.coding import CodingAgent
from config.settings import Settings, load_settings
from core.agent_loop import AgentLoop
from core.approval import ApprovalPolicy
from core.model_adapter import ModelAdapter
from core.session import Session
from core.tool_executor import ToolExecutor
from core.tool_results import ToolResults
from providers.openai_compatible import OpenAICompatibleProvider
from storage.session_index import latest_session_id, session_dir_for
from storage.session_store import SessionStore
from storage.undo_store import UndoStore
from ui.sessions import USAGE, handle_session_viewer
from ui.terminal import TerminalDisplay


def _session_dir_for_resume(repo_root: Path, session_id: str) -> Path | None:
    if session_id == "latest":
        resolved_id = latest_session_id(repo_root)
        if resolved_id is None:
            print("No saved sessions.")
            return None

        session_id = resolved_id

    return session_dir_for(repo_root, session_id)


def _build_loop(
    repo_root: Path,
    session: Session,
    session_store: SessionStore,
    agent: CodingAgent,
    undo_store: UndoStore,
    settings: Settings,
) -> tuple[AgentLoop, TerminalDisplay]:
    provider = OpenAICompatibleProvider(
        base_url=settings.model.base_url,
        api_key=settings.model.api_key,
    )

    model_adapter = ModelAdapter(
        provider=provider,
        model_name=settings.model.name,
    )

    tool_executor = ToolExecutor(
        repo_root=repo_root,
        session=session,
        undo_store=undo_store,
    )
    tool_results = ToolResults()
    display = TerminalDisplay(debug=settings.display.debug)
    approval_policy = ApprovalPolicy(
        mode=settings.runtime.approval_mode,
        prompter=display,
    )

    loop = AgentLoop(
        session=session,
        model_adapter=model_adapter,
        tool_executor=tool_executor,
        tool_results=tool_results,
        agent=agent,
        display=display,
        session_store=session_store,
        max_tool_steps=settings.runtime.max_tool_steps,
        approval_policy=approval_policy,
    )

    return loop, display


def _run_loop(
    loop: AgentLoop,
    display: TerminalDisplay,
    session: Session,
    session_store: SessionStore,
) -> None:
    display.start()
    try:
        loop.run()
    except KeyboardInterrupt:
        session_store.update_status("interrupted")
        print("⏹️ Interrupted")
    finally:
        display.loop_finished(session)


def _run_new_session(repo_root: Path) -> None:
    settings = load_settings(repo_root)
    task = input("Task: ")

    session = Session(repo_root=repo_root)
    session_store = SessionStore.create(repo_root=repo_root, task=task)
    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    agent = CodingAgent(task=task)
    loop, display = _build_loop(repo_root, session, session_store, agent, undo_store, settings)

    _run_loop(loop, display, session, session_store)


def _resume_session(repo_root: Path, session_id: str) -> None:
    settings = load_settings(repo_root)
    session_dir = _session_dir_for_resume(repo_root, session_id)
    if session_dir is None:
        return

    session_store = SessionStore.open(session_dir)
    session = Session(repo_root=repo_root)
    session.add_messages(*session_store.load_messages())

    follow_up_task = input("Follow-up task: ")
    agent = CodingAgent(task=follow_up_task)
    follow_up_message = agent.follow_up_message(follow_up_task)
    session.add_message(follow_up_message)
    session_store.append_message(follow_up_message)
    session_store.update_status("active")

    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    loop, display = _build_loop(repo_root, session, session_store, agent, undo_store, settings)
    _run_loop(loop, display, session, session_store)


def _undo(repo_root: Path) -> None:
    try:
        results = UndoStore.open(repo_root).restore()
    except FileNotFoundError as error:
        print(error)
        return

    restored = sum(1 for result in results if result["restored"])
    deleted = sum(1 for result in results if result["deleted"])
    print(f"↩️ Undo complete: restored {restored}, deleted {deleted}")


# Create the app objects, wire them together, and run one coding task.
def main() -> None:
    repo_root = Path(".").resolve()
    args = sys.argv[1:]

    if args == ["undo"]:
        _undo(repo_root)
        return

    if handle_session_viewer(repo_root, args):
        return

    if len(args) == 2 and args[0] == "resume":
        try:
            _resume_session(repo_root, args[1])
        except FileNotFoundError as error:
            print(error)
        return

    if args:
        print(USAGE)
        return

    _run_new_session(repo_root)


# Run the app when this file is executed directly.
if __name__ == "__main__":
    main()

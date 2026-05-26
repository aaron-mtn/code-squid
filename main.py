# main.py

"""Owns thin application wiring for standalone Code Squid; must not own core architecture, agent policy, or tool logic."""

import sys
from pathlib import Path

from agent.coding import CodingAgent
from config.settings import DEFAULT_BASE_URL, Settings, load_settings
from core.agent_loop import AgentLoop, RunResult
from core.approval import ApprovalPolicy
from core.compaction import Compactor
from core.model_adapter import ModelAdapter, ModelRequestError
from core.session import Session
from core.tool_executor import ToolExecutor
from core.tool_results import ToolResults
from providers.openai_compatible import OpenAICompatibleProvider
from providers.ollama import OllamaProvider
from storage.error_log import write_error_log
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
    display: TerminalDisplay,
) -> AgentLoop:
    provider = _build_provider(settings)

    model_adapter = ModelAdapter(
        provider=provider,
        model_name=settings.model.name,
        tool_call_content_mode=_tool_call_content_mode(settings),
    )
    compactor = Compactor(settings.compaction, model_adapter)

    tool_executor = ToolExecutor(
        repo_root=repo_root,
        session=session,
        undo_store=undo_store,
    )
    tool_results = ToolResults()
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
        compactor=compactor,
        max_tool_steps=settings.runtime.max_tool_steps,
        approval_policy=approval_policy,
    )

    return loop


def _build_provider(settings: Settings):
    if settings.model.provider == "ollama":
        if settings.model.base_url == DEFAULT_BASE_URL:
            return OllamaProvider(temperature=settings.model.temperature)
        return OllamaProvider(
            base_url=settings.model.base_url,
            temperature=settings.model.temperature,
        )

    return OpenAICompatibleProvider(
        base_url=settings.model.base_url,
        api_key=settings.model.api_key,
        temperature=settings.model.temperature,
        debug=settings.display.debug,
    )


def _tool_call_content_mode(settings: Settings) -> str:
    if settings.model.provider == "openrouter":
        return "null"
    return "empty"


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
    return 0


def _run_new_session(repo_root: Path) -> int:
    settings = load_settings(repo_root)
    display = TerminalDisplay(debug=settings.display.debug)
    display.start()
    task = input("Task: ")
    display.run_started()

    session = Session(repo_root=repo_root)
    session_store = SessionStore.create(repo_root=repo_root, task=task)
    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    agent = CodingAgent(task=task)
    loop = _build_loop(repo_root, session, session_store, agent, undo_store, settings, display)

    return _run_loop(repo_root, loop, display, session, session_store)


def _resume_session(repo_root: Path, session_id: str) -> int:
    settings = load_settings(repo_root)
    session_dir = _session_dir_for_resume(repo_root, session_id)
    if session_dir is None:
        return 0

    session_store = SessionStore.open(session_dir)
    session = Session(repo_root=repo_root)
    session.add_messages(*session_store.load_messages())

    display = TerminalDisplay(debug=settings.display.debug)
    display.start()
    follow_up_task = input("Follow-up task: ")
    display.run_started()
    agent = CodingAgent(task=follow_up_task)
    follow_up_message = agent.follow_up_message(follow_up_task)
    session.add_message(follow_up_message)
    session_store.append_message(follow_up_message)
    session_store.update_status("active")

    undo_store = UndoStore.create(repo_root, session_id=session_store.session_id)
    loop = _build_loop(repo_root, session, session_store, agent, undo_store, settings, display)
    return _run_loop(repo_root, loop, display, session, session_store)


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
def main() -> int:
    repo_root = Path(".").resolve()
    args = sys.argv[1:]

    if args == ["undo"]:
        _undo(repo_root)
        return 0

    if handle_session_viewer(repo_root, args):
        return 0

    if len(args) == 2 and args[0] == "resume":
        try:
            return _resume_session(repo_root, args[1])
        except FileNotFoundError as error:
            print(error)
        return 0

    if args:
        print(USAGE)
        return 0

    return _run_new_session(repo_root)


# Run the app when this file is executed directly.
if __name__ == "__main__":
    sys.exit(main())

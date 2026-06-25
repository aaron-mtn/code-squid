# main.py

"""Standalone Code Squid CLI entry point and command dispatcher."""

import os
import sys
from pathlib import Path

from prompt_toolkit.formatted_text import FormattedText

from agent.coding import CodingAgent
from config.settings import Settings, load_settings, write_approval_mode
from core.agent_loop import AgentLoop, RunResult
from core.model_adapter import ModelRequestError
from core.runner import (
    FRIENDLY_MODES,
    append_run_context,
    build_agent_loop,
    build_coding_task_run,
    resolve_skill_tools,
    startup_info,
)
from core.session import Session
from core.skills import discover_skills
from storage.error_log import write_error_log
from storage.session_index import latest_session_id, session_dir_for
from storage.session_store import SessionStore
from storage.undo_store import UndoStore
from ui.sessions import USAGE, handle_session_viewer
from ui.prompt_input import prompt_multiline_input
from ui.terminal import (
    INPUT_IDENTITY_LINE,
    INPUT_PROMPT_PREFIX,
    INPUT_PROMPT_STYLE,
    TerminalDisplay,
)


PROMPT_PREFIX = INPUT_PROMPT_PREFIX
PROMPT_STYLE = INPUT_PROMPT_STYLE
CANCELLED_BEFORE_RUN_MESSAGE = "⏹️ Cancelled before task started"
HELP_COMMAND = "/help"
NEW_COMMAND = "/new"
SKILL_COMMAND = "/skill"
EXIT_COMMANDS = {"/exit", "exit", "quit"}
HELP_TEXT = """\
Code Squid help

At the task prompt:
  Normal input runs a coding task.
  /skill shows the active skill and available skills.
  /skill <name> sets the active skill for future tasks and follow-ups.
  /skill none clears the active skill.
  Enter sends.
  Alt+Enter inserts a newline.
  Ctrl+C cancels before a run or interrupts an active run.

Shell commands:
  python main.py --cwd /path/to/project
  python main.py undo
  python main.py mode
  python main.py mode strict
  python main.py mode balanced
  python main.py mode yolo
  python main.py skills
  python main.py --skill architecture-review
  python main.py sessions
  python main.py show latest
  python main.py resume latest
  python main.py resume <session_id>"""

APPROVAL_MODES = {
    "strict": "always",
    "balanced": "guarded",
    "yolo": "never",
}


def _is_help_input(task: str) -> bool:
    return task.strip() == HELP_COMMAND


def _is_new_input(task: str) -> bool:
    return task.strip() == NEW_COMMAND


def _is_skill_input(task: str) -> bool:
    stripped = task.strip()
    return stripped == SKILL_COMMAND or stripped.startswith(f"{SKILL_COMMAND} ")


def _is_exit_input(task: str) -> bool:
    return task.strip() in EXIT_COMMANDS


def _print_help() -> None:
    print(HELP_TEXT)


def _format_skill_details(skill_name: str | None) -> list[str]:
    if skill_name is None:
        return ["Current skill: none"]

    skill = discover_skills().get(skill_name)
    lines = [f"Current skill: {skill_name}"]
    if skill is None:
        return lines

    if skill.allowed_tools:
        lines.append(f"Tools: {', '.join(skill.allowed_tools)}")
    if skill.prompt_sections:
        lines.append(f"Prompt overrides: {', '.join(skill.prompt_sections)}")
    return lines


def _format_available_skills() -> list[str]:
    skills = discover_skills()
    if not skills:
        return ["Available skills:", "none"]

    lines = ["Available skills:"]
    for skill in skills.values():
        lines.append(f"- {skill.name}: {skill.description}")
    return lines


def _format_skill_status(skill_name: str | None) -> str:
    return "\n".join(
        [
            *_format_skill_details(skill_name),
            "",
            *_format_available_skills(),
        ]
    )


def _print_skill_status(skill_name: str | None) -> None:
    print(_format_skill_status(skill_name))


def _handle_skill_input(task: str, skill_name: str | None) -> str | None:
    parts = task.strip().split()
    if len(parts) == 1:
        _print_skill_status(skill_name)
        return skill_name

    if len(parts) != 2:
        print("Usage: /skill [name|none]")
        return skill_name

    requested_skill = parts[1]
    if requested_skill in {"none", "default"}:
        print("Active skill cleared.")
        return None

    skills = discover_skills()
    skill = skills.get(requested_skill)
    if skill is None:
        print(f"Unknown skill: {requested_skill}")
        print("Run /skill to see available skills.")
        return skill_name

    print(f"Active skill set to: {skill.name}")
    if skill.allowed_tools:
        print(f"Tools: {', '.join(skill.allowed_tools)}")
    return skill.name


def _extract_cwd_arg(args: list[str]) -> tuple[str | None, list[str]]:
    if "--cwd" not in args:
        return None, args

    cwd_index = args.index("--cwd")
    if cwd_index + 1 >= len(args):
        raise ValueError("--cwd requires a path")

    cwd_arg = args[cwd_index + 1]
    remaining_args = args[:cwd_index] + args[cwd_index + 2 :]
    return cwd_arg, remaining_args


def _extract_skill_arg(args: list[str]) -> tuple[str | None, list[str]]:
    if "--skill" not in args:
        return None, args

    skill_index = args.index("--skill")
    if skill_index + 1 >= len(args):
        raise ValueError("--skill requires a skill name")

    skill_name = args[skill_index + 1]
    remaining_args = args[:skill_index] + args[skill_index + 2 :]
    return skill_name, remaining_args


def _resolve_workspace_root(cwd_arg: str | None) -> Path:
    workspace_root = Path.cwd() if cwd_arg is None else Path(cwd_arg).expanduser()
    resolved_root = workspace_root.resolve()

    if not resolved_root.exists():
        raise ValueError(f"--cwd path does not exist: {workspace_root}")
    if not resolved_root.is_dir():
        raise ValueError(f"--cwd path is not a directory: {workspace_root}")

    return resolved_root


def _prompt_task(label: str) -> str:
    return prompt_multiline_input(
        FormattedText([(PROMPT_STYLE, PROMPT_PREFIX)]),
        preface=FormattedText([(PROMPT_STYLE, INPUT_IDENTITY_LINE)]),
    )


def _prompt_task_or_cancel(label: str) -> str | None:
    try:
        return _prompt_task(label)
    except KeyboardInterrupt:
        print(CANCELLED_BEFORE_RUN_MESSAGE)
        return None


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
    return 0


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
    agent = CodingAgent(task=follow_up_task, skill=skill, tools=active_tools)
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


def _run_new_session(repo_root: Path, skill_name: str | None = None) -> int:
    settings = load_settings(repo_root)
    display = _run_display(repo_root, settings, skill_name)
    display.start()
    task = _prompt_task_or_cancel("Task")
    if task is None:
        return 0
    if _is_help_input(task):
        _print_help()
        return 0
    if not task.strip():
        print("No task entered; nothing to run.")
        return 0

    status, _ = _run_new_session_task(repo_root, task, settings, display, skill_name)
    return status


def _resume_session(repo_root: Path, session_id: str, skill_name: str | None = None) -> int:
    settings = load_settings(repo_root)
    display = _run_display(repo_root, settings, skill_name)
    display.start()
    follow_up_task = _prompt_task_or_cancel("Follow-up task")
    if follow_up_task is None:
        return 0
    if _is_help_input(follow_up_task):
        _print_help()
        return 0
    if not follow_up_task.strip():
        print("No task entered; nothing to run.")
        return 0

    status, _ = _run_follow_up_task(
        repo_root,
        session_id,
        follow_up_task,
        settings,
        display,
        skill_name,
    )
    return status


def _run_interactive(repo_root: Path, skill_name: str | None = None) -> int:
    settings = load_settings(repo_root)
    display = _run_display(repo_root, settings, skill_name)
    display.start()
    active_session_id: str | None = None

    while True:
        task = _prompt_task_or_cancel("Task")
        if task is None:
            return 0
        if _is_exit_input(task):
            return 0
        if _is_new_input(task):
            active_session_id = None
            continue
        if _is_help_input(task):
            _print_help()
            continue
        if _is_skill_input(task):
            skill_name = _handle_skill_input(task, skill_name)
            continue
        if not task.strip():
            continue

        if active_session_id is None:
            status, session_id = _run_new_session_task(
                repo_root,
                task,
                settings,
                display,
                skill_name,
            )
        else:
            status, session_id = _run_follow_up_task(
                repo_root,
                active_session_id,
                task,
                settings,
                display,
                skill_name,
            )

        if session_id is not None:
            active_session_id = session_id
        if status != 0:
            return status


def _undo(repo_root: Path) -> None:
    try:
        results = UndoStore.open(repo_root).restore()
    except FileNotFoundError as error:
        print(error)
        return

    restored = sum(1 for result in results if result["restored"])
    deleted = sum(1 for result in results if result["deleted"])
    print(f"↩️ Undo complete: restored {restored}, deleted {deleted}")


def _mode(repo_root: Path, args: list[str]) -> int:
    if not args:
        settings = load_settings(repo_root)
        approval_mode = settings.runtime.approval_mode
        friendly_mode = FRIENDLY_MODES[approval_mode]
        print(f"Current mode: {friendly_mode} (approval_mode={approval_mode})")
        return 0

    if len(args) != 1 or args[0] not in APPROVAL_MODES:
        print("Invalid mode. Valid options: strict, balanced, yolo")
        return 1

    friendly_mode = args[0]
    approval_mode = APPROVAL_MODES[friendly_mode]
    write_approval_mode(repo_root, approval_mode)

    if friendly_mode == "strict":
        print(
            "Mode set to strict (approval_mode=always). "
            "Code Squid will ask before every tool execution. This is not a sandbox."
        )
    elif friendly_mode == "balanced":
        print(
            "Mode set to balanced (approval_mode=guarded). "
            "Low-risk workspace actions can run without approval prompts."
        )
    else:
        print(
            "Mode set to yolo (approval_mode=never). "
            "Tools will run without approval prompts."
        )

    return 0


def _skills() -> int:
    print("\n".join(_format_available_skills()))
    return 0


# Parse CLI commands and run the selected standalone Code Squid flow.
def main() -> int:
    args = sys.argv[1:]
    try:
        cwd_arg, args = _extract_cwd_arg(args)
        skill_name, args = _extract_skill_arg(args)
        repo_root = _resolve_workspace_root(cwd_arg)
    except ValueError as error:
        print(error)
        return 1

    if args == ["skills"]:
        return _skills()

    if args == ["undo"]:
        _undo(repo_root)
        return 0

    if args and args[0] == "mode":
        return _mode(repo_root, args[1:])

    if handle_session_viewer(repo_root, args):
        return 0

    if len(args) == 2 and args[0] == "resume":
        try:
            return _resume_session(repo_root, args[1], skill_name)
        except ValueError as error:
            print(error)
            return 1
        except FileNotFoundError as error:
            print(error)
        return 0

    if args:
        print(USAGE)
        return 0

    try:
        return _run_interactive(repo_root, skill_name)
    except ValueError as error:
        print(error)
        return 1


# Run the app when this file is executed directly.
if __name__ == "__main__":
    sys.exit(main())

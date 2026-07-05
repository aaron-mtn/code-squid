# main.py

"""Standalone Code Squid CLI entry point and command dispatcher."""

import sys
from pathlib import Path

from prompt_toolkit.formatted_text import FormattedText

from cli.args import (
    _extract_cwd_arg,
    _extract_skill_arg,
    _resolve_workspace_root,
    parse_cli_args,
)
from cli.skills import (
    _format_available_skills,
    _format_skill_details,
    _format_skill_status,
    _handle_skill_input,
    _is_skill_input,
    _print_skill_status,
    _skills,
)
from cli.run import (
    _run_display,
    _run_follow_up_task,
    _run_loop,
    _run_new_session_task,
    _session_dir_for_resume,
)
from config.settings import load_settings, write_approval_mode
from core.runner import FRIENDLY_MODES
from storage.undo_store import UndoStore
from ui.sessions import USAGE, handle_session_viewer
from ui.prompt_input import prompt_multiline_input
from ui.terminal import (
    INPUT_IDENTITY_LINE,
    INPUT_PROMPT_PREFIX,
    INPUT_PROMPT_STYLE,
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


def _is_exit_input(task: str) -> bool:
    return task.strip() in EXIT_COMMANDS


def _print_help() -> None:
    print(HELP_TEXT)


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


# Parse CLI commands and run the selected standalone Code Squid flow.
def main() -> int:
    args = sys.argv[1:]
    try:
        parsed_args = parse_cli_args(args)
        repo_root = parsed_args.repo_root
        skill_name = parsed_args.skill_name
        args = parsed_args.remaining_args
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

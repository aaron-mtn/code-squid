# main.py

"""Standalone Code Squid CLI entry point and command dispatcher."""

import sys
from pathlib import Path

from cli.args import (
    _extract_cwd_arg,
    _extract_skill_arg,
    _resolve_workspace_root,
    parse_cli_args,
)
from cli.interactive import (
    CANCELLED_BEFORE_RUN_MESSAGE,
    EXIT_COMMANDS,
    HELP_COMMAND,
    HELP_TEXT,
    INPUT_IDENTITY_LINE,
    NEW_COMMAND,
    PROMPT_PREFIX,
    PROMPT_STYLE,
    SKILL_COMMAND,
    _is_exit_input,
    _is_help_input,
    _is_new_input,
    _print_help,
    _prompt_task,
    _prompt_task_or_cancel,
    _resume_session,
    _run_interactive,
    _run_new_session,
)
from cli.skills import (
    _format_available_skills,
    _format_skill_details,
    _format_skill_status,
    _print_skill_status,
    _skills,
)
from cli.run import (
    _run_follow_up_task,
    _run_loop,
    _run_new_session_task,
    _session_dir_for_resume,
)
from config.settings import load_settings, write_approval_mode
from core.runner import FRIENDLY_MODES
from storage.undo_store import UndoStore
from ui.sessions import USAGE, handle_session_viewer

APPROVAL_MODES = {
    "strict": "always",
    "balanced": "guarded",
    "yolo": "never",
}


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

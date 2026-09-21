"""Top-level Code Squid CLI command dispatch."""

from pathlib import Path

from code_squid.console.cli.cli_options import parse_cli_args
from code_squid.console.cli.control_commands import undo_latest_run
from code_squid.console.cli.prompt_loop import _resume_session, _run_interactive
from code_squid.console.cli.skill_commands import handle_skill_listing
from code_squid.settings import load_settings, write_approval_mode
from code_squid.console.ui.banner import FRIENDLY_APPROVAL_MODES
from code_squid.console.ui.sessions import handle_session_viewer


APPROVAL_MODES = {
    "strict": "always",
    "balanced": "guarded",
    "yolo": "never",
}


SHELL_HELP = """\
Code Squid

Usage:
  python main.py
  python main.py --cwd <path>
  python main.py --skill <name>
  python main.py safety [strict|balanced|yolo]
  python main.py skill
  python main.py sessions
  python main.py show latest
  python main.py show <session_id>
  python main.py resume latest
  python main.py resume <session_id>
  python main.py undo
  python main.py help
  python main.py --help
  python main.py -h
"""


def _undo(repo_root: Path) -> int:
    return 0 if undo_latest_run(repo_root) else 1


def _safety(repo_root: Path, args: list[str]) -> int:
    if not args:
        try:
            settings = load_settings(repo_root)
        except (OSError, ValueError) as error:
            print(f"Safety settings could not be loaded: {error}")
            return 1
        approval_mode = settings.runtime.approval_mode
        friendly_mode = FRIENDLY_APPROVAL_MODES[approval_mode]
        print(f"Current safety mode: {friendly_mode} (approval_mode={approval_mode})")
        return 0

    if len(args) != 1 or args[0] not in APPROVAL_MODES:
        print(
            "Invalid safety command. Usage: "
            "python main.py safety [strict|balanced|yolo]"
        )
        return 1

    friendly_mode = args[0]
    approval_mode = APPROVAL_MODES[friendly_mode]
    try:
        write_approval_mode(repo_root, approval_mode)
    except (OSError, ValueError) as error:
        print(f"Safety mode was not saved: {error}")
        return 1

    if friendly_mode == "strict":
        print(
            "Safety mode set to strict (approval_mode=always). "
            "Code Squid will ask before every tool execution. This is not a sandbox."
        )
    elif friendly_mode == "balanced":
        print(
            "Safety mode set to balanced (approval_mode=guarded). "
            "Low-risk workspace actions can run without approval prompts."
        )
    else:
        print(
            "Safety mode set to yolo (approval_mode=never). "
            "Tools will run without approval prompts."
        )

    return 0


def run_cli(args: list[str]) -> int:
    try:
        parsed_args = parse_cli_args(args)
        repo_root = parsed_args.repo_root
        skill_name = parsed_args.skill_name
        args = parsed_args.remaining_args
    except ValueError as error:
        print(error)
        return 1

    if args in (["help"], ["--help"], ["-h"]):
        print(SHELL_HELP, end="")
        return 0

    if args == ["skill"]:
        return handle_skill_listing()

    if args == ["undo"]:
        return _undo(repo_root)

    if args and args[0] == "undo":
        print("Usage: python main.py undo")
        return 1

    if args and args[0] == "safety":
        return _safety(repo_root, args[1:])

    session_status = handle_session_viewer(repo_root, args)
    if session_status is not None:
        return session_status

    if args and args[0] == "resume":
        if len(args) != 2:
            print(
                "Usage: python main.py resume latest | "
                "python main.py resume <session_id>"
            )
            return 1
        try:
            return _resume_session(repo_root, args[1], skill_name)
        except ValueError as error:
            print(error)
            return 1
        except FileNotFoundError as error:
            print(error)
            return 1
        except OSError as error:
            print(f"Code Squid setup failed: {error}")
            return 1

    if args:
        print(SHELL_HELP, end="")
        return 1

    try:
        return _run_interactive(repo_root, skill_name)
    except ValueError as error:
        print(error)
        return 1
    except OSError as error:
        print(f"Code Squid setup failed: {error}")
        return 1

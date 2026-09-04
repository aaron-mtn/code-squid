"""Interactive Code Squid prompt flows."""

from pathlib import Path

from prompt_toolkit.formatted_text import FormattedText

from code_squid.console.cli import session_runner
from code_squid.console.cli.session_runner import (
    _run_display,
    _run_follow_up_task,
    _run_new_session_task,
)
from code_squid.console.cli.control_commands import handle_control_command
from code_squid.console.cli.mod_commands import _handle_mod_input, _is_mod_input
from code_squid.console.cli.runtime_commands import handle_runtime_command
from code_squid.console.cli.skill_commands import (
    _handle_skill_input,
    _is_skill_input,
)
from code_squid.settings import load_settings
from code_squid.console.ui.prompt_input import prompt_multiline_input
from code_squid.console.ui.approval import (
    INPUT_PROMPT_PREFIX,
    INPUT_PROMPT_STYLE,
)
from code_squid.console.ui.display import INPUT_IDENTITY_LINE, TerminalDisplay
from code_squid.console.ui.binary_header import BinaryRainHeader
from code_squid.console.startup_menu import StartupMenu


PROMPT_PREFIX = INPUT_PROMPT_PREFIX
PROMPT_STYLE = INPUT_PROMPT_STYLE
CANCELLED_BEFORE_RUN_MESSAGE = "⏹️ Cancelled before task started"
HELP_COMMAND = "/help"
NEW_COMMAND = "/new"
SKILL_COMMAND = "/skill"
EXIT_COMMAND = "/exit"
HELP_TEXT = """\
Code Squid help

Core interaction:
  Normal input runs a coding task.
  /new starts a new session boundary.
  /exit exits the interactive prompt.

Input:
  Enter       Send
  Alt+Enter   New line
  Ctrl+C      Cancel before a run or stop the current run

Startup menu:
  Up from empty prompt   Focus menu
  Up/Down                Move selection
  Enter                  Open/select
  Esc                    Back / return to prompt

Specialization:
  /mod shows the active Mod and available Mods.
  /mod <name> selects a Mod for future tasks and follow-ups.
  /mod none clears the active Mod.
  /skill shows the active standalone Skill and available Skills
    (advanced/direct).
  /skill <name> selects a standalone Skill for future tasks and follow-ups.
  /skill none clears the active standalone Skill.

Runtime:
  /provider shows or changes the effective provider.
  /model shows or changes the effective model.
  /safety shows or changes the safety mode (strict, balanced, yolo).

Sessions and workspace:
  /sessions lists saved sessions for this workspace.
  /show [current|latest|<session_id>] shows a saved session.
  /resume latest or /resume <session_id> switches the active session.
  /undo restores the existing latest-run undo buffer.
  /cwd shows the immutable workspace root.
"""


def _is_help_input(task: str) -> bool:
    return task.strip() == HELP_COMMAND


def _is_new_input(task: str) -> bool:
    return task.strip() == NEW_COMMAND


def _is_exit_input(task: str) -> bool:
    return task.strip() == EXIT_COMMAND


def _print_help() -> None:
    print(HELP_TEXT)


def _prompt_task(label: str, animator: BinaryRainHeader | None = None) -> str:
    return prompt_multiline_input(
        FormattedText([(PROMPT_STYLE, PROMPT_PREFIX)]),
        preface=FormattedText([(PROMPT_STYLE, INPUT_IDENTITY_LINE)]),
        animator=animator,
    )


def _prompt_task_or_cancel(
    label: str,
    display: TerminalDisplay | None = None,
) -> str | None:
    try:
        if display is not None:
            display.prepare_header_for_prompt()
            return _prompt_task(label, display.header)
        return _prompt_task(label)
    except KeyboardInterrupt:
        print(CANCELLED_BEFORE_RUN_MESSAGE)
        return None


def _run_new_session(repo_root: Path, skill_name: str | None = None) -> int:
    settings = load_settings(repo_root)
    display = _run_display(repo_root, settings, skill_name)
    menu = StartupMenu(repo_root, settings, skill_name=skill_name)
    if hasattr(display, "set_startup_menu"):
        display.set_startup_menu(menu)
    try:
        display.start()
        task = _prompt_task_or_cancel("Task", display)
        settings = menu.settings
        if task is None:
            return 0
        if _is_help_input(task):
            _print_help()
            return 0
        if not task.strip():
            print("No task entered; nothing to run.")
            return 0

        if menu.mod_name is None:
            status, _ = _run_new_session_task(
                repo_root,
                task,
                settings,
                display,
                menu.skill_name,
            )
        else:
            status, _ = _run_new_session_task(
                repo_root,
                task,
                settings,
                display,
                mod_name=menu.mod_name,
            )
        return status
    finally:
        display.stop_header()


def _resume_session(repo_root: Path, session_id: str, skill_name: str | None = None) -> int:
    # Validate once before entering the shared interpreter. The path helper is
    # also the established seam that resolves ``latest`` to its concrete ID.
    session_dir = session_runner._session_dir_for_resume(repo_root, session_id)
    if session_dir is None:
        return 1
    return _run_interactive(repo_root, skill_name, active_session_id=session_dir.name)


def _run_interactive(
    repo_root: Path,
    skill_name: str | None = None,
    *,
    active_session_id: str | None = None,
) -> int:
    settings = load_settings(repo_root)
    display = _run_display(repo_root, settings, skill_name)
    mod_name: str | None = None
    menu = StartupMenu(repo_root, settings, mod_name=mod_name, skill_name=skill_name)
    if hasattr(display, "set_startup_menu"):
        display.set_startup_menu(menu)

    try:
        display.start()
        while True:
            task = _prompt_task_or_cancel("Task", display)
            settings = menu.settings
            mod_name = menu.mod_name
            skill_name = menu.skill_name
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
            handled, settings = handle_runtime_command(repo_root, task, settings)
            if handled:
                menu.sync(settings, mod_name=mod_name, skill_name=skill_name)
                continue
            handled, active_session_id = handle_control_command(
                repo_root,
                task,
                active_session_id,
            )
            if handled:
                continue
            if _is_skill_input(task):
                skill_name, mod_name = _handle_skill_input(task, skill_name, mod_name)
                display.set_specialization(mod_name=mod_name, skill_name=skill_name)
                menu.sync(settings, mod_name=mod_name, skill_name=skill_name)
                continue
            if _is_mod_input(task):
                mod_name, skill_name = _handle_mod_input(task, mod_name, skill_name)
                display.set_specialization(mod_name=mod_name, skill_name=skill_name)
                menu.sync(settings, mod_name=mod_name, skill_name=skill_name)
                continue
            if not task.strip():
                continue

            if active_session_id is None:
                if mod_name is None:
                    status, session_id = _run_new_session_task(
                        repo_root, task, settings, display, skill_name
                    )
                else:
                    status, session_id = _run_new_session_task(
                        repo_root, task, settings, display, mod_name=mod_name
                    )
            else:
                if mod_name is None:
                    status, session_id = _run_follow_up_task(
                        repo_root, active_session_id, task, settings, display, skill_name
                    )
                else:
                    status, session_id = _run_follow_up_task(
                        repo_root,
                        active_session_id,
                        task,
                        settings,
                        display,
                        mod_name=mod_name,
                    )

            if session_id is not None:
                active_session_id = session_id
            if status != 0:
                return status
    finally:
        display.stop_header()

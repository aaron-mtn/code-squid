"""Interactive Code Squid prompt flows."""

from pathlib import Path

from prompt_toolkit.formatted_text import FormattedText

from code_squid.console.cli import session_runner
from code_squid.console.cli.session_runner import (
    _run_display,
    _run_follow_up_task,
    _run_new_session_task,
)
from code_squid.console.cli.control_commands import (
    handle_control_command,
    handle_workspace_command,
    request_workspace_switch,
)
from code_squid.console.cli.mod_commands import _handle_mod_input, _is_mod_input
from code_squid.console.cli.runtime_commands import handle_runtime_command
from code_squid.console.cli.skill_commands import (
    _handle_skill_input,
    _is_skill_input,
)
from code_squid.settings import Settings, load_settings
from code_squid.console.ui.prompt_input import prompt_multiline_input
from code_squid.console.ui.approval import (
    INPUT_PROMPT_PREFIX,
    INPUT_PROMPT_STYLE,
)
from code_squid.console.ui.display import INPUT_IDENTITY_LINE, TerminalDisplay
from code_squid.console.ui.binary_header import BinaryRainHeader
from code_squid.console.ui.startup_application import (
    STARTUP_WORKSPACE_SELECTED,
)
from code_squid.console.startup_menu import StartupMenu


PROMPT_PREFIX = INPUT_PROMPT_PREFIX
PROMPT_STYLE = ""
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
  Enter         Send
  Shift+Enter   New line
  Alt+Enter     New line
  Ctrl+C        Cancel before a run or stop the current run

Startup menu:
  Up from empty prompt   Focus menu
  Up/Down                Move selection
  Enter                  Open/select
  Esc                    Back / return to prompt

Specialization:
  /mod shows the active Mod and available Mods.
  /mod <name> selects a Mod and its default Skill for future tasks and follow-ups.
  /mod none clears the active Mod and its packaged Skill.
  /skill shows the active Skill and available Skills in the active Mod
    or standalone Skills when no Mod is active.
  /skill <name> selects a packaged Skill, or a standalone Skill without a Mod.
  /skill none resets the Mod default, or clears the active standalone Skill.

Runtime:
  /provider shows the current provider and available providers.
  /provider use <name> selects a provider for configuration and use.
  /provider key <value> saves the current provider's API key.
  /provider url <value> saves the current provider's base URL.
  /provider status shows effective setup without exposing secrets.
  /model shows the effective model; /model <name> selects its exact ID.
  /safety shows or changes the safety mode (strict, balanced, yolo).
  /reasoning [show|hide] reports or changes reasoning display.
  /compact-at <tokens> sets the automatic compaction trigger (for example, 30k).

Sessions and workspace:
  /sessions lists saved sessions for this workspace.
  /show [current|latest|<session_id>] shows a saved session.
  /resume latest or /resume <session_id> switches the active session.
  /undo restores the existing latest-run undo buffer.
  /workspace                 Show the current workspace.
  /workspace <path>          Switch workspace.
  /cwd                       Show the current workspace root.
"""


def _is_help_input(task: str) -> bool:
    return task.strip() == HELP_COMMAND


def _is_new_input(task: str) -> bool:
    return task.strip() == NEW_COMMAND


def _is_exit_input(task: str) -> bool:
    return task.strip() == EXIT_COMMAND


def _print_help() -> None:
    print(HELP_TEXT)


def _composer_prompt(animator: BinaryRainHeader | None = None):
    """Return the padded identity/input rows with a focus-aware marker."""
    def fragments() -> FormattedText:
        menu = getattr(animator, "startup_menu", None)
        marker = "  " if menu is not None and menu.focused else PROMPT_PREFIX
        return FormattedText(
            [
                ("", f"  {INPUT_IDENTITY_LINE}\n  "),
                (PROMPT_STYLE, marker),
            ]
        )

    return fragments


def _prompt_task(label: str, animator: BinaryRainHeader | None = None) -> str | object:
    prompt = _composer_prompt(animator)
    if label != "Task":
        # Non-task handoffs still use the ordinary boxed PromptSession, but
        # identify the value being requested instead of showing the agent ID.
        prompt = FormattedText([("", f"  {label}\n  "), (PROMPT_STYLE, PROMPT_PREFIX)])
    return prompt_multiline_input(
        prompt,
        animator=animator,
        boxed=True,
    )


def _finish_startup_fade(display: TerminalDisplay) -> None:
    """Release real startup ownership; lightweight test displays own none."""
    finish = getattr(display, "finish_startup_fade", None)
    if finish is not None:
        finish()


def _wait_for_startup_fade(display: TerminalDisplay) -> None:
    """Join the natural startup fade without forcing its clean frame."""
    wait = getattr(display, "wait_for_startup_fade", None)
    if wait is not None:
        wait()


def _print_selected_session_notice(
    display: TerminalDisplay,
    menu: StartupMenu,
) -> None:
    """Print and consume the startup picker's pending saved-session notice."""
    notice = menu.take_selected_session_notice()
    if notice is not None:
        display.previous_session_loaded(*notice)


def _prompt_task_or_cancel(
    label: str,
    display: TerminalDisplay | None = None,
    menu: StartupMenu | None = None,
) -> str | object | None:
    try:
        if display is not None:
            animator = display.header if display.session_scene_active else None
            task = _prompt_task(label, animator)
            display.retire_session_scene()
            if task is STARTUP_WORKSPACE_SELECTED:
                # Workspace reconstruction must begin only after the sole
                # startup renderer has relinquished the terminal.
                _wait_for_startup_fade(display)
                return task
            assert isinstance(task, str)
            if menu is not None and menu.session_id is not None:
                # Session choices remain transient until composer submission.
                # Join before printing the one pending notice on primary.
                if animator is not None:
                    _wait_for_startup_fade(display)
                _print_selected_session_notice(display, menu)
            return task
        task = _prompt_task(label)
        assert isinstance(task, str)
        return task
    except KeyboardInterrupt:
        print(CANCELLED_BEFORE_RUN_MESSAGE)
        return None


def _selected_workspace(menu: StartupMenu) -> Path | None:
    """Return the recent workspace selected by the startup menu."""
    selection = menu.take_workspace_handoff()
    return request_workspace_switch(selection) if selection is not None else None


def _rebuild_workspace_runtime(
    selected_root: Path,
    current_root: Path,
    display: TerminalDisplay,
    *,
    mod_name: str | None,
    skill_name: str | None,
    active_session_id: str | None,
) -> tuple[Path, Settings, TerminalDisplay, StartupMenu, str | None]:
    """Reconstruct workspace-bound CLI objects around ``selected_root``."""

    workspace_changed = selected_root != current_root
    display.stop_header()
    # Settings are application-wide; reloading refreshes environment overrides
    # without allowing the selected repository to replace user preferences.
    settings = load_settings(selected_root)
    if workspace_changed:
        # Session IDs, titles, discovery, runners, and undo paths belong to one
        # root and must never leak across this reconstruction boundary.
        active_session_id = None
    replacement = _run_display(selected_root, settings, skill_name)
    menu = StartupMenu(
        selected_root,
        settings,
        mod_name=mod_name,
        skill_name=skill_name,
        session_id=active_session_id,
    )
    if hasattr(replacement, "set_startup_menu"):
        replacement.set_startup_menu(menu)
    replacement.start()
    return selected_root, settings, replacement, menu, active_session_id


def _run_new_session(workspace_root: Path, skill_name: str | None = None) -> int:
    settings = load_settings(workspace_root)
    display = _run_display(workspace_root, settings, skill_name)
    menu = StartupMenu(workspace_root, settings, skill_name=skill_name)
    if hasattr(display, "set_startup_menu"):
        display.set_startup_menu(menu)
    try:
        display.start()
        while True:
            task = _prompt_task_or_cancel("Task", display, menu)
            if task is not STARTUP_WORKSPACE_SELECTED:
                break
            selected_root = _selected_workspace(menu) or workspace_root
            # A workspace rebuild continues startup, including its current
            # specialization, rather than recursively starting another cycle.
            workspace_root, settings, display, menu, _ = _rebuild_workspace_runtime(
                selected_root,
                workspace_root,
                display,
                mod_name=menu.mod_name,
                skill_name=menu.skill_name,
                active_session_id=menu.session_id,
            )
        settings = menu.settings
        selected_session_id = menu.session_id
        if task is None:
            return 0
        if _is_help_input(task):
            _finish_startup_fade(display)
            _print_help()
            return 0
        if not task.strip():
            _finish_startup_fade(display)
            print("No task entered; nothing to run.")
            return 0

        if selected_session_id is not None:
            status, _ = _run_follow_up_task(
                workspace_root,
                selected_session_id,
                task,
                settings,
                display,
                menu.skill_name,
                mod_name=menu.mod_name,
            )
        elif menu.mod_name is None:
            status, _ = _run_new_session_task(
                workspace_root,
                task,
                settings,
                display,
                menu.skill_name,
            )
        else:
            status, _ = _run_new_session_task(
                workspace_root,
                task,
                settings,
                display,
                mod_name=menu.mod_name,
                skill_name=menu.skill_name,
            )
        return status
    finally:
        display.stop_header()


def _resume_session(workspace_root: Path, session_id: str, skill_name: str | None = None) -> int:
    # Validate once before entering the shared interpreter. The path helper is
    # also the established seam that resolves ``latest`` to its concrete ID.
    session_dir = session_runner._session_dir_for_resume(workspace_root, session_id)
    if session_dir is None:
        return 1
    return _run_interactive(workspace_root, skill_name, active_session_id=session_dir.name)


def _run_interactive(
    workspace_root: Path,
    skill_name: str | None = None,
    *,
    active_session_id: str | None = None,
) -> int:
    """Interpret on primary and join temporary startup rendering on cleanup."""
    settings = load_settings(workspace_root)
    display = _run_display(workspace_root, settings, skill_name)
    mod_name: str | None = None
    menu = StartupMenu(
        workspace_root,
        settings,
        mod_name=mod_name,
        skill_name=skill_name,
        session_id=active_session_id,
    )
    if hasattr(display, "set_startup_menu"):
        display.set_startup_menu(menu)

    try:
        display.start()
        while True:
            task = _prompt_task_or_cancel("Task", display, menu)
            if task is STARTUP_WORKSPACE_SELECTED:
                selected_root = _selected_workspace(menu) or workspace_root
                (
                    workspace_root,
                    settings,
                    display,
                    menu,
                    active_session_id,
                ) = _rebuild_workspace_runtime(
                    selected_root,
                    workspace_root,
                    display,
                    mod_name=menu.mod_name,
                    skill_name=menu.skill_name,
                    active_session_id=menu.session_id,
                )
                continue
            settings = menu.settings
            mod_name = menu.mod_name
            skill_name = menu.skill_name
            # The menu selects only an ID; the existing follow-up runner still
            # owns transcript loading and construction of the resumed run.
            active_session_id = menu.session_id
            if task is None:
                return 0
            if _is_exit_input(task):
                _finish_startup_fade(display)
                return 0
            if _is_new_input(task):
                _finish_startup_fade(display)
                active_session_id = None
                menu.session_id = None
                menu.session_title = None
                display.start_session_scene()
                continue
            if _is_help_input(task):
                _finish_startup_fade(display)
                _print_help()
                continue
            # Every remaining command handler can print directly. Finish the
            # startup renderer before dispatch, then restart no scene unless
            # this input proves to be an actual model task below.
            is_direct_command = (
                task.strip().startswith("/")
                or not task.strip()
            )
            if is_direct_command:
                _finish_startup_fade(display)
            handled, settings = handle_runtime_command(workspace_root, task, settings)
            if handled:
                # Runtime display preferences take effect in this persistent
                # prompt without rebuilding the session or model runtime.
                display.show_reasoning = settings.display.show_reasoning
                menu.sync(settings, mod_name=mod_name, skill_name=skill_name)
                continue
            handled, selected_root = handle_workspace_command(workspace_root, task)
            if handled:
                if selected_root is not None:
                    (
                        workspace_root,
                        settings,
                        display,
                        menu,
                        active_session_id,
                    ) = _rebuild_workspace_runtime(
                        selected_root,
                        workspace_root,
                        display,
                        mod_name=mod_name,
                        skill_name=skill_name,
                        active_session_id=active_session_id,
                    )
                continue
            handled, active_session_id = handle_control_command(
                workspace_root,
                task,
                active_session_id,
            )
            if handled:
                if active_session_id != menu.session_id:
                    menu.set_active_session(active_session_id)
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

            started_new_session = active_session_id is None
            if started_new_session:
                if mod_name is None:
                    status, session_id = _run_new_session_task(
                        workspace_root, task, settings, display, skill_name
                    )
                else:
                    status, session_id = _run_new_session_task(
                        workspace_root, task, settings, display, mod_name=mod_name,
                        skill_name=skill_name,
                    )
            else:
                if mod_name is None:
                    status, session_id = _run_follow_up_task(
                        workspace_root, active_session_id, task, settings, display, skill_name
                    )
                else:
                    status, session_id = _run_follow_up_task(
                        workspace_root,
                        active_session_id,
                        task,
                        settings,
                        display,
                        mod_name=mod_name,
                        skill_name=skill_name,
                    )

            if session_id is not None:
                active_session_id = session_id
                selected_title = task if started_new_session else menu.session_title
                menu.set_active_session(session_id, title=selected_title)
            if status != 0:
                return status
    finally:
        display.stop_header()

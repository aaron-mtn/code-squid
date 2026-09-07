"""Interactive session and workspace control commands for Code Squid."""

from pathlib import Path

from code_squid.app_paths import workspace_sessions_dir, workspace_undo_dir
from code_squid.console.ui.sessions import print_session, print_sessions
from squid_core.storage import UndoStore
from squid_core.storage.session_index import (
    latest_session_id,
    list_sessions,
    session_dir_for,
)


RECENT_SESSION_LIMIT = 20


def discover_recent_sessions(repo_root: Path) -> list[dict]:
    """Return the newest workspace session metadata for CLI selection surfaces."""
    return list_sessions(workspace_sessions_dir(repo_root))[:RECENT_SESSION_LIMIT]


def undo_latest_run(repo_root: Path) -> bool:
    """Restore the latest-run undo buffer and report whether it was usable."""

    try:
        results = UndoStore.open(workspace_undo_dir(repo_root)).restore()
    except FileNotFoundError as error:
        print(error)
        return False

    if not results:
        print("No changes are available to undo.")
        return False

    restored = sum(1 for result in results if result["restored"])
    deleted = sum(1 for result in results if result["deleted"])
    print(f"↩️ Undo complete: restored {restored}, deleted {deleted}")
    return True


def handle_control_command(
    repo_root: Path,
    command: str,
    active_session_id: str | None,
) -> tuple[bool, str | None]:
    """Handle a session/control command and return the active session ID."""

    parts = command.strip().split()
    if not parts or parts[0] not in {"/sessions", "/show", "/resume", "/undo", "/cwd"}:
        return False, active_session_id

    name, args = parts[0], parts[1:]
    if name == "/sessions":
        if args:
            print("Usage: /sessions")
        else:
            print_sessions(repo_root)
    elif name == "/show":
        _show_session(repo_root, args, active_session_id)
    elif name == "/resume":
        active_session_id = _resume(repo_root, args, active_session_id)
    elif name == "/undo":
        if args:
            print("Usage: /undo")
        else:
            undo_latest_run(repo_root)
    elif args:
        print("Usage: /cwd")
    else:
        print(f"Current workspace: {repo_root}")

    return True, active_session_id


def resolve_session_id(repo_root: Path, requested_id: str) -> str | None:
    """Resolve and validate an explicit or latest workspace session ID."""

    sessions_dir = workspace_sessions_dir(repo_root)
    session_id = requested_id
    if requested_id == "latest":
        session_id = latest_session_id(sessions_dir)
        if session_id is None:
            print("No saved sessions.")
            return None

    session_dir_for(sessions_dir, session_id)
    return session_id


def _show_session(repo_root: Path, args: list[str], active_session_id: str | None) -> None:
    if len(args) > 1:
        print("Usage: /show [current|latest|<session_id>]")
        return

    requested_id = args[0] if args else ("current" if active_session_id else "latest")
    if requested_id == "current":
        if active_session_id is None:
            print("No active session.")
            return
        requested_id = active_session_id

    try:
        print_session(repo_root, requested_id)
    except (FileNotFoundError, ValueError) as error:
        print(error)


def _resume(
    repo_root: Path,
    args: list[str],
    active_session_id: str | None,
) -> str | None:
    if len(args) != 1:
        print("Usage: /resume latest | /resume <session_id>")
        return active_session_id

    try:
        session_id = resolve_session_id(repo_root, args[0])
    except (FileNotFoundError, ValueError) as error:
        print(error)
        return active_session_id

    if session_id is not None:
        print(f"Active session: {session_id}")
        return session_id
    return active_session_id

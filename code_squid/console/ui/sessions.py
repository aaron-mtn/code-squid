"""Terminal rendering for saved Code Squid sessions."""

import json
from pathlib import Path

from code_squid.app_paths import workspace_sessions_dir
from code_squid.console.ui.formatting import SQUID_GLYPH
from squid_core.image_content import image_descriptor, image_marker
from squid_core.storage.session_index import (
    latest_session_id,
    list_sessions,
    load_session_entries,
    session_dir_for,
)


def print_sessions(repo_root: Path) -> None:
    """Print a compact index of saved sessions."""
    print(f"{SQUID_GLYPH} Code Squid Sessions")
    print()

    sessions = list_sessions(workspace_sessions_dir(repo_root))
    if not sessions:
        print("No saved sessions.")
        return

    for metadata in sessions:
        print(metadata.get("session_id", ""))
        print(f"  status: {metadata.get('status', '')}")
        print(f"  updated: {metadata.get('updated_at', '')}")
        print(f"  task: {metadata.get('task', '')}")
        print()


# Print metadata and message transcript for one saved session.
def print_session(repo_root: Path, session_id: str) -> bool:
    """Print one session and return whether the requested session exists."""
    sessions_dir = workspace_sessions_dir(repo_root)
    if session_id == "latest":
        session_id = latest_session_id(sessions_dir)
        if session_id is None:
            print("No saved sessions.")
            return False

    session_dir = session_dir_for(sessions_dir, session_id)
    metadata = session_dir.joinpath("metadata.json").read_text(encoding="utf-8")

    metadata_dict = json.loads(metadata)
    entries = load_session_entries(sessions_dir, session_id)

    print(f"{SQUID_GLYPH} Session: {metadata_dict.get('session_id', session_id)}")
    print(f"status: {metadata_dict.get('status', '')}")
    print(f"updated: {metadata_dict.get('updated_at', '')}")
    print(f"task: {metadata_dict.get('task', '')}")
    print(f"repo: {metadata_dict.get('repo_root', '')}")

    for entry in entries:
        if entry.get("type") == "run_context":
            print()
            print("[run context]")
            skill_name = entry.get("skill_name")
            print(f"skill: {skill_name if skill_name is not None else 'none'}")
            print(f"tools: {', '.join(entry.get('allowed_tools', []))}")
            print(f"prompt overrides: {', '.join(entry.get('prompt_overrides', []))}")
            continue

        if entry.get("type") != "message":
            continue

        message = entry.get("message", {})
        if not isinstance(message, dict):
            message = {}

        print()
        print(f"[{message.get('role', '')}]")
        content = message.get("content", "")
        if message.get("role") == "tool" and isinstance(content, str):
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                result = None
            image = image_descriptor(result)
            if image is not None:
                print(image_marker(result.get("path"), image))
                continue
        print(content)

    return True


# Handle tiny saved-session viewer subcommands and leave runs untouched.
def handle_session_viewer(repo_root: Path, args: list[str]) -> int | None:
    """Handle shell session-view commands, or return ``None`` if unrelated."""

    if not args or args[0] not in {"sessions", "show"}:
        return None

    if args == ["sessions"]:
        print_sessions(repo_root)
        return 0

    if args[0] == "sessions":
        print("Usage: python main.py sessions")
        return 1

    if len(args) == 2 and args[0] == "show":
        try:
            return 0 if print_session(repo_root, args[1]) else 1
        except (FileNotFoundError, ValueError) as error:
            print(error)
            return 1

    print("Usage: python main.py show latest | python main.py show <session_id>")
    return 1

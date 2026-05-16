"""Terminal rendering for saved Code Squid sessions."""

import json
from pathlib import Path

from storage.session_index import (
    latest_session_id,
    list_sessions,
    load_session_entries,
    session_dir_for,
)

USAGE = (
    "Usage: python main.py "
    "[sessions | show latest | show <session_id> | resume latest | resume <session_id>]"
)


# Print a compact index of saved sessions.
def print_sessions(repo_root: Path) -> None:
    print("🦑 Code Squid Sessions")
    print()

    sessions = list_sessions(repo_root)
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
def print_session(repo_root: Path, session_id: str) -> None:
    if session_id == "latest":
        session_id = latest_session_id(repo_root)
        if session_id is None:
            print("No saved sessions.")
            return

    session_dir = session_dir_for(repo_root, session_id)
    metadata = session_dir.joinpath("metadata.json").read_text(encoding="utf-8")

    metadata_dict = json.loads(metadata)
    entries = load_session_entries(repo_root, session_id)

    print(f"🦑 Session: {metadata_dict.get('session_id', session_id)}")
    print(f"status: {metadata_dict.get('status', '')}")
    print(f"updated: {metadata_dict.get('updated_at', '')}")
    print(f"task: {metadata_dict.get('task', '')}")
    print(f"repo: {metadata_dict.get('repo_root', '')}")

    for entry in entries:
        if entry.get("type") != "message":
            continue

        message = entry.get("message", {})
        if not isinstance(message, dict):
            message = {}

        print()
        print(f"[{message.get('role', '')}]")
        print(message.get("content", ""))


# Handle tiny saved-session viewer subcommands and leave runs untouched.
def handle_session_viewer(repo_root: Path, args: list[str]) -> bool:
    if not args or args[0] == "resume":
        return False

    if args == ["sessions"]:
        print_sessions(repo_root)
        return True

    if len(args) == 2 and args[0] == "show":
        try:
            print_session(repo_root, args[1])
        except FileNotFoundError as error:
            print(error)
        return True

    print(USAGE)
    return True

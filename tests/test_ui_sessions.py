from pathlib import Path

from code_squid.app_paths import workspace_sessions_dir
from squid_core.storage import SessionStore
from code_squid.console.ui.sessions import handle_session_viewer, print_session


def test_print_session_shows_run_context_events(
    tmp_path: Path,
    capsys,
) -> None:
    store = SessionStore.create(
        workspace_sessions_dir(tmp_path),
        "debug context",
        workspace_root=tmp_path,
    )
    store.append_run_context(
        skill_name="user-review",
        allowed_tools=["run_command", "read_file"],
        prompt_overrides=["TOOL_USAGE_GUIDANCE", "FINAL_SUMMARY_REQUIREMENTS"],
    )
    store.append_message({"role": "user", "content": "review it"})

    print_session(tmp_path, store.session_id)

    output = capsys.readouterr().out
    assert "[run context]" in output
    assert "skill: user-review" in output
    assert "tools: read_file, run_command" in output
    assert "prompt overrides: FINAL_SUMMARY_REQUIREMENTS, TOOL_USAGE_GUIDANCE" in output
    assert "[user]" in output


def test_session_viewer_latest_selects_newest_session(tmp_path: Path, capsys) -> None:
    store = SessionStore.create(
        workspace_sessions_dir(tmp_path),
        "latest session",
        workspace_root=tmp_path,
    )

    assert handle_session_viewer(tmp_path, ["show", "latest"]) == 0

    assert f"Session: {store.session_id}" in capsys.readouterr().out


def test_session_viewer_reports_invalid_session_id_without_escaping(
    tmp_path: Path,
    capsys,
) -> None:
    assert handle_session_viewer(tmp_path, ["show", "../x"]) == 1

    assert "Invalid session ID" in capsys.readouterr().out

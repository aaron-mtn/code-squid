from pathlib import Path

from storage.session_store import SessionStore
from ui.sessions import print_session


def test_print_session_shows_run_context_events(
    tmp_path: Path,
    capsys,
) -> None:
    store = SessionStore.create(tmp_path, "debug context")
    store.append_run_context(
        skill_name="architecture-review",
        allowed_tools=["run_command", "read_file"],
        prompt_overrides=["TOOL_USAGE_GUIDANCE", "TASK_PROMPT"],
    )
    store.append_message({"role": "user", "content": "review it"})

    print_session(tmp_path, store.session_id)

    output = capsys.readouterr().out
    assert "[run context]" in output
    assert "skill: architecture-review" in output
    assert "tools: read_file, run_command" in output
    assert "prompt overrides: TASK_PROMPT, TOOL_USAGE_GUIDANCE" in output
    assert "[user]" in output

from core.action_preflight import ActionPreflight


def test_allowed_guarded_action_passes_through_unchanged(tmp_path) -> None:
    target = tmp_path / "README.md"
    action = {"tool": "read_file", "args": {"path": str(target)}}

    decision = ActionPreflight(tmp_path, "guarded").check(action)

    assert decision.approval_action == action
    assert decision.execution_action == action


def test_outside_workspace_action_requires_approval_and_marks_execution(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    action = {
        "tool": "write_file",
        "args": {"path": str(tmp_path / "outside.txt"), "content": "hello"},
    }

    decision = ActionPreflight(workspace, "guarded").check(action)

    assert "outside the workspace root" in decision.approval_action["approval_reason"]
    assert decision.execution_action == {
        **action,
        "outside_workspace_approved": True,
    }


def test_guarded_command_reason_is_combined_after_hook_reason(tmp_path) -> None:
    action = {"tool": "run_command", "args": {"command": "mkdir build"}}

    decision = ActionPreflight(tmp_path, "guarded").check(
        action,
        additional_approval_reason="hook reason",
    )

    assert decision.approval_action["approval_reason"] == (
        "hook reason; Command may modify files"
    )
    assert decision.execution_action == action

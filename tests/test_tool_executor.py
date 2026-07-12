from pathlib import Path
import sys

from core.session import Session
import core.tool_executor as tool_executor_module
from core.tool_executor import ToolExecutor
from core.platform_context import PlatformContext


class FakeUndoStore:
    def __init__(self) -> None:
        self.paths = []
        self.contents = []

    def snapshot_file(self, path: str) -> None:
        self.paths.append(path)
        self.contents.append(Path(path).read_text(encoding="utf-8"))


def test_write_file_snapshots_target_before_write(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("before", encoding="utf-8")
    undo_store = FakeUndoStore()
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
        undo_store=undo_store,
    )

    result = executor.execute(
        {
            "tool": "write_file",
            "args": {"path": str(target), "content": "after"},
        }
    )

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "after"
    assert undo_store.paths == [str(target)]
    assert undo_store.contents == ["before"]


def test_successful_apply_patch_snapshots_and_records_file_written(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("before", encoding="utf-8")
    undo_store = FakeUndoStore()
    session = Session(repo_root=tmp_path)
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=session,
        undo_store=undo_store,
    )

    result = executor.execute(
        {
            "tool": "apply_patch",
            "args": {"path": str(target), "old_text": "before", "new_text": "after"},
        }
    )

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "after"
    assert session.files_written == {str(target)}
    assert undo_store.paths == [str(target)]
    assert undo_store.contents == ["before"]


def test_read_file_and_run_command_do_not_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("content", encoding="utf-8")
    undo_store = FakeUndoStore()
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
        undo_store=undo_store,
    )

    read_result = executor.execute(
        {
            "tool": "read_file",
            "args": {"path": str(target)},
        }
    )
    command_result = executor.execute(
        {
            "tool": "run_command",
            "args": {"command": "$true" if sys.platform == "win32" else "true"},
        }
    )

    assert read_result["ok"] is True
    assert command_result["ok"] is True
    assert undo_store.paths == []


def test_blocked_read_file_does_not_call_tool(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    calls = []

    def fake_execute(repo_root: Path, **args) -> dict:
        calls.append((repo_root, args))
        return {"ok": True, "tool": "read_file", "path": args["path"]}

    monkeypatch.setattr(
        tool_executor_module,
        "TOOLS",
        {"read_file": {"execute": fake_execute}},
    )
    executor = ToolExecutor(
        repo_root=workspace,
        session=Session(repo_root=workspace),
    )

    result = executor.execute(
        {
            "tool": "read_file",
            "args": {"path": str(outside)},
        }
    )

    assert result["ok"] is False
    assert "outside the workspace root" in result["error"]
    assert calls == []


def test_blocked_write_file_does_not_snapshot_or_call_tool(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    undo_store = FakeUndoStore()
    calls = []

    def fake_execute(repo_root: Path, **args) -> dict:
        calls.append((repo_root, args))
        return {"ok": True, "tool": "write_file", "path": args["path"]}

    monkeypatch.setattr(
        tool_executor_module,
        "TOOLS",
        {"write_file": {"execute": fake_execute}},
    )
    executor = ToolExecutor(
        repo_root=workspace,
        session=Session(repo_root=workspace),
        undo_store=undo_store,
    )

    result = executor.execute(
        {
            "tool": "write_file",
            "args": {"path": str(outside), "content": "outside"},
        }
    )

    assert result["ok"] is False
    assert "outside the workspace root" in result["error"]
    assert undo_store.paths == []
    assert calls == []


def test_apply_patch_respects_workspace_policy(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    undo_store = FakeUndoStore()
    calls = []

    def fake_execute(repo_root: Path, **args) -> dict:
        calls.append((repo_root, args))
        return {"ok": True, "tool": "apply_patch", "path": args["path"]}

    monkeypatch.setattr(
        tool_executor_module,
        "TOOLS",
        {"apply_patch": {"execute": fake_execute}},
    )
    executor = ToolExecutor(
        repo_root=workspace,
        session=Session(repo_root=workspace),
        undo_store=undo_store,
    )

    result = executor.execute(
        {
            "tool": "apply_patch",
            "args": {"path": str(outside), "old_text": "old", "new_text": "new"},
        }
    )

    assert result["ok"] is False
    assert "outside the workspace root" in result["error"]
    assert undo_store.paths == []
    assert calls == []


def test_run_command_is_not_restricted_by_workspace_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    def fake_execute(repo_root: Path, **args) -> dict:
        calls.append((repo_root, args))
        return {"ok": True, "tool": "run_command", "command": args["command"]}

    monkeypatch.setattr(
        tool_executor_module,
        "TOOLS",
        {"run_command": {"execute": fake_execute}},
    )
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
    )

    result = executor.execute(
        {
            "tool": "run_command",
            "args": {"command": "cat /etc/hosts"},
        }
    )

    assert result["ok"] is True
    assert calls == [(tmp_path, {"command": "cat /etc/hosts"})]


def test_only_builtin_run_command_receives_platform_context(monkeypatch, tmp_path: Path) -> None:
    context = PlatformContext("Windows", "PowerShell", "pwsh", "\\", True)
    calls = []

    def builtin_command(repo_root: Path, **args) -> dict:
        calls.append(("command", args))
        return {"ok": True, "tool": "run_command"}

    def other_tool(repo_root: Path, **args) -> dict:
        calls.append(("other", args))
        return {"ok": True, "tool": "other"}

    monkeypatch.setattr(tool_executor_module, "BUILTIN_RUN_COMMAND", builtin_command)
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
        tools={
            "run_command": {"execute": builtin_command},
            "other": {"execute": other_tool},
        },
        platform_context=context,
    )

    executor.execute({"tool": "run_command", "args": {"command": "Get-ChildItem"}})
    executor.execute({"tool": "other", "args": {"value": 1}})

    assert calls == [
        ("command", {"command": "Get-ChildItem", "platform_context": context}),
        ("other", {"value": 1}),
    ]


def test_allow_outside_workspace_allows_outside_file_paths_through(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside_read = tmp_path / "outside-read.txt"
    outside_write = tmp_path / "outside-write.txt"
    workspace.mkdir()
    calls = []

    def fake_execute(repo_root: Path, **args) -> dict:
        calls.append((repo_root, args))
        return {"ok": True, "path": args["path"]}

    monkeypatch.setattr(
        tool_executor_module,
        "TOOLS",
        {
            "read_file": {"execute": fake_execute},
            "write_file": {"execute": fake_execute},
            "apply_patch": {"execute": fake_execute},
        },
    )
    executor = ToolExecutor(
        repo_root=workspace,
        session=Session(repo_root=workspace),
        allow_outside_workspace=True,
    )

    result = executor.execute(
        {
            "tool": "read_file",
            "args": {"path": str(outside_read)},
        }
    )
    write_result = executor.execute(
        {
            "tool": "write_file",
            "args": {"path": str(outside_write), "content": "outside"},
        }
    )
    patch_result = executor.execute(
        {
            "tool": "apply_patch",
            "args": {"path": str(outside_write), "old_text": "old", "new_text": "new"},
        }
    )

    assert result["ok"] is True
    assert write_result["ok"] is True
    assert patch_result["ok"] is True
    assert calls == [
        (workspace, {"path": str(outside_read)}),
        (workspace, {"path": str(outside_write), "content": "outside"}),
        (workspace, {"path": str(outside_write), "old_text": "old", "new_text": "new"}),
    ]


def test_workspace_boundary_approval_allows_outside_file_path_through(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    calls = []

    def fake_execute(repo_root: Path, **args) -> dict:
        calls.append((repo_root, args))
        return {"ok": True, "tool": "read_file", "path": args["path"]}

    monkeypatch.setattr(
        tool_executor_module,
        "TOOLS",
        {"read_file": {"execute": fake_execute}},
    )
    executor = ToolExecutor(
        repo_root=workspace,
        session=Session(repo_root=workspace),
    )

    result = executor.execute(
        {
            "tool": "read_file",
            "args": {"path": str(outside)},
            "outside_workspace_approved": True,
        }
    )

    assert result["ok"] is True
    assert calls == [(workspace, {"path": str(outside)})]

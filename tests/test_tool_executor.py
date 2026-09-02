from pathlib import Path
import sys

from squid_core.session import Session
import squid_core.tools.executor as tool_executor_module
from squid_core.tools import ToolExecutor
from squid_core.platform_context import PlatformContext
from squid_core.storage import UndoStore


class FakeUndoStore:
    def __init__(self) -> None:
        self.paths = []
        self.contents = []

    def snapshot_file(self, path: str) -> None:
        self.paths.append(path)
        self.contents.append(Path(path).read_text(encoding="utf-8"))

    def has_snapshot(self, path: str) -> bool:
        return path in self.paths

    def discard_snapshot(self, path: str) -> bool:
        if path not in self.paths:
            return False
        position = self.paths.index(path)
        self.paths.pop(position)
        self.contents.pop(position)
        return True

    def discard_snapshot_if_unchanged(self, path: str) -> bool:
        if path not in self.paths:
            return False
        position = self.paths.index(path)
        if Path(path).read_text(encoding="utf-8") != self.contents[position]:
            return False
        return self.discard_snapshot(path)


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


def test_successful_write_file_produces_usable_undo_state(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("before", encoding="utf-8")
    undo_store = UndoStore.create(tmp_path / ".undo")
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
    assert len(undo_store.load_index()) == 1
    undo_store.restore()
    assert target.read_text(encoding="utf-8") == "before"


def test_failed_write_file_discards_new_undo_state(tmp_path: Path) -> None:
    target = tmp_path / "missing-parent" / "target.txt"
    undo_store = UndoStore.create(tmp_path / ".undo")
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

    assert result["ok"] is False
    assert not target.exists()
    assert undo_store.load_index() == []
    assert list(undo_store.files_dir.iterdir()) == []


def test_successful_apply_patch_produces_usable_undo_state(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("before", encoding="utf-8")
    undo_store = UndoStore.create(tmp_path / ".undo")
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
        undo_store=undo_store,
    )

    result = executor.execute(
        {
            "tool": "apply_patch",
            "args": {"path": str(target), "old_text": "before", "new_text": "after"},
        }
    )

    assert result["ok"] is True
    assert len(undo_store.load_index()) == 1
    undo_store.restore()
    assert target.read_text(encoding="utf-8") == "before"


def test_failed_apply_patch_discards_new_undo_state(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("before", encoding="utf-8")
    undo_store = UndoStore.create(tmp_path / ".undo")
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
        undo_store=undo_store,
    )

    result = executor.execute(
        {
            "tool": "apply_patch",
            "args": {"path": str(target), "old_text": "missing", "new_text": "after"},
        }
    )

    assert result["ok"] is False
    assert target.read_text(encoding="utf-8") == "before"
    assert undo_store.load_index() == []
    assert list(undo_store.files_dir.iterdir()) == []


def test_failed_mutation_preserves_previous_successful_undo_state(tmp_path: Path) -> None:
    changed = tmp_path / "changed.txt"
    unchanged = tmp_path / "unchanged.txt"
    changed.write_text("original", encoding="utf-8")
    unchanged.write_text("untouched", encoding="utf-8")
    undo_store = UndoStore.create(tmp_path / ".undo")
    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
        undo_store=undo_store,
    )

    successful_result = executor.execute(
        {
            "tool": "write_file",
            "args": {"path": str(changed), "content": "changed"},
        }
    )
    failed_result = executor.execute(
        {
            "tool": "apply_patch",
            "args": {"path": str(unchanged), "old_text": "missing", "new_text": "replacement"},
        }
    )

    assert successful_result["ok"] is True
    assert failed_result["ok"] is False
    assert [record["path"] for record in undo_store.load_index()] == [str(changed)]
    undo_store.restore()
    assert changed.read_text(encoding="utf-8") == "original"
    assert unchanged.read_text(encoding="utf-8") == "untouched"


def test_mutation_exception_retains_snapshot_for_possible_partial_write(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("before", encoding="utf-8")
    undo_store = UndoStore.create(tmp_path / ".undo")

    def partially_write_then_raise(_repo_root: Path, **args) -> dict:
        Path(args["path"]).write_text("partial", encoding="utf-8")
        raise OSError("write interrupted")

    executor = ToolExecutor(
        repo_root=tmp_path,
        session=Session(repo_root=tmp_path),
        undo_store=undo_store,
        tools={"write_file": {"execute": partially_write_then_raise}},
    )

    result = executor.execute(
        {
            "tool": "write_file",
            "args": {"path": str(target), "content": "after"},
        }
    )

    assert result["ok"] is False
    assert target.read_text(encoding="utf-8") == "partial"
    assert len(undo_store.load_index()) == 1
    undo_store.restore()
    assert target.read_text(encoding="utf-8") == "before"


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

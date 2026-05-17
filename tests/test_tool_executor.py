from pathlib import Path

from core.session import Session
from core.tool_executor import ToolExecutor


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
            "args": {"command": "true"},
        }
    )

    assert read_result["ok"] is True
    assert command_result["ok"] is True
    assert undo_store.paths == []

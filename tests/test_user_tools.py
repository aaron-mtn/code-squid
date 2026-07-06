from pathlib import Path

import pytest

from core.extension_paths import CODE_SQUID_HOME_ENV
from core.user_tools import UserTool, UserToolError, discover_user_tools, load_user_tool


def _write_tool(home: Path, directory_name: str, metadata: str, source: str = "") -> Path:
    tool_dir = home / "tools" / directory_name
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.yaml").write_text(metadata, encoding="utf-8")
    if source:
        (tool_dir / "tool.py").write_text(source, encoding="utf-8")
    return tool_dir


def test_discovers_valid_user_tool_from_code_squid_home(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(
        home,
        "local_search",
        """name: local_search
description: Search local notes.
version: "1.2.0"
entrypoint: search.py
function: run_search
args:
  query:
    type: string
safety:
  network: false
""",
    )

    assert discover_user_tools() == {
        "local_search": UserTool(
            name="local_search",
            description="Search local notes.",
            version="1.2.0",
            entrypoint="search.py",
            function="run_search",
            args={"query": {"type": "string"}},
            safety={"network": False},
            source="user",
            editable=True,
        )
    }


@pytest.mark.parametrize(
    ("directory_name", "metadata"),
    [
        ("BadName", "name: BadName\n"),
        ("bad.name", "name: bad.name\n"),
        ("bad name", "name: bad name\n"),
    ],
)
def test_rejects_unsafe_names(
    tmp_path: Path,
    directory_name: str,
    metadata: str,
) -> None:
    tool_dir = _write_tool(tmp_path, directory_name, metadata)

    with pytest.raises(UserToolError, match="tool name must contain only"):
        load_user_tool(tool_dir)


def test_rejects_mismatch_between_folder_and_yaml_name(tmp_path: Path) -> None:
    tool_dir = _write_tool(tmp_path, "folder_name", "name: yaml_name\n")

    with pytest.raises(UserToolError, match="must match folder name"):
        load_user_tool(tool_dir)


def test_handles_missing_optional_fields_with_defaults(tmp_path: Path) -> None:
    tool_dir = _write_tool(tmp_path, "minimal", "name: minimal\n")

    assert load_user_tool(tool_dir) == UserTool(
        name="minimal",
        description="",
        version="",
        entrypoint="tool.py",
        function="run",
        args={},
        safety={},
        source="user",
        editable=True,
    )


@pytest.mark.parametrize(
    "metadata",
    [
        "name malformed\n",
        '{"name": "broken"',
        "name: broken\nargs: [\n",
    ],
)
def test_handles_malformed_yaml_json_safely(tmp_path: Path, metadata: str) -> None:
    tool_dir = _write_tool(tmp_path, "broken", metadata)

    with pytest.raises(UserToolError):
        load_user_tool(tool_dir)


def test_discovery_skips_malformed_tools_independently(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(home, "broken", "name malformed\n")
    _write_tool(home, "valid", "name: valid\n")

    assert discover_user_tools() == {"valid": UserTool(name="valid")}


def test_does_not_import_or_execute_tool_py_during_discovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    marker = home / "imported"
    _write_tool(
        home,
        "passive",
        "name: passive\nentrypoint: tool.py\n",
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
    )

    assert discover_user_tools() == {"passive": UserTool(name="passive")}
    assert not marker.exists()


def test_empty_tools_dir_returns_empty_dict(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    (home / "tools").mkdir(parents=True)

    assert discover_user_tools() == {}

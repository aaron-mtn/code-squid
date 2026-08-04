from pathlib import Path

import pytest

from core.extension_paths import CODE_SQUID_HOME_ENV
from core.extensions import set_active_extension
from core.session import Session
from core.tool_executor import ToolExecutor
from core.user_tools import (
    UserTool,
    UserToolError,
    build_user_tool_registry,
    build_user_tool_registry_from_metadata,
    discover_user_tools,
    execute_user_tool,
    load_user_tool,
)


def _write_tool(home: Path, directory_name: str, metadata: str, source: str = "") -> Path:
    tool_dir = home / "tools" / directory_name
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.yaml").write_text(metadata, encoding="utf-8")
    if source:
        (tool_dir / "tool.py").write_text(source, encoding="utf-8")
    return tool_dir


def _write_extension_tool(
    home: Path,
    extension_name: str,
    tool_name: str,
    metadata: str | None = None,
    source: str = "",
    *,
    extension_metadata: str | None = None,
) -> Path:
    extension_dir = home / "extensions" / extension_name
    extension_dir.mkdir(parents=True, exist_ok=True)
    (extension_dir / "extension.yaml").write_text(
        extension_metadata
        or f"""name: {extension_name}
tools:
  - {tool_name}
""",
        encoding="utf-8",
    )
    tool_dir = extension_dir / "tools" / tool_name
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.yaml").write_text(metadata or f"name: {tool_name}\n", encoding="utf-8")
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


def test_accepts_python_identifier_function_name(tmp_path: Path) -> None:
    tool_dir = _write_tool(
        tmp_path,
        "valid_function",
        "name: valid_function\nfunction: run_tool\n",
    )

    assert load_user_tool(tool_dir) == UserTool(
        name="valid_function",
        function="run_tool",
    )


@pytest.mark.parametrize("function", ["bad-name", "bad name", "123run"])
def test_discovery_skips_invalid_function_names(
    monkeypatch,
    tmp_path: Path,
    function: str,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(
        home,
        "invalid_function",
        f"name: invalid_function\nfunction: {function}\n",
    )
    _write_tool(home, "valid", "name: valid\n")

    assert discover_user_tools() == {"valid": UserTool(name="valid")}


@pytest.mark.parametrize("function", ["bad-name", "bad name", "123run"])
def test_rejects_invalid_function_names(tmp_path: Path, function: str) -> None:
    tool_dir = _write_tool(
        tmp_path,
        "invalid_function",
        f"name: invalid_function\nfunction: {function}\n",
    )

    with pytest.raises(UserToolError, match="function must be a valid Python identifier"):
        load_user_tool(tool_dir)


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


def test_user_tool_registry_imports_tool_py_only_during_execution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    marker = home / "imported"
    _write_tool(
        home,
        "lazy",
        "name: lazy\n",
        f"""
from pathlib import Path
Path({str(marker)!r}).write_text("imported")

def run(args, context=None):
    return "done"
""",
    )

    registry = build_user_tool_registry()

    assert not marker.exists()
    assert registry["lazy"]["execute"](tmp_path)["message"] == "done"
    assert marker.read_text(encoding="utf-8") == "imported"


def test_explicit_user_tool_metadata_builds_executable_registry_without_discovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tool_dir = _write_tool(
        tmp_path / "package",
        "package_echo",
        "name: package_echo\n",
        "def run(args, context=None):\n    return args['message']\n",
    )
    tool = load_user_tool(tool_dir, source="mod", editable=False)
    assert tool is not None
    monkeypatch.setattr(
        "core.user_tools.discover_user_tools",
        lambda: pytest.fail("explicit registry must not rediscover tools"),
    )

    registry = build_user_tool_registry_from_metadata(
        {tool.name: tool},
        session_id="mod-session",
    )

    assert registry["package_echo"]["source"] == "mod"
    assert registry["package_echo"]["execute"](tmp_path, message="hello")["message"] == "hello"


def test_explicit_user_tool_registry_does_not_import_source_until_execution(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "imported"
    tool_dir = _write_tool(
        tmp_path / "package",
        "lazy_package_tool",
        "name: lazy_package_tool\n",
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n"
        "def run(args, context=None):\n    return 'done'\n",
    )
    tool = load_user_tool(tool_dir)
    assert tool is not None

    registry = build_user_tool_registry_from_metadata({tool.name: tool})

    assert not marker.exists()
    assert registry[tool.name]["execute"](tmp_path)["message"] == "done"
    assert marker.exists()


def test_no_active_extension_leaves_user_tool_discovery_unchanged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(home, "loose", "name: loose\n")
    _write_extension_tool(home, "bundle", "extension_tool")

    assert set(discover_user_tools()) == {"loose"}


def test_active_extension_tool_appears_in_discovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    tool_dir = _write_extension_tool(
        home,
        "repo-inspector",
        "line_count",
        "name: line_count\ndescription: Count lines.\n",
    )
    set_active_extension("repo-inspector")

    tools = discover_user_tools()

    assert "line_count" in tools
    assert tools["line_count"].source == "extension"
    assert tools["line_count"].editable is False
    assert tools["line_count"].path == tool_dir


def test_inactive_extension_tool_does_not_appear(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension_tool(home, "repo-inspector", "line_count")

    assert "line_count" not in discover_user_tools()


def test_invalid_active_extension_tool_does_not_appear(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension_tool(
        home,
        "repo-inspector",
        "line_count",
        extension_metadata="""name: repo-inspector
default_skill: missing
tools:
  - line_count
""",
    )
    set_active_extension("repo-inspector")

    assert "line_count" not in discover_user_tools()


def test_loose_user_tool_wins_over_active_extension_duplicate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(home, "line_count", "name: line_count\ndescription: Loose tool.\n")
    _write_extension_tool(
        home,
        "repo-inspector",
        "line_count",
        "name: line_count\ndescription: Extension tool.\n",
    )
    set_active_extension("repo-inspector")

    tools = discover_user_tools()

    assert tools["line_count"].description == "Loose tool."
    assert tools["line_count"].source == "user"


def test_extension_tool_registry_executes_from_extension_folder(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    tool_dir = _write_extension_tool(
        home,
        "repo-inspector",
        "line_count",
        "name: line_count\n",
        """
from pathlib import Path

def run(args, context=None):
    marker = Path(__file__).with_name("marker.txt")
    marker.write_text(context["tool_name"], encoding="utf-8")
    return {"ok": True, "marker": str(marker)}
""",
    )
    set_active_extension("repo-inspector")

    registry = build_user_tool_registry()
    result = registry["line_count"]["execute"](tmp_path)

    assert result["ok"] is True
    assert result["marker"] == str(tool_dir / "marker.txt")
    assert (tool_dir / "marker.txt").read_text(encoding="utf-8") == "line_count"


def test_empty_tools_dir_returns_empty_dict(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    (home / "tools").mkdir(parents=True)

    assert discover_user_tools() == {}


def test_user_tool_registry_exposes_schema_from_metadata(
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
args:
  query:
    type: string
    description: Search query
    required: true
""",
        "def run(args, context=None):\n    return None\n",
    )

    definition = build_user_tool_registry()["local_search"]["definition"]()
    parameters = definition["function"]["parameters"]

    assert definition["function"]["name"] == "local_search"
    assert definition["function"]["description"] == "Search local notes."
    assert parameters["properties"]["query"] == {
        "type": "string",
        "description": "Search query",
    }
    assert parameters["required"] == ["query"]


def test_selected_user_tool_executes_and_returns_normalized_dict(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(
        home,
        "echo_args",
        "name: echo_args\n",
        """
def run(args, context=None):
    return {
        "ok": True,
        "message": args["message"],
        "context_repo": context["repo_root"],
        "context_tool": context["tool_name"],
        "context_session": context["session_id"],
    }
""",
    )
    registry = build_user_tool_registry(session_id="session-1")
    executor = ToolExecutor(
        repo_root=repo,
        session=Session(repo_root=repo),
        tools={"echo_args": registry["echo_args"]},
    )

    result = executor.execute(
        {
            "tool": "echo_args",
            "args": {"message": "hello"},
        }
    )

    assert result == {
        "ok": True,
        "tool": "echo_args",
        "message": "hello",
        "context_repo": str(repo),
        "context_tool": "echo_args",
        "context_session": "session-1",
    }


def test_selected_user_tool_string_result_is_wrapped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(
        home,
        "say_hi",
        "name: say_hi\n",
        "def run(args, context=None):\n    return 'hi'\n",
    )

    result = build_user_tool_registry()["say_hi"]["execute"](tmp_path)

    assert result == {
        "ok": True,
        "tool": "say_hi",
        "message": "hi",
        "data": {},
    }


def test_selected_user_tool_none_result_is_wrapped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(
        home,
        "noop",
        "name: noop\n",
        "def run(args, context=None):\n    return None\n",
    )

    result = build_user_tool_registry()["noop"]["execute"](tmp_path)

    assert result == {
        "ok": True,
        "tool": "noop",
        "message": "",
        "data": {},
    }


def test_selected_user_tool_exception_becomes_error_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_tool(
        home,
        "broken",
        "name: broken\n",
        "def run(args, context=None):\n    raise RuntimeError('boom')\n",
    )

    result = build_user_tool_registry()["broken"]["execute"](tmp_path)

    assert result == {
        "ok": False,
        "tool": "broken",
        "error": "boom",
    }


def test_user_tool_entrypoint_cannot_escape_tool_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    (home / "tools" / "escape").mkdir(parents=True)
    (home / "tools" / "outside.py").write_text(
        "def run(args, context=None):\n    return 'escaped'\n",
        encoding="utf-8",
    )

    result = execute_user_tool(
        UserTool(name="escape", entrypoint="../outside.py"),
        tmp_path,
        {},
    )

    assert result["ok"] is False
    assert result["tool"] == "escape"
    assert "entrypoint must stay inside the tool directory" in result["error"]

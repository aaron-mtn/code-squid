import json
from pathlib import Path

import pytest

from squid_core.agent import Agent
from code_squid.app_paths import CODE_SQUID_HOME_ENV
from code_squid.agent_setup import build_coding_task_run, resolve_skill_tools
from squid_core.skills import Skill
from squid_core.tools.builtins import TOOLS


def read_entries(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_user_tool(home: Path, name: str, metadata: str | None = None) -> None:
    tool_dir = home / "tools" / name
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.yaml").write_text(metadata or f"name: {name}\n", encoding="utf-8")
    (tool_dir / "tool.py").write_text(
        "def run(args, context=None):\n    return {'ok': True}\n",
        encoding="utf-8",
    )


def write_user_skill(home: Path, name: str) -> None:
    skill_dir = home / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Review architecture.
allowed-tools: read_file run_command
---

Review architecture without modifying files.

## FINAL_SUMMARY_REQUIREMENTS replace

Write a focused architecture review.

## TOOL_USAGE_GUIDANCE append

Use inspection tools only.
""",
        encoding="utf-8",
    )


def test_selecting_skill_filters_tool_definitions(monkeypatch, tmp_path: Path) -> None:
    skill = Skill(
        name="read-only",
        description="Read only.",
        instructions="Do not write.",
        allowed_tools=("read_file", "run_command"),
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"read-only": skill})

    selected_skill, tools = resolve_skill_tools("read-only")
    agent = Agent("review this", skill=selected_skill, tools=tools)
    names = [definition["function"]["name"] for definition in agent.tool_definitions()]

    assert selected_skill is skill
    assert names == ["read_file", "run_command"]


def test_selecting_user_skill_uses_same_resolution_path(monkeypatch, tmp_path: Path) -> None:
    skill = Skill(
        name="user-review",
        description="User review.",
        instructions="Review my way.",
        allowed_tools=("read_file",),
        path=tmp_path / "skills" / "user" / "user-review" / "SKILL.md",
        source="user",
        editable=True,
    )

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"user-review": skill})

    selected_skill, tools = resolve_skill_tools("user-review")

    assert selected_skill is skill
    assert selected_skill.source == "user"
    assert selected_skill.editable is True
    assert list(tools) == ["read_file"]


def test_skill_with_explicit_empty_tools_resolves_to_no_tools(monkeypatch, tmp_path: Path) -> None:
    skill = Skill(
        name="chat-only",
        description="Chat only.",
        instructions="Do not use tools.",
        allowed_tools=(),
        allowed_tools_explicit=True,
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"chat-only": skill})

    selected_skill, tools = resolve_skill_tools("chat-only")
    agent = Agent("plan this", skill=selected_skill, tools=tools)

    assert selected_skill is skill
    assert tools == {}
    assert agent.tool_definitions() == []


def test_skill_with_omitted_tools_keeps_full_tool_default(monkeypatch, tmp_path: Path) -> None:
    skill = Skill(
        name="legacy",
        description="Legacy default.",
        instructions="Use default tools.",
        allowed_tools=(),
        allowed_tools_explicit=False,
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"legacy": skill})

    selected_skill, tools = resolve_skill_tools("legacy")

    assert selected_skill is skill
    assert list(tools) == ["read_file", "write_file", "apply_patch", "run_command"]


def test_no_selected_skill_preserves_full_tool_behavior(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    write_user_tool(home, "custom_tool")

    skill, tools = resolve_skill_tools(None)
    agent = Agent("do this", skill=skill, tools=tools)
    names = [definition["function"]["name"] for definition in agent.tool_definitions()]

    assert skill is None
    assert names == ["read_file", "write_file", "apply_patch", "run_command"]


def test_skill_listing_user_tool_activates_it(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    write_user_tool(
        home,
        "custom_tool",
        "name: custom_tool\ndescription: Custom user tool.\n",
    )
    skill = Skill(
        name="custom",
        description="Custom.",
        instructions="Use custom tools.",
        allowed_tools=("custom_tool",),
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"custom": skill})

    selected_skill, tools = resolve_skill_tools("custom")
    agent = Agent("use it", skill=selected_skill, tools=tools)
    names = [definition["function"]["name"] for definition in agent.tool_definitions()]

    assert selected_skill is skill
    assert list(tools) == ["custom_tool"]
    assert names == ["custom_tool"]
    assert tools["custom_tool"]["definition"]()["function"]["description"] == "Custom user tool."


def test_builtin_tool_name_wins_over_user_tool_collision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    write_user_tool(
        home,
        "read_file",
        "name: read_file\ndescription: Colliding user tool.\n",
    )
    skill = Skill(
        name="read",
        description="Read.",
        instructions="Use read.",
        allowed_tools=("read_file",),
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"read": skill})

    _selected_skill, tools = resolve_skill_tools("read")

    assert tools["read_file"] is TOOLS["read_file"]


def test_unknown_tool_in_allowed_tools_fails_clearly(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))
    skill = Skill(
        name="bad",
        description="Bad tool list.",
        instructions="Use a missing tool.",
        allowed_tools=("read_file", "missing_tool"),
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"bad": skill})

    try:
        resolve_skill_tools("bad")
    except ValueError as error:
        assert str(error) == "Skill bad lists unknown tool(s): missing_tool"
    else:
        raise AssertionError("Expected unknown skill tool to fail")


def test_build_coding_task_run_passes_filtered_tools_to_executor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    skill = Skill(
        name="review",
        description="Review only.",
        instructions="Only inspect.",
        allowed_tools=("read_file",),
        path=tmp_path / "SKILL.md",
    )
    captured = {}

    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            captured["agent"] = kwargs["agent"]
            captured["tool_executor"] = kwargs["tool_executor"]
            self.display = kwargs["display"]

    monkeypatch.setattr("code_squid.agent_setup.discover_skills", lambda **_kwargs: {"review": skill})
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("squid_core.spawner.AgentLoop", FakeAgentLoop)

    build_coding_task_run(
        workspace_root=tmp_path,
        task="review this",
        display=type("FakeDisplay", (), {"debug": False})(),
        skill_name="review",
    )

    assert captured["agent"].skill is skill
    assert list(captured["agent"].tools) == ["read_file"]
    assert list(captured["tool_executor"].tools) == ["read_file"]


def test_build_coding_task_run_uses_explicit_resolved_components(
    monkeypatch,
    tmp_path: Path,
) -> None:
    skill = Skill(
        name="packaged-review",
        description="Packaged review.",
        instructions="Inspect the package.",
        allowed_tools=("packaged_tool",),
        path=tmp_path / "SKILL.md",
    )
    tool_entry = {"marker": object()}
    tools = {"packaged_tool": tool_entry}
    captured = {}

    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.display = kwargs["display"]

    def fail_resolution(*args, **kwargs):
        raise AssertionError("explicit components must bypass skill discovery")

    monkeypatch.setattr("code_squid.agent_setup.resolve_skill_tools", fail_resolution)
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("squid_core.spawner.AgentLoop", FakeAgentLoop)

    run = build_coding_task_run(
        workspace_root=tmp_path,
        task="review this",
        display=type("FakeDisplay", (), {"debug": False})(),
        resolved_skill=skill,
        resolved_tools=tools,
    )

    assert captured["agent"].skill is skill
    assert captured["agent"].tools is tools
    assert captured["tool_executor"].tools is tools
    assert tools == {"packaged_tool": tool_entry}
    entries = read_entries(run.session_store.jsonl_path)
    assert entries[0]["skill_name"] == "packaged-review"
    assert entries[0]["allowed_tools"] == ["packaged_tool"]


@pytest.mark.parametrize("supplied", ["skill", "tools"])
def test_build_coding_task_run_rejects_partial_explicit_components(
    tmp_path: Path,
    supplied: str,
) -> None:
    skill = Skill(
        name="only-skill",
        description="Only skill.",
        instructions="",
        allowed_tools=(),
        path=tmp_path / "SKILL.md",
    )
    kwargs = {"resolved_skill": skill} if supplied == "skill" else {"resolved_tools": {}}

    with pytest.raises(
        ValueError,
        match="resolved_skill and resolved_tools must be supplied together",
    ):
        build_coding_task_run(workspace_root=tmp_path, task="review this", **kwargs)


def test_build_coding_task_run_records_architecture_review_run_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app_home = tmp_path / "home"
    write_user_skill(app_home, "user-review")

    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.display = kwargs["display"]

    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("squid_core.spawner.AgentLoop", FakeAgentLoop)

    run = build_coding_task_run(
        workspace_root=tmp_path,
        task="review this",
        display=type("FakeDisplay", (), {"debug": False})(),
        skill_name="user-review",
        app_home=app_home,
        mod_id="architecture-mod",
    )

    entries = read_entries(run.session_store.jsonl_path)
    assert entries[0]["type"] == "run_context"
    assert entries[0]["skill_name"] == "user-review"
    assert entries[0]["mod_id"] == "architecture-mod"
    assert entries[0]["allowed_tools"] == ["read_file", "run_command"]
    assert entries[0]["prompt_overrides"] == [
        "FINAL_SUMMARY_REQUIREMENTS",
        "TOOL_USAGE_GUIDANCE",
    ]


def test_build_coding_task_run_records_default_run_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.display = kwargs["display"]

    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("squid_core.spawner.AgentLoop", FakeAgentLoop)

    run = build_coding_task_run(
        workspace_root=tmp_path,
        task="fix this",
        display=type("FakeDisplay", (), {"debug": False})(),
    )

    entries = read_entries(run.session_store.jsonl_path)
    assert entries[0]["type"] == "run_context"
    assert entries[0]["skill_name"] is None
    assert entries[0]["allowed_tools"] == [
        "apply_patch",
        "read_file",
        "run_command",
        "write_file",
    ]
    assert entries[0]["prompt_overrides"] == []

import json
from pathlib import Path

from agent.coding import CodingAgent
from core.runner import build_coding_task_run, resolve_skill_tools
from core.skills import Skill


def read_entries(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_selecting_skill_filters_tool_definitions(monkeypatch, tmp_path: Path) -> None:
    skill = Skill(
        name="read-only",
        description="Read only.",
        instructions="Do not write.",
        allowed_tools=("read_file", "run_command"),
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("core.runner.discover_skills", lambda: {"read-only": skill})

    selected_skill, tools = resolve_skill_tools("read-only")
    agent = CodingAgent("review this", skill=selected_skill, tools=tools)
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

    monkeypatch.setattr("core.runner.discover_skills", lambda: {"user-review": skill})

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

    monkeypatch.setattr("core.runner.discover_skills", lambda: {"chat-only": skill})

    selected_skill, tools = resolve_skill_tools("chat-only")
    agent = CodingAgent("plan this", skill=selected_skill, tools=tools)

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

    monkeypatch.setattr("core.runner.discover_skills", lambda: {"legacy": skill})

    selected_skill, tools = resolve_skill_tools("legacy")

    assert selected_skill is skill
    assert list(tools) == ["read_file", "write_file", "apply_patch", "run_command"]


def test_no_selected_skill_preserves_full_tool_behavior() -> None:
    skill, tools = resolve_skill_tools(None)
    agent = CodingAgent("do this", skill=skill, tools=tools)
    names = [definition["function"]["name"] for definition in agent.tool_definitions()]

    assert skill is None
    assert names == ["read_file", "write_file", "apply_patch", "run_command"]


def test_unknown_tool_in_allowed_tools_fails_clearly(monkeypatch, tmp_path: Path) -> None:
    skill = Skill(
        name="bad",
        description="Bad tool list.",
        instructions="Use a missing tool.",
        allowed_tools=("read_file", "missing_tool"),
        path=tmp_path / "SKILL.md",
    )

    monkeypatch.setattr("core.runner.discover_skills", lambda: {"bad": skill})

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

    monkeypatch.setattr("core.runner.discover_skills", lambda: {"review": skill})
    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("core.runner.AgentLoop", FakeAgentLoop)

    build_coding_task_run(
        repo_root=tmp_path,
        task="review this",
        display=type("FakeDisplay", (), {"debug": False})(),
        skill_name="review",
    )

    assert captured["agent"].skill is skill
    assert list(captured["agent"].tools) == ["read_file"]
    assert list(captured["tool_executor"].tools) == ["read_file"]


def test_build_coding_task_run_records_architecture_review_run_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.display = kwargs["display"]

    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("core.runner.AgentLoop", FakeAgentLoop)

    run = build_coding_task_run(
        repo_root=tmp_path,
        task="review this",
        display=type("FakeDisplay", (), {"debug": False})(),
        skill_name="architecture-review",
    )

    entries = read_entries(run.session_store.jsonl_path)
    assert entries[0]["type"] == "run_context"
    assert entries[0]["skill_name"] == "architecture-review"
    assert entries[0]["allowed_tools"] == ["read_file", "run_command"]
    assert entries[0]["prompt_overrides"] == [
        "FINAL_SUMMARY_REQUIREMENTS",
        "TASK_PROMPT",
        "TOOL_USAGE_GUIDANCE",
    ]


def test_build_coding_task_run_records_default_run_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.display = kwargs["display"]

    monkeypatch.setattr("core.runner.build_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr("core.runner.AgentLoop", FakeAgentLoop)

    run = build_coding_task_run(
        repo_root=tmp_path,
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

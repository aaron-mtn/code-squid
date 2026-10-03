"""Packaged Mod discovery, Skill selection, and runtime resource boundaries."""

from pathlib import Path
import json

import pytest

from code_squid.settings import (
    DEFAULT_BUILT_IN_HOOK_SETTINGS,
    CompactionSettings,
    DisplaySettings,
    ModelSettings,
    RuntimeSettings,
    Settings,
)
from squid_core.hooks import list_user_hooks, load_user_hooks
from squid_core.mods import ModResolutionError, discover_mods, load_mod, resolve_mod, validate_mod
from code_squid.agent_setup import build_coding_task_run
from squid_core.settings import RuntimeSettings as CoreRuntimeSettings
from squid_core.skills import discover_skills
from squid_core.tools.user_tools import discover_user_tools
from squid_core import spawner as generic_spawner
from squid_core.tools.builtins import TOOLS
from squid_core.session import Session
from squid_core.storage import SessionStore


def _write_skill(path: Path, name: str, tools: tuple[str, ...], description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    allowed = "allowed-tools: []" if not tools else "allowed-tools:\n" + "".join(
        f"  - {tool}\n" for tool in tools
    ).rstrip()
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n{allowed}\n---\n\nInstructions for {name}.\n",
        encoding="utf-8",
    )


def _write_tool(root: Path, name: str, marker: Path | None = None, result: str = "tool") -> None:
    tool_dir = root / name
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "tool.yaml").write_text(
        f"name: {name}\ndescription: {result}\n",
        encoding="utf-8",
    )
    import_marker = "" if marker is None else f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
    (tool_dir / "tool.py").write_text(
        import_marker + f"def run(args, context=None):\n    return {result!r}\n",
        encoding="utf-8",
    )


def _write_hook(root: Path, name: str, marker: Path | None = None, source: str = "hook") -> None:
    hook_dir = root / name
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "hook.yaml").write_text(
        f"name: {name}\nenabled: false\n",
        encoding="utf-8",
    )
    import_marker = "" if marker is None else f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n"
    (hook_dir / "hook.py").write_text(
        import_marker
        + f"class SelectedHook:\n    source = {source!r}\n\ndef create_hook(config=None):\n    return SelectedHook()\n",
        encoding="utf-8",
    )


def _write_mod(
    home: Path,
    name: str = "review-pack",
    *,
    skill_name: str | None = None,
    tools: tuple[str, ...] = (),
    hooks: tuple[str, ...] = (),
    local_skill: bool = True,
    skill_description: str = "Mod-local skill",
) -> Path:
    skill_name = name if skill_name is None else skill_name
    mod_dir = home / "mods" / name
    mod_dir.mkdir(parents=True, exist_ok=True)
    hook_lines = "hooks: []" if not hooks else "hooks:\n" + "".join(f"  - {item}\n" for item in hooks).rstrip()
    (mod_dir / "mod.yaml").write_text(
        f"---\nname: {name}\ndescription: Test Mod\ndefault_skill: {skill_name}\naccent: purple\n{hook_lines}\n---\n",
        encoding="utf-8",
    )
    if local_skill:
        _write_skill(mod_dir / "skills" / skill_name / "SKILL.md", skill_name, tools, skill_description)
    return mod_dir


def _settings(
    built_in_hook_settings: dict[str, bool] | None = None,
) -> Settings:
    return Settings(
        model=ModelSettings(),
        display=DisplaySettings(),
        runtime=RuntimeSettings(
            built_in_hook_settings=(
                dict(DEFAULT_BUILT_IN_HOOK_SETTINGS)
                if built_in_hook_settings is None
                else built_in_hook_settings
            )
        ),
        compaction=CompactionSettings(enabled=False),
    )


class _Display:
    debug = False

    def thinking(self) -> None:
        pass

    def debug_reply(self, reply: dict) -> None:
        pass

    def final_message(self, content: str) -> None:
        pass


class _CompletingAdapter:
    def __init__(self) -> None:
        self.requests = []

    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        self.requests.append((list(messages), list(tool_definitions)))
        return {
            "message": {"role": "assistant", "content": "complete"},
            "actions": [],
            "raw_reply": {},
        }

    def supports_streaming(self) -> bool:
        return False


def test_canonical_discovery_uses_supplied_home_and_ignores_legacy_layout(tmp_path: Path) -> None:
    selected_home = tmp_path / "selected"
    other_home = tmp_path / "other"
    _write_mod(selected_home, "canonical")
    _write_mod(other_home, "elsewhere")
    legacy = selected_home / "extensions" / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "extension.yaml").write_text("name: legacy\n", encoding="utf-8")

    assert set(discover_mods(selected_home)) == {"canonical"}
    assert discover_mods(other_home)["elsewhere"].path == other_home / "mods" / "elsewhere"
    with pytest.raises(ModResolutionError, match="Unknown Mod: legacy"):
        load_mod("legacy", selected_home)


def test_standalone_resources_remain_discoverable_with_explicit_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_skill(home / "skills" / "loose-skill" / "SKILL.md", "loose-skill", (), "Loose")
    _write_tool(home / "tools", "loose-tool")
    _write_hook(home / "hooks", "loose-hook")

    assert "loose-skill" in discover_skills(app_home=home)
    assert "loose-tool" in discover_user_tools(app_home=home)
    assert [hook.name for hook in list_user_hooks(app_home=home)] == ["loose-hook"]
    assert load_user_hooks(app_home=home) == []


def test_discovery_and_validation_do_not_import_tool_or_hook_source(tmp_path: Path) -> None:
    home = tmp_path / "home"
    tool_marker = tmp_path / "tool-imported"
    hook_marker = tmp_path / "hook-imported"
    mod_dir = _write_mod(home, tools=("custom-tool",), hooks=("custom-hook",))
    _write_tool(mod_dir / "tools", "custom-tool", tool_marker)
    _write_hook(mod_dir / "hooks", "custom-hook", hook_marker)

    mod = discover_mods(home)["review-pack"]

    assert mod.valid is True
    assert validate_mod(mod, home) == ()
    assert not tool_marker.exists()
    assert not hook_marker.exists()


def test_runtime_resolves_local_skill_lazy_tool_and_loaded_hook(tmp_path: Path) -> None:
    home = tmp_path / "home"
    tool_marker = tmp_path / "tool-imported"
    hook_marker = tmp_path / "hook-imported"
    mod_dir = _write_mod(home, tools=("custom-tool",), hooks=("custom-hook",))
    _write_tool(mod_dir / "tools", "custom-tool", tool_marker, "mod-tool")
    _write_hook(mod_dir / "hooks", "custom-hook", hook_marker, "mod-hook")

    resolved = resolve_mod("review-pack", home, repo_root=tmp_path)

    assert resolved.metadata.name == "review-pack"
    assert resolved.skill.source == "mod"
    assert resolved.skill.name == "review-pack"
    assert list(resolved.tools) == ["custom-tool"]
    assert resolved.hooks[0].source == "mod-hook"
    assert hook_marker.exists()
    assert not tool_marker.exists()
    assert resolved.tools["custom-tool"]["execute"](tmp_path)["message"] == "mod-tool"
    assert tool_marker.exists()


def test_mod_local_resources_win_over_same_named_loose_resources(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_skill(home / "skills" / "review-pack" / "SKILL.md", "review-pack", ("custom-tool",), "Loose skill")
    _write_tool(home / "tools", "custom-tool", result="loose-tool")
    _write_hook(home / "hooks", "custom-hook", source="loose-hook")
    mod_dir = _write_mod(home, tools=("custom-tool",), hooks=("custom-hook",), skill_description="Local skill")
    _write_tool(mod_dir / "tools", "custom-tool", result="mod-tool")
    _write_hook(mod_dir / "hooks", "custom-hook", source="mod-hook")

    resolved = resolve_mod("review-pack", home, repo_root=tmp_path)

    assert resolved.skill.description == "Local skill"
    assert resolved.tools["custom-tool"]["execute"](tmp_path)["message"] == "mod-tool"
    assert resolved.hooks[0].source == "mod-hook"


def test_mod_can_reference_shared_tools_and_hooks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_skill(home / "skills" / "shared-skill" / "SKILL.md", "shared-skill", ("shared-tool",), "Shared skill")
    _write_tool(home / "tools", "shared-tool", result="shared-tool")
    _write_hook(home / "hooks", "shared-hook", source="shared-hook")
    _write_mod(
        home,
        skill_name="shared-skill",
        tools=("shared-tool",),
        hooks=("shared-hook",),
    )

    resolved = resolve_mod("review-pack", home, repo_root=tmp_path)

    assert resolved.skill.source == "mod"
    assert resolved.tools["shared-tool"]["execute"](tmp_path)["message"] == "shared-tool"
    assert resolved.hooks[0].source == "shared-hook"


def test_protected_builtin_tool_cannot_be_replaced_by_mod(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, tools=("read_file",))
    _write_tool(mod_dir / "tools", "read_file", result="replacement")

    mod = load_mod("review-pack", home)
    assert any("cannot replace protected built-in" in error for error in mod.errors)
    with pytest.raises(ModResolutionError, match="cannot replace protected built-in"):
        resolve_mod("review-pack", home)


def test_loose_builtin_collision_still_uses_protected_builtin(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_tool(home / "tools", "read_file", result="replacement")
    _write_mod(home, tools=("read_file",))

    resolved = resolve_mod("review-pack", home)

    assert resolved.tools["read_file"] is TOOLS["read_file"]


def test_code_squid_builder_resolves_selected_mod_into_agent_tools_hooks_and_context(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, tools=("read_file",), hooks=("selected-hook",))
    _write_hook(mod_dir / "hooks", "selected-hook", source="selected")

    run = build_coding_task_run(
        tmp_path,
        "review",
        settings=_settings(
            dict.fromkeys(DEFAULT_BUILT_IN_HOOK_SETTINGS, False)
        ),
        display=_Display(),
        mod_name="review-pack",
        app_home=home,
        model_adapter=object(),
    )

    assert run.loop.agent.skill_name == "review-pack"
    assert list(run.loop.tool_executor.tools) == ["read_file"]
    assert [hook.source for hook in run.loop.hook_runner.hooks] == ["selected"]
    context = run.session_store.jsonl_path.read_text(encoding="utf-8")
    assert '"mod_id": "review-pack"' in context
    assert '"skill_name": "review-pack"' in context


def test_one_session_switches_default_mods_and_back_as_coherent_runs(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    for name, tool, hook in (
        ("mod-a", "read_file", "hook-a"),
        ("mod-b", "run_command", "hook-b"),
    ):
        mod_dir = _write_mod(home, name, tools=(tool,), hooks=(hook,))
        _write_hook(mod_dir / "hooks", hook, source=hook)

    first_adapter = _CompletingAdapter()
    current = build_coding_task_run(
        tmp_path,
        "default task",
        settings=_settings(),
        display=_Display(),
        app_home=home,
        model_adapter=first_adapter,
    )
    current.loop.run()
    original_non_system = list(current.session.messages[1:])

    observed = []
    for mod_name in ("mod-a", "mod-b", None):
        adapter = _CompletingAdapter()
        current = build_coding_task_run(
            tmp_path,
            f"task for {mod_name or 'default'}",
            settings=_settings(),
            display=_Display(),
            app_home=home,
            mod_name=mod_name,
            session=current.session,
            session_store=current.session_store,
            model_adapter=adapter,
        )
        follow_up = current.loop.agent.follow_up_message(current.loop.agent.task)
        current.session.add_message(follow_up)
        current.session_store.append_message(follow_up)
        current.loop.run()
        request_messages, tool_definitions = adapter.requests[0]
        observed.append(
            (
                current.loop.agent.skill_name,
                tuple(
                    definition.get("name", definition.get("function", {}).get("name"))
                    for definition in tool_definitions
                ),
                tuple(hook.source for hook in current.loop.hook_runner.hooks),
                request_messages,
            )
        )

    assert observed[0][:3] == (
        "mod-a",
        ("read_file",),
        (
            "hook-a",
            "Code Squid",
            "Code Squid",
        ),
    )
    assert observed[1][:3] == (
        "mod-b",
        ("run_command",),
        (
            "hook-b",
            "Code Squid",
            "Code Squid",
        ),
    )
    assert observed[2][0] is None
    assert set(observed[2][1]) == set(TOOLS)
    assert observed[2][2] == (
        "Code Squid",
        "Code Squid",
    )
    for _, _, _, messages in observed:
        assert sum(message["role"] == "system" for message in messages) == 1
        assert messages[1 : 1 + len(original_non_system)] == original_non_system

    contexts = [
        line
        for line in current.session_store.jsonl_path.read_text(encoding="utf-8").splitlines()
        if '"type": "run_context"' in line
    ]
    assert len(contexts) == 4
    assert '"mod_id": "mod-a"' in contexts[1]
    assert '"mod_id": "mod-b"' in contexts[2]
    assert '"mod_id"' not in contexts[3]


def test_generic_spawner_remains_mod_agnostic() -> None:
    assert "mod_name" not in generic_spawner.build_agent_run.__annotations__
    assert "mod_name" not in generic_spawner.build_agent_run.__code__.co_varnames


@pytest.mark.parametrize("reopen", [False, True])
def test_session_switches_packaged_skills_and_mods(tmp_path: Path, reopen: bool) -> None:
    """Exercise both in-memory hosts and the CLI's persisted follow-up path."""
    home = tmp_path / "home"
    selections = (
        ("mod-a", "skill-one", "read_file", "hook-a"),
        ("mod-a", "skill-two", "run_command", "hook-a"),
        ("mod-b", "skill-one", "apply_patch", "hook-b"),
    )
    for mod_name, skill_name, tool, hook in selections:
        mod_dir = home / "mods" / mod_name
        if not mod_dir.exists():
            _write_mod(home, mod_name, skill_name="skill-one", hooks=(hook,))
            _write_hook(mod_dir / "hooks", hook, source=hook)
        path = mod_dir / "skills" / skill_name / "SKILL.md"
        _write_skill(path, skill_name, (tool,), "Selected profile")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"\n## SYSTEM_PROMPT_INTRO replace\n\nProfile {mod_name}/{skill_name}.\n")

    current = None
    for index, (mod_name, skill_name, tool, hook) in enumerate(selections):
        session = current.session if current else None
        store = current.session_store if current else None
        if current and reopen:
            store = SessionStore.open(store.session_dir)
            session = Session(repo_root=tmp_path)
            session.add_messages(*store.load_messages())
        prior = [message for message in session.messages if message["role"] != "system"] if session else []
        adapter = _CompletingAdapter()
        current = build_coding_task_run(
            tmp_path, f"task {index}", settings=_settings(), display=_Display(),
            app_home=home, mod_name=mod_name, skill_name=skill_name,
            session=session, session_store=store, model_adapter=adapter,
        )
        if index:
            follow_up = current.loop.agent.follow_up_message(current.loop.agent.task)
            current.session.add_message(follow_up)
            current.session_store.append_message(follow_up)
        current.loop.run()
        messages, definitions = adapter.requests[0]
        assert sum(message["role"] == "system" for message in messages) == 1
        assert messages[1:1 + len(prior)] == prior
        assert f"Profile {mod_name}/{skill_name}." in messages[0]["content"]
        for other_mod, other_skill, _, _ in selections:
            if (other_mod, other_skill) != (mod_name, skill_name):
                assert f"Profile {other_mod}/{other_skill}." not in messages[0]["content"]
        assert current.loop.agent.skill_name == skill_name
        assert list(current.loop.tool_executor.tools) == [tool]
        assert [item["function"]["name"] for item in definitions] == [tool]
        assert [item.source for item in current.loop.hook_runner.hooks] == [
            hook, "Code Squid", "Code Squid",
        ]
        persisted = current.session_store.load_messages()
        assert sum(message["role"] == "system" for message in persisted) == 1
        assert persisted == current.session.messages

    contexts = [json.loads(line) for line in current.session_store.jsonl_path.read_text().splitlines()
                if json.loads(line)["type"] == "run_context"]
    assert [(entry["mod_id"], entry["skill_name"]) for entry in contexts] == [
        (mod, skill) for mod, skill, _, _ in selections
    ]
    assert [entry["allowed_tools"] for entry in contexts] == [[tool] for _, _, tool, _ in selections]
    assert all(entry["prompt_overrides"] == ["SYSTEM_PROMPT_INTRO"] for entry in contexts)


def test_application_skill_namespaces_do_not_fall_back(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_mod(home, "mod-a", skill_name="shared", tools=("read_file",))
    _write_skill(home / "skills" / "shared" / "SKILL.md", "shared", ("run_command",), "Standalone")
    _write_skill(home / "skills" / "loose" / "SKILL.md", "loose", (), "Loose")
    kwargs = dict(settings=_settings(), app_home=home, model_adapter=object())
    default = build_coding_task_run(tmp_path, "default", mod_name="mod-a", **kwargs)
    packaged = build_coding_task_run(tmp_path, "packaged", mod_name="mod-a", skill_name="shared", **kwargs)
    standalone = build_coding_task_run(tmp_path, "standalone", skill_name="shared", **kwargs)
    assert list(default.loop.tool_executor.tools) == ["read_file"]
    assert list(packaged.loop.tool_executor.tools) == ["read_file"]
    assert list(standalone.loop.tool_executor.tools) == ["run_command"]
    with pytest.raises(ModResolutionError, match="loose"):
        build_coding_task_run(tmp_path, "missing packaged", mod_name="mod-a", skill_name="loose", **kwargs)
    with pytest.raises(ValueError, match="Unknown skill: mod-a"):
        build_coding_task_run(tmp_path, "missing standalone", skill_name="mod-a", **kwargs)


def test_cli_selects_skills_only_within_active_mod(monkeypatch, tmp_path: Path, capsys) -> None:
    from code_squid.console.cli.mod_commands import _handle_mod_input
    from code_squid.console.cli.skill_commands import _handle_skill_input, _format_skill_status

    home = tmp_path / "home"
    monkeypatch.setenv("CODE_SQUID_HOME", str(home))
    mod_a = _write_mod(home, "mod-a", skill_name="skill-one", tools=("read_file",))
    _write_skill(mod_a / "skills" / "skill-two" / "SKILL.md", "skill-two", ("run_command",), "Second")
    _write_mod(home, "mod-b", skill_name="skill-one", tools=("apply_patch",))
    _write_skill(home / "skills" / "loose" / "SKILL.md", "loose", (), "Standalone")

    mod, skill = _handle_mod_input("/mod mod-a", None, "loose")
    assert (mod, skill) == ("mod-a", "skill-one")
    skill, mod = _handle_skill_input("/skill skill-two", skill, mod)
    assert (mod, skill) == ("mod-a", "skill-two")
    status = _format_skill_status(skill, mod)
    assert "Current skill: skill-two" in status
    assert "Tools: run_command" in status
    assert "- skill-one:" in status and "- skill-two:" in status
    assert "loose" not in status
    assert _handle_skill_input("/skill loose", skill, mod) == (skill, mod)
    assert _handle_skill_input("/skill none", skill, mod) == ("skill-one", "mod-a")
    mod, skill = _handle_mod_input("/mod mod-b", mod, skill)
    assert (mod, skill) == ("mod-b", "skill-one")
    assert _handle_mod_input("/mod none", mod, skill) == (None, None)
    assert _handle_skill_input("/skill loose", None, None) == ("loose", None)
    assert _handle_skill_input("/skill skill-one", "loose", None) == ("loose", None)
    assert _handle_mod_input("/mod none", None, "loose") == (None, "loose")


def test_two_packaged_skills_resolve_one_profile_and_share_mod_hooks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, skill_name="review", tools=("read_file",), hooks=("audit",))
    _write_skill(mod_dir / "skills" / "edit" / "SKILL.md", "edit", ("run_command", "custom-tool"), "Edit")
    _write_tool(mod_dir / "tools", "custom-tool", result="local")
    _write_hook(mod_dir / "hooks", "audit", source="mod-wide")

    mod = discover_mods(home)["review-pack"]
    assert mod.valid
    assert set(mod.skills) == {"review", "edit"}
    assert validate_mod(mod, home) == ()
    assert not hasattr(mod, "tools")
    default = resolve_mod("review-pack", home)
    selected = resolve_mod("review-pack", home, selected_skill="edit")
    assert default.skill.name == "review"
    assert selected.skill.name == "edit"
    assert tuple(default.tools) == ("read_file",)
    assert tuple(selected.tools) == ("run_command", "custom-tool")
    assert [hook.source for hook in default.hooks] == ["mod-wide"]
    assert [hook.source for hook in selected.hooks] == ["mod-wide"]

    # Exercise the ordinary Core construction seam, so package validation's
    # broader dependencies cannot quietly reach the active ToolExecutor.
    run = generic_spawner.build_agent_run(
        tmp_path, "edit", settings=CoreRuntimeSettings(
            provider=None, approval_mode="never", max_tool_steps=None,
            stream_assistant_text=False, compaction=CompactionSettings(enabled=False),
        ),
        skill=selected.skill, tools=selected.tools, model_adapter=object(),
        sessions_dir=tmp_path / "sessions", undo_dir=tmp_path / "undo",
    )
    assert tuple(run.loop.tool_executor.tools) == ("run_command", "custom-tool")
    assert run.loop.tool_executor.execute({"tool": "read_file"})["ok"] is False


def test_empty_selected_allowed_tools_stays_empty(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, tools=("read_file",))
    _write_skill(mod_dir / "skills" / "no-tools" / "SKILL.md", "no-tools", (), "No tools")
    selected = resolve_mod("review-pack", home, selected_skill="no-tools")
    run = generic_spawner.build_agent_run(
        tmp_path, "think", settings=CoreRuntimeSettings(
            provider=None, approval_mode="never", max_tool_steps=None,
            stream_assistant_text=False, compaction=CompactionSettings(enabled=False),
        ),
        skill=selected.skill, tools=selected.tools, model_adapter=object(),
        sessions_dir=tmp_path / "sessions", undo_dir=tmp_path / "undo",
    )
    assert selected.tools == {}
    assert run.loop.tool_executor.tools == {}


def test_missing_default_cannot_fall_back_to_standalone_skill(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, skill_name="missing", local_skill=False)
    _write_skill(home / "skills" / "missing" / "SKILL.md", "missing", (), "Standalone")
    _write_skill(mod_dir / "skills" / "other" / "SKILL.md", "other", (), "Other")
    mod = load_mod("review-pack", home)
    assert not mod.valid
    assert any("unknown default Skill" in error for error in mod.errors)
    with pytest.raises(ModResolutionError, match="unknown default Skill"):
        resolve_mod("review-pack", home, selected_skill="other")


def test_mod_requires_at_least_one_direct_packaged_skill(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, local_skill=False)
    _write_skill(mod_dir / "skills" / "nested" / "review-pack" / "SKILL.md", "review-pack", (), "Nested")
    mod = load_mod("review-pack", home)
    assert not mod.valid
    assert any("at least one packaged Skill" in error for error in mod.errors)


@pytest.mark.parametrize("selected_skill", ["missing", "", "../review-pack"])
def test_missing_explicit_skill_errors_without_standalone_fallback(tmp_path: Path, selected_skill: str) -> None:
    home = tmp_path / "home"
    _write_mod(home)
    _write_skill(home / "skills" / "missing" / "SKILL.md", "missing", (), "Standalone")
    with pytest.raises(ModResolutionError, match="unknown selected Skill"):
        resolve_mod("review-pack", home, selected_skill=selected_skill)


def test_same_local_skill_and_tool_ids_are_scoped_to_each_mod(tmp_path: Path) -> None:
    home = tmp_path / "home"
    for name in ("first", "second"):
        mod_dir = _write_mod(home, name, skill_name="review", tools=("custom-tool",))
        _write_tool(mod_dir / "tools", "custom-tool", result=name)
    assert all(mod.valid for mod in discover_mods(home).values())
    for name in ("first", "second"):
        resolved = resolve_mod(name, home)
        assert resolved.skill.name == "review"
        assert resolved.tools["custom-tool"]["execute"](tmp_path)["message"] == name


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("name: other\ndescription: Bad\nallowed-tools: []", "must match directory"),
        ("name: edit\ndescription: Bad", "explicitly declare allowed-tools"),
        ("name: edit\ndescription: Bad\nallowed-tools: missing-tool", "unknown Tool"),
        ("name: edit\ndescription: Bad\nallowed-tools: read_file read_file", "duplicate allowed-tools"),
        ("name: edit\nallowed-tools: []", "missing required frontmatter field"),
    ],
)
def test_invalid_non_default_skill_invalidates_entire_mod(tmp_path: Path, content: str, error: str) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home)
    path = mod_dir / "skills" / "edit" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{content}\n---\nInstructions.\n", encoding="utf-8")
    mod = discover_mods(home)["review-pack"]
    assert not mod.valid
    assert any(error in message for message in mod.errors)
    with pytest.raises(ModResolutionError, match=error):
        resolve_mod("review-pack", home)


def test_all_non_default_skills_are_validated_after_parse_failure(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home)
    broken = mod_dir / "skills" / "broken" / "SKILL.md"
    broken.parent.mkdir(parents=True)
    broken.write_text("not frontmatter", encoding="utf-8")
    _write_skill(mod_dir / "skills" / "other" / "SKILL.md", "wrong", (), "Wrong name")
    errors = load_mod("review-pack", home).errors
    assert any("must start with YAML frontmatter" in error for error in errors)
    assert any("must match directory" in error for error in errors)


def test_legacy_mod_tools_field_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home)
    path = mod_dir / "mod.yaml"
    path.write_text(path.read_text().replace("hooks: []", "tools: []\nhooks: []"), encoding="utf-8")
    assert not load_mod("review-pack", home).valid
    with pytest.raises(ModResolutionError, match="unsupported mod.yaml field: tools"):
        resolve_mod("review-pack", home)


def test_default_skill_field_remains_required(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home)
    path = mod_dir / "mod.yaml"
    path.write_text(path.read_text().replace("default_skill: review-pack\n", ""), encoding="utf-8")
    with pytest.raises(ModResolutionError, match="missing required mod.yaml field: default_skill"):
        resolve_mod("review-pack", home)


def test_non_default_protected_builtin_collision_invalidates_package(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home)
    _write_skill(mod_dir / "skills" / "edit" / "SKILL.md", "edit", ("read_file",), "Edit")
    _write_tool(mod_dir / "tools", "read_file", result="replacement")
    with pytest.raises(ModResolutionError, match="cannot replace protected built-in"):
        resolve_mod("review-pack", home)

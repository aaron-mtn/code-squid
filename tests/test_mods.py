from pathlib import Path

import pytest

from code_squid.settings import (
    CompactionSettings,
    DisplaySettings,
    ModelSettings,
    RuntimeSettings,
    Settings,
)
from squid_core.hooks import list_user_hooks, load_user_hooks
from squid_core.mods import ModResolutionError, discover_mods, load_mod, resolve_mod, validate_mod
from code_squid.agent_setup import build_coding_task_run
from squid_core.skills import discover_skills
from squid_core.tools.user_tools import discover_user_tools
from squid_core import spawner as generic_spawner
from squid_core.tools.builtins import TOOLS


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
    tool_lines = "tools: []" if not tools else "tools:\n" + "".join(f"  - {item}\n" for item in tools).rstrip()
    hook_lines = "hooks: []" if not hooks else "hooks:\n" + "".join(f"  - {item}\n" for item in hooks).rstrip()
    (mod_dir / "mod.yaml").write_text(
        f"---\nname: {name}\ndescription: Test Mod\ndefault_skill: {skill_name}\naccent: purple\n{tool_lines}\n{hook_lines}\n---\n",
        encoding="utf-8",
    )
    if local_skill:
        _write_skill(mod_dir / "skills" / skill_name / "SKILL.md", skill_name, tools, skill_description)
    return mod_dir


def _settings() -> Settings:
    return Settings(
        model=ModelSettings(),
        display=DisplaySettings(),
        runtime=RuntimeSettings(),
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


def test_mod_can_reference_loose_shared_resources(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_skill(home / "skills" / "shared-skill" / "SKILL.md", "shared-skill", ("shared-tool",), "Shared skill")
    _write_tool(home / "tools", "shared-tool", result="shared-tool")
    _write_hook(home / "hooks", "shared-hook", source="shared-hook")
    _write_mod(
        home,
        skill_name="shared-skill",
        tools=("shared-tool",),
        hooks=("shared-hook",),
        local_skill=False,
    )

    resolved = resolve_mod("review-pack", home, repo_root=tmp_path)

    assert resolved.skill.source == "user"
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


def test_skill_permissions_must_match_mod_tool_inventory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, tools=("read_file",))
    _write_skill(mod_dir / "skills" / "review-pack" / "SKILL.md", "review-pack", (), "Restricted")

    with pytest.raises(ModResolutionError, match="allowed-tools"):
        resolve_mod("review-pack", home)


def test_code_squid_builder_resolves_selected_mod_into_agent_tools_hooks_and_context(tmp_path: Path) -> None:
    home = tmp_path / "home"
    mod_dir = _write_mod(home, tools=("read_file",), hooks=("selected-hook",))
    _write_hook(mod_dir / "hooks", "selected-hook", source="selected")

    run = build_coding_task_run(
        tmp_path,
        "review",
        settings=_settings(),
        display=_Display(),
        mod_name="review-pack",
        app_home=home,
        model_adapter=object(),
    )

    assert run.loop.agent.skill_name == "review-pack"
    assert list(run.loop.tool_executor.tools) == ["read_file"]
    assert run.loop.hook_runner.hooks[0].source == "selected"
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
        ("hook-a", "Code Squid"),
    )
    assert observed[1][:3] == (
        "mod-b",
        ("run_command",),
        ("hook-b", "Code Squid"),
    )
    assert observed[2][0] is None
    assert set(observed[2][1]) == set(TOOLS)
    assert observed[2][2] == ("Code Squid",)
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

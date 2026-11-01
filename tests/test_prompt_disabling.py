"""Check application-owned section names without changing Core execution policy.

Code Squid defines the baseline components; Core handles omission and tools.
"""

from dataclasses import replace

import pytest

from code_squid.agent.prompts import (
    BASELINE_SECTIONS, CODE_SQUID_PROMPT_DEFAULTS, SUPPORTED_DISABLE_SECTIONS,
    system_prompt,
)
from code_squid.agent_setup import discover_skills_for_app
from code_squid.mods import discover_mods, load_mod, resolve_mod
from squid_core.agent.prompts import system_prompt as core_system_prompt
from squid_core.skills import parse_skill_file


@pytest.mark.parametrize("disabled", [(name,) for name in BASELINE_SECTIONS] + [tuple(BASELINE_SECTIONS)])
def test_application_sections_are_independent_and_default_is_identical(tmp_path, disabled):
    path = tmp_path / "skills" / "sample" / "SKILL.md"
    path.parent.mkdir(parents=True)
    header = "---\nname: sample\ndescription: Sample\nallowed-tools: read_file\n---\n\n"
    path.write_text(header + "Ordinary instructions.\n", encoding="utf-8")
    plain = parse_skill_file(path)
    legacy = replace(CODE_SQUID_PROMPT_DEFAULTS, baseline_sections={})
    assert system_prompt() == core_system_prompt(legacy)
    assert system_prompt(plain) == core_system_prompt(legacy, plain)
    path.write_text(header + "Ordinary instructions.\n\n## DISABLE_PROMPT_SECTIONS\n" +
                    "".join(f"- {name}\n" for name in disabled), encoding="utf-8")
    skill = discover_skills_for_app(app_home=tmp_path)["sample"]
    for name, text in BASELINE_SECTIONS.items():
        assert (text in system_prompt(skill)) == (name not in disabled)
    assert skill.allowed_tools == plain.allowed_tools
    with pytest.raises(ValueError, match="unknown disabled prompt section"):
        parse_skill_file(path)  # Bare Core does not know application names.


def test_application_mod_adapter_accepts_host_targets_for_all_paths(tmp_path):
    root = tmp_path / "mods" / "sample"
    path = root / "skills" / "sample" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: sample\ndescription: Sample\nallowed-tools: []\n---\n\n"
                    "## DISABLE_PROMPT_SECTIONS\n- BASELINE_CODING_POLICY\n")
    (root / "mod.yaml").write_text("---\nname: sample\ndescription: Sample\ndefault_skill: sample\nhooks: []\n---\n")
    assert discover_mods(tmp_path)["sample"].valid
    assert load_mod("sample", tmp_path).valid
    resolved = resolve_mod("sample", tmp_path)
    assert resolved.tools == {}
    assert resolved.skill.disabled_prompt_sections == ("BASELINE_CODING_POLICY",)
    assert "BASELINE_CODING_POLICY" in SUPPORTED_DISABLE_SECTIONS

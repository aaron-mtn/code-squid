"""Core protocol and protected application-policy prompt regressions."""

from pathlib import Path

from code_squid.agent.coding import CodingAgent
from code_squid.agent.prompts import BASELINE_CODING_POLICY, CODE_SQUID_PROMPT_DEFAULTS
from squid_core.skills import PromptSectionOverride, Skill
from squid_core.agent import Agent


def _skill_with_replacements() -> Skill:
    return Skill(
        name="review",
        description="Review a change.",
        instructions="Focus on architecture.",
        allowed_tools=("read_file",),
        path=Path("SKILL.md"),
        prompt_sections={
            "SYSTEM_PROMPT_INTRO": PromptSectionOverride(
                section="SYSTEM_PROMPT_INTRO",
                mode="replace",
                content="Specialized intro.",
            ),
            "TOOL_USAGE_GUIDANCE": PromptSectionOverride(
                section="TOOL_USAGE_GUIDANCE",
                mode="replace",
                content="Use review tools carefully.",
            ),
            "FINAL_SUMMARY_REQUIREMENTS": PromptSectionOverride(
                section="FINAL_SUMMARY_REQUIREMENTS",
                mode="replace",
                content="Return review findings.",
            ),
        },
    )


def test_coding_agent_is_compatibility_alias_for_core_agent() -> None:
    assert CodingAgent is Agent












def test_skill_replacements_cannot_erase_code_squid_baseline_policy() -> None:
    prompt = Agent(
        "review", skill=_skill_with_replacements(), prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS
    ).initial_messages()[0]["content"]

    assert BASELINE_CODING_POLICY in prompt
    assert "smallest most high leverage part of the repository" in prompt
    assert "Prefer the smallest, cleanest implementation" in prompt
    assert "complete and adequately verified" in prompt
    assert "Specialized intro." in prompt
    assert "Return review findings." in prompt

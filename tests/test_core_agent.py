"""Core protocol and protected application-policy prompt regressions."""

from pathlib import Path

from code_squid.agent.prompts import (
    BASELINE_CODING_POLICY, CODE_SQUID_PROMPT_DEFAULTS, VISIBLE_NARRATION_GUIDANCE,
    CODING_RESPONSE_EXAMPLES, TOOL_USAGE_GUIDANCE, FINAL_SUMMARY_REQUIREMENTS,
)
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
            "AGENT_IDENTITY": PromptSectionOverride(
                section="AGENT_IDENTITY",
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



def test_moved_application_guidance_survives_all_section_replacements() -> None:
    prompt = Agent("review", skill=_skill_with_replacements(),
                   prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS).initial_messages()[0]["content"]
    assert VISIBLE_NARRATION_GUIDANCE in prompt
    assert CODING_RESPONSE_EXAMPLES in prompt
    assert "Prefer dedicated file tools for source reading and editing." in prompt
    assert "For shell discovery on Windows, use native commands" in prompt
    assert "A final response contains no tool call" in prompt
    assert "Verification honesty" in prompt


def test_default_code_squid_prompt_preserves_coding_policy() -> None:
    prompt = Agent("task", prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS).initial_messages()[0]["content"]
    for section in (BASELINE_CODING_POLICY, VISIBLE_NARRATION_GUIDANCE,
                    CODING_RESPONSE_EXAMPLES, TOOL_USAGE_GUIDANCE, FINAL_SUMMARY_REQUIREMENTS):
        assert section in prompt
    assert "Use read_file to check files instead of commands" in prompt
    assert "Use apply_patch to edit a file instead of" in prompt
    assert "Prefer dedicated file tools for source reading and editing" in prompt

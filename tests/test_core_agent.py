from pathlib import Path

from agent.coding import CodingAgent
from agent.prompts import BASELINE_CODING_POLICY, CODE_SQUID_PROMPT_DEFAULTS
from core.skills import PromptSectionOverride, Skill
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


def test_core_agent_starts_with_system_and_raw_authored_task() -> None:
    messages = Agent("  keep authored spacing  ").initial_messages()

    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1] == {"role": "user", "content": "  keep authored spacing  "}


def test_core_agent_follow_up_is_raw_authored_user_message() -> None:
    message = Agent("first").follow_up_message("  follow up exactly  ")

    assert message == {"role": "user", "content": "  follow up exactly  "}


def test_active_skill_name_is_exposed() -> None:
    agent = Agent("review", skill=_skill_with_replacements())

    assert agent.skill_name == "review"


def test_skill_replacements_cannot_erase_core_protocol_or_narration() -> None:
    prompt = Agent(
        "review", skill=_skill_with_replacements(), prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS
    ).initial_messages()[0]["content"]

    assert "exactly one real tool call" in prompt
    assert "A final response uses no tool call" in prompt
    assert "Strongly prefer a brief visible action note" in prompt
    assert "exactly one real tool call to read the implementation file" in prompt


def test_skill_replacements_cannot_erase_code_squid_baseline_policy() -> None:
    prompt = Agent(
        "review", skill=_skill_with_replacements(), prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS
    ).initial_messages()[0]["content"]

    assert BASELINE_CODING_POLICY in prompt
    assert "Inspect the relevant code, tests, and repository guidance" in prompt
    assert "Make the smallest clean change" in prompt
    assert "Run the strongest practical verification" in prompt
    assert "Specialized intro." in prompt
    assert "Return review findings." in prompt


def test_prompt_encourages_narration_but_validation_does_not_require_it() -> None:
    agent = Agent("change it", prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS)
    prompt = agent.initial_messages()[0]["content"]
    reply = {
        "message": {"content": "   "},
        "actions": [{"tool": "read_file", "args": {}, "tool_call_id": "call_1"}],
    }

    assert "Strongly prefer a brief visible action note" in prompt
    assert agent.validate_reply(reply) == {"ok": True, "reason": ""}

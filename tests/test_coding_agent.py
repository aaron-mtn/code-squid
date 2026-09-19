from pathlib import Path

from code_squid.agent.coding import CodingAgent
from squid_core.platform_context import PlatformContext
from code_squid.agent.prompts import (
    BASELINE_CODING_POLICY,
    CODE_SQUID_PROMPT_DEFAULTS,
    SYSTEM_PROMPT,
    TOOL_USAGE_GUIDANCE,
    system_prompt,
)
from squid_core.session import Session
from squid_core.skills import PromptSectionOverride, Skill


def test_validate_reply_accepts_no_tool_normal_answer_as_final() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "The answer is already available from the transcript.",
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_accepts_coding_summary_without_task_complete_as_final() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": (
                "## Files changed\n"
                "- `a.py`\n"
                "\n"
                "## What changed\n"
                "- Fixed the bug.\n"
                "\n"
                "## Verification\n"
                "- `pytest`\n"
                "\n"
                "## Remaining risks / notes\n"
                "- No known remaining risks; pytest passed."
            ),
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_rejects_empty_no_tool_reply() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "   \n",
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": False,
        "reason": "empty_final_reply",
    }


def test_validate_reply_accepts_exactly_one_tool_call_as_tool_turn() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "I need to inspect a.py before editing.",
        },
        "actions": [
            {
                "tool": "read_file",
                "args": {"path": "a.py"},
                "tool_call_id": "call_1",
            }
        ],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_accepts_one_tool_call_with_blank_content() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "   \n",
        },
        "actions": [
            {
                "tool": "read_file",
                "args": {"path": "a.py"},
                "tool_call_id": "call_1",
            }
        ],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_rejects_more_than_one_tool_call() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "I need to inspect both files.",
        },
        "actions": [
            {
                "tool": "read_file",
                "args": {"path": "a.py"},
                "tool_call_id": "call_1",
            },
            {
                "tool": "read_file",
                "args": {"path": "b.py"},
                "tool_call_id": "call_2",
            },
        ],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": False,
        "reason": "non_final_too_many_tool_calls",
    }


def test_validate_reply_rejects_malformed_tool_call() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "I need to inspect a.py.",
        },
        "actions": [],
        "format_error": "Unknown tool: missing_tool",
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": False,
        "reason": "malformed_tool_call",
    }


def test_should_stop_returns_true_for_latest_assistant_no_tool_non_empty_message() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "Done. Verification passed.",
        }
    ]

    assert agent.should_stop(session) is True


def test_should_stop_returns_false_if_latest_assistant_has_tool_calls() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "I am reading a.py next.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        }
    ]

    assert agent.should_stop(session) is False


def test_should_stop_returns_false_after_newer_user_message() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "Done. Verification passed.",
        },
        {
            "role": "user",
            "content": "Continue this saved session with this follow-up task: more",
        },
    ]

    assert agent.should_stop(session) is False


def test_failure_message_for_invalid_replies_includes_reason_and_explanation() -> None:
    agent = CodingAgent("demo task", prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS)

    message = agent.failure_message_for_invalid_replies(
        "empty_final_reply",
        3,
    )

    assert message == {
        "role": "assistant",
        "content": (
            "Code Squid stopped after 3 consecutive invalid replies.\n"
            "Last invalid reply reason: empty_final_reply\n"
            "Explanation: the model replied with no tool call and no final content"
        ),
    }


def test_tool_definition_exposes_apply_patch_through_coding_agent() -> None:
    agent = CodingAgent("demo task")

    names = [
        definition["function"]["name"]
        for definition in agent.tool_definitions()
    ]

    assert names == ["read_file", "write_file", "apply_patch", "run_command"]


def test_empty_final_correction_mentions_final_content() -> None:
    agent = CodingAgent("demo task")

    message = agent.correction_message_for("empty_final_reply")

    assert "no tool call and no final content" in message["content"]
    assert "TASK COMPLETE" not in message["content"]


def test_follow_up_message_returns_user_message() -> None:
    agent = CodingAgent("show me what changed")

    message = agent.follow_up_message("show me what changed")

    assert message == {"role": "user", "content": "show me what changed"}


def test_initial_prompts_encourage_compact_markdown_narration() -> None:
    messages = CodingAgent(
        task="Update the UI", prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS
    ).initial_messages()
    combined_prompt = "\n".join(message["content"] for message in messages)

    assert "Write visible action notes in concise lightweight Markdown." in combined_prompt
    assert "keep narration to 2-4 sentences" in combined_prompt
    assert "Use inline code for file names, paths, commands" in combined_prompt
    assert "Do not use `#` headings" in combined_prompt


def test_initial_prompts_keep_markdown_final_summary_guidance() -> None:
    messages = CodingAgent(
        task="Update the UI", prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS
    ).initial_messages()
    combined_prompt = "\n".join(message["content"] for message in messages)

    assert "write the final summary in simple Markdown" in combined_prompt
    assert "Prefer short Markdown headings" in combined_prompt
    assert "Use bullets when they make the summary easier to scan." in combined_prompt
    assert "Use backticks for paths, commands, code symbols" in combined_prompt


def test_initial_prompt_includes_selected_skill_instructions() -> None:
    skill = Skill(
        name="bug-fix",
        description="Fix bugs with small targeted edits.",
        instructions="Prefer small patches.",
        allowed_tools=("read_file", "apply_patch", "run_command"),
        path=Path("SKILL.md"),
    )

    messages = CodingAgent(task="Fix it", skill=skill).initial_messages()

    assert "## Active Skill: bug-fix" in messages[0]["content"]
    assert "Fix bugs with small targeted edits." in messages[0]["content"]
    assert "Prefer small patches." in messages[0]["content"]


def test_default_tool_usage_guidance_is_used_without_skill() -> None:
    assert TOOL_USAGE_GUIDANCE in system_prompt()


def test_read_guidance_prefers_coherent_reads_over_incremental_ranges() -> None:
    assert "Read only the source needed for the next decision or edit" in TOOL_USAGE_GUIDANCE
    assert "understanding the file as a whole is necessary" in TOOL_USAGE_GUIDANCE
    assert "For every targeted read, use ranges" in TOOL_USAGE_GUIDANCE
    assert "request them together in one information-dense read_file call" in TOOL_USAGE_GUIDANCE
    assert "substantial coherent regions over tiny inchworm reads" in TOOL_USAGE_GUIDANCE
    assert "many scattered ranges for speculative broad exploration" in TOOL_USAGE_GUIDANCE
    assert "Do not reread unchanged ranges" in TOOL_USAGE_GUIDANCE
    assert "For obviously large files, prefer a focused line range" not in TOOL_USAGE_GUIDANCE
    assert "do not re-read solely to confirm it happened" in TOOL_USAGE_GUIDANCE


def test_baseline_policy_uses_corrective_failures_and_changes_stalled_approaches() -> None:
    assert (
        "When a tool failure returns exact corrective information, use it directly "
        "before doing more discovery."
        in BASELINE_CODING_POLICY
    )
    assert (
        "If repeated actions fail for the same underlying reason, stop repeating that "
        "approach and choose a materially different next step."
        in BASELINE_CODING_POLICY
    )


def test_baseline_policy_requires_behavioral_verification_against_the_request() -> None:
    assert (
        "Before finishing, compare the final implementation against the user's requested "
        "behavior. A syntax or build check alone does not verify behavioral correctness."
        in BASELINE_CODING_POLICY
    )


def test_baseline_policy_requires_explicit_run_command_verification_intent() -> None:
    assert "Every run_command call must explicitly set verification" in (
        BASELINE_CODING_POLICY
    )
    assert "tests, syntax checks, validation builds, lint or type checks" in (
        BASELINE_CODING_POLICY
    )
    assert "repository discovery, file listings, code searches" in (
        BASELINE_CODING_POLICY
    )
    assert "Classify the command by its purpose" in BASELINE_CODING_POLICY


def test_baseline_policy_removes_replaced_implementations() -> None:
    assert "remove obsolete code, state, helpers, and comments" in BASELINE_CODING_POLICY
    assert "only for a concrete compatibility, fallback" in BASELINE_CODING_POLICY
    assert "no longer referenced or unnecessarily present" in BASELINE_CODING_POLICY


def test_apply_patch_guidance_prefers_diagnostics_over_unconditional_rereads() -> None:
    assert "Choose the intended returned candidate" in TOOL_USAGE_GUIDANCE
    assert "retry apply_patch with only that match_id" in TOOL_USAGE_GUIDANCE
    assert "returned candidate context is insufficient" in (
        TOOL_USAGE_GUIDANCE
    )
    assert "selectable closest current match" in TOOL_USAGE_GUIDANCE
    assert "mutation remains exact and revalidated" in (
        TOOL_USAGE_GUIDANCE
    )


def test_tool_guidance_prevents_shell_workarounds_for_editing_tool_failures() -> None:
    assert (
        "Do not use run_command to work around a dedicated file-editing tool failure "
        "unless shell behavior is genuinely required by the task."
        in TOOL_USAGE_GUIDANCE
    )
    assert (
        "Use run_command for repository discovery, toolchain discovery, verification, "
        "and shell behavior."
        in TOOL_USAGE_GUIDANCE
    )


def test_system_prompt_without_platform_context_preserves_compatibility() -> None:
    assert system_prompt() == SYSTEM_PROMPT
    assert "## Execution Environment" not in system_prompt()


def test_windows_environment_prompt_includes_workspace_and_powershell_guidance() -> None:
    context = PlatformContext("Windows", "PowerShell", "pwsh", "\\", True)
    workspace = r"C:\Users\Example User\Desktop\project"

    prompt = system_prompt(platform_context=context, workspace=workspace)

    assert "Operating system: Windows" in prompt
    assert "Preferred shell: PowerShell" in prompt
    assert "Path separator: \\" in prompt
    assert f"Workspace: {workspace}" in prompt
    assert "Use PowerShell syntax for run_command." in prompt
    assert "Prefer Get-ChildItem" in prompt


def test_non_windows_environment_prompt_omits_powershell_guidance() -> None:
    context = PlatformContext("Linux", "bash", "/bin/bash", "/", False)

    prompt = system_prompt(platform_context=context, workspace="/home/user/project")

    assert "Use commands compatible with bash." in prompt
    assert "PowerShell" not in prompt
    assert "Get-ChildItem" not in prompt


def test_skill_override_does_not_remove_environment_block() -> None:
    skill = Skill(
        name="custom",
        description="Custom behavior.",
        instructions="Follow custom instructions.",
        allowed_tools=("read_file",),
        path=Path("SKILL.md"),
        prompt_sections={
            "SYSTEM_PROMPT_INTRO": PromptSectionOverride(
                section="SYSTEM_PROMPT_INTRO",
                mode="replace",
                content="Custom intro.",
            ),
        },
    )
    context = PlatformContext("macOS", "zsh", "/bin/zsh", "/", False)

    prompt = system_prompt(skill, context, "/Users/example/My Project")

    assert prompt.startswith("Custom intro.")
    assert "## Execution Environment" in prompt
    assert "Workspace: /Users/example/My Project" in prompt
    assert "## Active Skill: custom" in prompt


def test_active_skill_without_tool_usage_guidance_omits_default_guidance_from_system_prompt() -> None:
    skill = Skill(
        name="bug-fix",
        description="Fix bugs with small targeted edits.",
        instructions="Prefer small patches.",
        allowed_tools=("read_file", "apply_patch", "run_command"),
        path=Path("SKILL.md"),
    )

    prompt = system_prompt(skill)

    assert "## Tool usage guidance" not in prompt
    assert TOOL_USAGE_GUIDANCE not in prompt


def test_selected_skill_can_override_prompt_sections() -> None:
    skill = Skill(
        name="user-review",
        description="Review architecture.",
        instructions="Review only.",
        allowed_tools=("read_file", "run_command"),
        path=Path("SKILL.md"),
        prompt_sections={
            "TOOL_USAGE_GUIDANCE": PromptSectionOverride(
                section="TOOL_USAGE_GUIDANCE",
                mode="append",
                content="Use inspection tools only.",
            ),
            "FINAL_SUMMARY_REQUIREMENTS": PromptSectionOverride(
                section="FINAL_SUMMARY_REQUIREMENTS",
                mode="replace",
                content="Write an architecture review.",
            ),
        },
    )

    messages = CodingAgent(task="agent/", skill=skill).initial_messages()

    assert messages[1]["content"] == "agent/"
    assert "Use inspection tools only." in messages[0]["content"]
    assert TOOL_USAGE_GUIDANCE not in messages[0]["content"]
    assert "Write an architecture review." in messages[0]["content"]
    assert "write the final summary in simple Markdown" not in messages[0]["content"]


def test_active_skill_tool_usage_replace_includes_only_custom_guidance() -> None:
    skill = Skill(
        name="focused-review",
        description="Review with custom guidance.",
        instructions="Use custom guidance.",
        allowed_tools=("read_file",),
        path=Path("SKILL.md"),
        prompt_sections={
            "TOOL_USAGE_GUIDANCE": PromptSectionOverride(
                section="TOOL_USAGE_GUIDANCE",
                mode="replace",
                content="Use replacement inspection guidance.",
            ),
        },
    )

    system = system_prompt(skill)
    assert "Use replacement inspection guidance." in system
    assert TOOL_USAGE_GUIDANCE not in system


def test_active_skill_tool_usage_append_includes_only_custom_guidance() -> None:
    skill = Skill(
        name="focused-review",
        description="Review with custom guidance.",
        instructions="Use custom guidance.",
        allowed_tools=("read_file",),
        path=Path("SKILL.md"),
        prompt_sections={
            "TOOL_USAGE_GUIDANCE": PromptSectionOverride(
                section="TOOL_USAGE_GUIDANCE",
                mode="append",
                content="Use appended inspection guidance.",
            ),
        },
    )

    system = system_prompt(skill)
    assert "Use appended inspection guidance." in system
    assert TOOL_USAGE_GUIDANCE not in system

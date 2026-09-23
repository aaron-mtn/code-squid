"""Agent response protocol and application prompt assembly regressions."""

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


def test_validate_reply_accepts_more_than_one_tool_call() -> None:
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

    assert validation == {"ok": True, "reason": ""}


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


def test_invalid_reply_corrections_preserve_necessity_based_batching_rule() -> None:
    agent = CodingAgent("demo task")

    for reason in ("empty_final_reply", "malformed_tool_call"):
        content = agent.correction_message_for(reason)["content"]

        assert "both their arguments and their necessity are already known" in content
        assert "could eliminate or materially change a later call" in content
        assert "wait for it before issuing that call" in content
        assert "fully determined without seeing an earlier call's result" not in content
        assert "none depends on an earlier call's result" not in content


def test_follow_up_message_returns_user_message() -> None:
    agent = CodingAgent("show me what changed")

    message = agent.follow_up_message("show me what changed")

    assert message == {"role": "user", "content": "show me what changed"}


def test_initial_prompts_encourage_compact_useful_narration() -> None:
    messages = CodingAgent(
        task="Update the UI", prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS
    ).initial_messages()
    combined_prompt = "\n".join(message["content"] for message in messages)

    assert "## Visible action notes" in combined_prompt
    assert "Prefer a brief natural note before tool calls when useful." in combined_prompt
    assert "Say what you found, changed, or are checking next." in combined_prompt
    assert "Keep it short" in combined_prompt
    assert "do not restate the whole plan or explain obvious actions" in combined_prompt


def test_initial_prompts_keep_markdown_final_summary_guidance() -> None:
    messages = CodingAgent(
        task="Update the UI", prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS
    ).initial_messages()
    combined_prompt = "\n".join(message["content"] for message in messages)

    assert "## Code Squid final report" in combined_prompt
    assert "Keep the final response concise and appropriate to the task." in combined_prompt
    assert "State the important changes, the verification actually performed" in combined_prompt
    assert "meaningful remaining risk, limitation, or unverified behavior" in combined_prompt
    assert "Use the clearest Markdown structure and omit empty sections." in combined_prompt


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
    assert "Read only what the current decision or edit needs." in TOOL_USAGE_GUIDANCE
    assert "For large files, use coherent relevant ranges" in TOOL_USAGE_GUIDANCE
    assert "read the whole file only when its overall structure genuinely matters" in TOOL_USAGE_GUIDANCE
    assert "Do not scatter speculative reads across files" in TOOL_USAGE_GUIDANCE
    assert "Do not reread unchanged source merely for reassurance" in TOOL_USAGE_GUIDANCE
    assert "If a read is truncated, use returned_line_ranges" in TOOL_USAGE_GUIDANCE


def test_baseline_policy_uses_corrective_failures_and_changes_stalled_approaches() -> None:
    assert "Treat failures as information." in BASELINE_CODING_POLICY
    assert "Address the reported cause or change approach" in BASELINE_CODING_POLICY
    assert "never retry a failed action unchanged" in BASELINE_CODING_POLICY


def test_baseline_policy_requires_behavioral_verification_against_the_request() -> None:
    assert (
        "Verify the behavior that changed with practical, relevant checks."
        in BASELINE_CODING_POLICY
    )


def test_baseline_policy_requires_explicit_run_command_verification_intent() -> None:
    assert "Every run_command call must explicitly set verification" in (
        TOOL_USAGE_GUIDANCE
    )
    assert "verification=true for tests, builds, lint, type or syntax checks" in (
        TOOL_USAGE_GUIDANCE
    )
    assert "verification=false for discovery, searches, setup" in TOOL_USAGE_GUIDANCE
    assert "environment inspection, and ordinary execution" in TOOL_USAGE_GUIDANCE


def test_baseline_policy_removes_replaced_implementations() -> None:
    assert "When replacing an implementation, remove the obsolete path" in BASELINE_CODING_POLICY
    assert "unless a concrete compatibility or fallback need remains" in BASELINE_CODING_POLICY


def test_apply_patch_guidance_prefers_diagnostics_over_unconditional_rereads() -> None:
    assert "If a failure returns selectable candidates" in TOOL_USAGE_GUIDANCE
    assert "choose the intended match_id" in TOOL_USAGE_GUIDANCE
    assert "Reread only when the diagnostics are insufficient." in TOOL_USAGE_GUIDANCE
    assert "Candidate selection still revalidates exact current text." in TOOL_USAGE_GUIDANCE


def test_tool_guidance_prevents_shell_workarounds_for_editing_tool_failures() -> None:
    assert "Do not use run_command in place of read_file, apply_patch, or write_file." in (
        TOOL_USAGE_GUIDANCE
    )
    assert "Use shell discovery to locate relevant files, symbols, tests, or workflows." in (
        TOOL_USAGE_GUIDANCE
    )
    assert "switch to the dedicated file tools for source work" in TOOL_USAGE_GUIDANCE


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
    assert "Use PowerShell syntax, paths, and commands, not Bash-only syntax." in prompt
    assert "use native commands such as Get-ChildItem and Select-String" in prompt


def test_non_windows_environment_prompt_omits_powershell_guidance() -> None:
    context = PlatformContext("Linux", "bash", "/bin/bash", "/", False)

    prompt = system_prompt(platform_context=context, workspace="/home/user/project")

    assert "Use commands and separators compatible with bash." in prompt
    assert "run_command already executes in PowerShell" not in prompt
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


def test_active_skill_without_tool_usage_guidance_keeps_default_guidance_from_system_prompt() -> None:
    skill = Skill(
        name="bug-fix",
        description="Fix bugs with small targeted edits.",
        instructions="Prefer small patches.",
        allowed_tools=("read_file", "apply_patch", "run_command"),
        path=Path("SKILL.md"),
    )

    prompt = system_prompt(skill)

    assert "## Tool usage guidance" in prompt
    assert TOOL_USAGE_GUIDANCE in prompt


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

    messages = CodingAgent(task="agent/", skill=skill, prompt_defaults=CODE_SQUID_PROMPT_DEFAULTS).initial_messages()

    assert messages[1]["content"] == "agent/"
    assert "Use inspection tools only." in messages[0]["content"]
    assert TOOL_USAGE_GUIDANCE in messages[0]["content"]
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


def test_active_skill_tool_usage_append_keeps_default_guidance() -> None:
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
    assert TOOL_USAGE_GUIDANCE in system


def test_failed_patch_guidance_uses_candidates_before_rereading() -> None:
    assert "If a failure returns selectable candidates" in TOOL_USAGE_GUIDANCE
    assert "choose the intended match_id" in TOOL_USAGE_GUIDANCE
    assert "Reread only when the diagnostics are insufficient." in TOOL_USAGE_GUIDANCE


def test_windows_guidance_keeps_dedicated_source_reading_default() -> None:
    context = PlatformContext("Windows", "PowerShell", "powershell", "\\", True)
    prompt = system_prompt(platform_context=context, workspace="C:/repo")
    assert "Prefer dedicated file tools for source reading and editing." in prompt
    assert "For shell discovery, use native commands" in prompt
    assert "Get-ChildItem and Select-String" in prompt

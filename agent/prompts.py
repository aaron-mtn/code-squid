"""Code Squid application prompt defaults and legacy prompt compatibility.

The live transcript uses :func:`system_prompt` plus raw authored user messages.
``TASK_PROMPT`` and ``FOLLOW_UP_PROMPT`` remain parseable/renderable only for
existing Skills and UI metadata; neither wrapper is inserted into transcripts.
"""

from squid_core.platform_context import PlatformContext
from squid_core.skills import Skill
from squid_core.agent.prompts import (
    PROTECTED_RESPONSE_PROTOCOL as REQUIRED_RESPONSE_FORMAT,
    VISIBLE_NARRATION_GUIDANCE as VISIBLE_NARRATION_REQUIREMENTS,
    PromptDefaults,
    correction_message,
    prompt_section,
    system_prompt as core_system_prompt,
    tool_usage_guidance as core_tool_usage_guidance,
)


SYSTEM_PROMPT_INTRO = """
You are Code Squid, a coding agent working inside a repository.

You have tools for reading files, writing and patching files, and running commands.
""".strip()


# This policy is deliberately outside Skill-replaceable sections. It contains
# the fundamental coding discipline audited out of DEFAULT_TASK_PROMPT.
BASELINE_CODING_POLICY = """
## Baseline coding policy

- Work iteratively and understand the requested change before editing.
- Inspect the relevant code, tests, and repository guidance when the task requires it.
- Make the smallest clean change that solves the task; avoid broad unrelated changes.
- Prefer the appropriate file or editing tool for the job.
- Run the strongest practical verification, using the repository's canonical verification command when one is found.
- Avoid unnecessary re-reading, exploration, and repeated checks.
- For browser or UI work, accurately state what was and was not actually run or manually verified.
- When the coding task is complete, stop working and report the result concisely and precisely.
- For coding tasks, identify the changed files, summarize the change, and state the verification performed and any concrete limitations.
""".strip()


TOOL_USAGE_GUIDANCE = """
## Tool usage guidance

- Prefer read_file for reading known files.
- For normal-sized files, read the whole file first.
- If read_file returns content_truncated true, use start_line and end_line to inspect the relevant section.
- For obviously large files, prefer reading a focused line range with read_file instead of reading the whole file.
- Prefer apply_patch for small edits to existing files after reading the relevant file and only when you can provide exact old_text.
- If apply_patch fails because old_text is missing or not unique, read the relevant file section again before retrying.
- Use write_file for new files or full-file replacement. Do not fall back to full-file write_file after apply_patch fails unless the file is small and you have read the full current file.
- Do not use run_command for simple file writes unless the user specifically asks for shell behavior.
- Use run_command for discovery, verification, and shell behavior.
- When using run_command for discovery, prefer focused commands with bounded output appropriate for the current shell.
- Always use absolute paths with read_file, write_file, and apply_patch.
""".strip()


FINAL_SUMMARY_REQUIREMENTS = """
## Code Squid final report

For coding tasks, write the final summary in simple Markdown. Include changed files, what changed, verification, and concrete remaining risks when relevant. Be exact about what was actually verified and do not invent speculative risks.
Prefer short Markdown headings and one-level bullets when they improve readability. Use bullets when they make the summary easier to scan. Use backticks for paths, commands, code symbols, selectors, IDs, and literal values. Avoid HTML, tables, complex nesting, and long implementation inventories unless requested.
""".strip()


CODE_SQUID_PROMPT_DEFAULTS = PromptDefaults(
    agent_name="Code Squid",
    system_prompt_intro=SYSTEM_PROMPT_INTRO,
    baseline_policy=BASELINE_CODING_POLICY,
    tool_usage_guidance=TOOL_USAGE_GUIDANCE,
    final_summary_requirements=FINAL_SUMMARY_REQUIREMENTS,
)


def tool_usage_guidance(skill: Skill | None = None) -> str:
    return core_tool_usage_guidance(TOOL_USAGE_GUIDANCE, skill)


def system_prompt(
    skill: Skill | None = None,
    platform_context: PlatformContext | None = None,
    workspace: str | None = None,
) -> str:
    return core_system_prompt(
        CODE_SQUID_PROMPT_DEFAULTS,
        skill,
        platform_context,
        workspace,
    )


SYSTEM_PROMPT = system_prompt()


# Dead/non-live compatibility template. Its useful protocol, narration, coding
# workflow, verification, and finish-when-complete guidance now lives above or
# in squid_core.agent.prompts and is therefore present in the live system prompt.
DEFAULT_TASK_PROMPT = """
Solve this coding task: {task}

{TOOL_USAGE_GUIDANCE}

{VISIBLE_NARRATION_REQUIREMENTS}

{REQUIRED_RESPONSE_FORMAT}

{FINAL_SUMMARY_REQUIREMENTS}
""".strip()


# Dead/non-live compatibility template for existing Skill section parsing and
# inspection. Follow-ups remain raw authored user messages at runtime.
DEFAULT_FOLLOW_UP_PROMPT = """
Continue this saved Code Squid session with this follow-up request:

{task}

Use the existing transcript as context. Preserve the current task mode, active skill, workspace, constraints, and available tools.
If the follow-up can be answered from existing context, answer directly. Keep the response aligned with the active skill. Do not reset the session.
""".strip()


def task_prompt(task: str, skill: Skill | None = None) -> str:
    prompt = prompt_section("TASK_PROMPT", DEFAULT_TASK_PROMPT, skill)
    return (
        prompt.replace("{task}", task)
        .replace("{TOOL_USAGE_GUIDANCE}", tool_usage_guidance(skill))
        .replace("{VISIBLE_NARRATION_REQUIREMENTS}", VISIBLE_NARRATION_REQUIREMENTS)
        .replace("{REQUIRED_RESPONSE_FORMAT}", REQUIRED_RESPONSE_FORMAT)
        .replace(
            "{FINAL_SUMMARY_REQUIREMENTS}",
            prompt_section(
                "FINAL_SUMMARY_REQUIREMENTS", FINAL_SUMMARY_REQUIREMENTS, skill
            ),
        )
        .strip()
    )


def follow_up_prompt(task: str, skill: Skill | None = None) -> str:
    prompt = prompt_section("FOLLOW_UP_PROMPT", DEFAULT_FOLLOW_UP_PROMPT, skill)
    return prompt.replace("{task}", task).strip()

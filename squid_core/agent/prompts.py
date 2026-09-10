"""Protected agent protocol and prompt assembly."""

from dataclasses import dataclass

from squid_core.platform_context import PlatformContext
from squid_core.skills import Skill


@dataclass(frozen=True)
class PromptDefaults:
    """Small, explicit application prompt surface consumed by Core."""

    agent_name: str = "Agent"
    system_prompt_intro: str = "You are an agent working on a user-authored task."
    baseline_policy: str = ""
    tool_usage_guidance: str = ""
    final_summary_requirements: str = ""


VISIBLE_NARRATION_GUIDANCE = """
## Visible action notes

Strongly prefer a short note before each tool call.

Keep it natural and conversational. Briefly tell the user what you found, what changed, or what you’re checking next.

Usually 1-2 short sentences is enough. Don’t restate the whole plan, explain obvious steps, or make every action sound formal.

Use inline code for file names, paths, commands, functions, selectors, IDs, symbols, and literal values when helpful. Keep formatting light.

Make sure the note matches the tool call that follows and doesn’t claim something happened before it actually did.

Visible narration is preferred but not required for runtime validity. A turn with exactly one valid tool call may still be accepted when the assistant text is blank.
""".strip()


PROTECTED_RESPONSE_PROTOCOL = """
## Response protocol

- A non-final turn uses exactly one real tool call for the immediate next step.
- Never batch multiple tool calls in one response.
- A final response uses no tool call and contains non-empty human-readable content.
- Finish only when the task is complete and verification was run or honestly cannot be run.
""".strip()


PROTECTED_RESPONSE_EXAMPLES = """
## Valid response examples

Valid non-final response:
I found where this is going wrong. I’m going to read the surrounding code before I touch it.
[exactly one real tool call to read the implementation file]

Valid non-final response:
There it is. This should only need a small patch.
[exactly one real tool call to apply the patch]

Valid non-final response:
The fix is in. I’m going to run the relevant check now and make sure I didn’t break anything nearby.
[exactly one real tool call to run verification]

Valid non-final response after a failed patch:
That patch was too broad and matched more than one place. I’m going to read a tighter section and target it properly.
[exactly one real tool call to read the relevant file section]

Valid non-final response after a failed command:
That command isn’t right for this setup. I’m going to check what this project actually uses instead of guessing again.
[exactly one real tool call to inspect project configuration or tooling]

Valid non-final response after enough investigation:
I’ve got enough context now. More digging isn’t going to help, so I’m making the change.
[exactly one real tool call to edit the relevant file]

Valid final response:
Fixed it and ran the relevant checks. The change stayed focused to the part that was causing the issue.
""".strip()


def prompt_section(section_name: str, default: str, skill: Skill | None = None) -> str:
    if skill is None:
        return default
    override = skill.prompt_sections.get(section_name)
    if override is None:
        return default
    if override.mode == "replace":
        return override.content
    if override.mode == "append":
        return f"{default}\n\n{override.content}"
    raise ValueError(f"Unsupported prompt section override mode: {override.mode}")


def tool_usage_guidance(default: str, skill: Skill | None = None) -> str:
    """Preserve the existing Skill opt-in behavior for tool guidance."""

    if skill is None:
        return default
    override = skill.prompt_sections.get("TOOL_USAGE_GUIDANCE")
    if override is None:
        return ""
    return override.content


def skill_prompt_block(skill: Skill | None = None) -> str:
    if skill is None:
        return ""
    return f"""
## Active Skill: {skill.name}

Description:
{skill.description}

Skill instructions:
{skill.instructions}
""".strip()


def execution_environment_prompt(
    platform_context: PlatformContext,
    workspace: str,
) -> str:
    lines = [
        "## Execution Environment",
        "",
        f"Operating system: {platform_context.os_name}",
        f"Preferred shell: {platform_context.shell_name}",
        f"Path separator: {platform_context.path_separator}",
        f"Workspace: {workspace}",
        "",
        "Use commands, quoting, separators, paths, and utilities that are valid for this environment.",
        "Do not mix command syntax or utilities from a different operating system or shell.",
    ]

    if platform_context.is_windows:
        lines.extend(
            [
                "run_command already executes in PowerShell. Write PowerShell commands directly; do not wrap them in `powershell -Command`.",
                "Use PowerShell syntax and separators. Do not use Bash operators such as `&&` or `||`.",
                "Do not assume Unix commands such as ls, cat, grep, find, cp, mv, rm, wc, or python3 are available.",
                "Prefer Get-ChildItem for listing files and directories.",
                "Prefer Get-Content for reading text files.",
                "Prefer Select-String for searching text.",
                "Prefer Copy-Item, Move-Item, and Remove-Item for file operations.",
                "Quote Windows paths when they contain spaces.",
            ]
        )
    else:
        lines.extend(
            [
                f"run_command executes using {platform_context.shell_name}. Write commands directly for that shell.",
                f"Use commands and separators compatible with {platform_context.shell_name}.",
                "Do not assume Windows PowerShell commands or Windows path syntax are available.",
            ]
        )

    return "\n".join(lines)


def system_prompt(
    defaults: PromptDefaults | None = None,
    skill: Skill | None = None,
    platform_context: PlatformContext | None = None,
    workspace: str | None = None,
) -> str:
    defaults = defaults or PromptDefaults()
    intro = prompt_section("SYSTEM_PROMPT_INTRO", defaults.system_prompt_intro, skill)
    environment = (
        execution_environment_prompt(platform_context, workspace)
        if platform_context is not None and workspace is not None
        else ""
    )
    final_guidance = prompt_section(
        "FINAL_SUMMARY_REQUIREMENTS",
        defaults.final_summary_requirements,
        skill,
    )
    sections = [
        intro,
        defaults.baseline_policy,
        environment,
        skill_prompt_block(skill),
        tool_usage_guidance(defaults.tool_usage_guidance, skill),
        VISIBLE_NARRATION_GUIDANCE,
        PROTECTED_RESPONSE_PROTOCOL,
        final_guidance,
        PROTECTED_RESPONSE_EXAMPLES,
    ]
    return "\n\n".join(section for section in sections if section.strip()).strip()


CORRECTION_MESSAGES = {
    "empty_final_reply": """
Format error: your last response had no tool call and no final content.

If the task is complete, reply with a concise non-empty final response and no tool call.
If work remains, choose exactly one real tool call for the immediate next step. Brief visible narration is strongly preferred.
Do not restate the plan or do extra work unless concrete work remains.
""".strip(),
    "non_final_too_many_tool_calls": """
Format error: your last response requested too many tool calls.

Only one tool call is allowed per turn. Do not batch reads, writes, or commands. Choose the single most important immediate action and call only that tool now. Brief visible narration is strongly preferred.
""".strip(),
    "malformed_tool_call": """
Format error: your last response included an invalid tool call.

Use one available tool with valid arguments for the immediate next step. Brief visible narration is strongly preferred.
""".strip(),
}


def correction_message(reason: str) -> str:
    return CORRECTION_MESSAGES.get(
        reason,
        "Your last response was invalid. Reply with either exactly one valid tool call for the immediate next step or a non-empty final response with no tool call.",
    )

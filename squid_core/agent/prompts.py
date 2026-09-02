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

Strongly prefer a brief visible action note before each tool call. The note should explain why that one action is the immediate next step, without exposing hidden reasoning or expanding into a broad plan.
Write visible action notes in concise lightweight Markdown. Prefer short paragraphs and keep narration to 2-4 sentences unless the situation genuinely needs more. Use inline code for file names, paths, commands, functions, selectors, IDs, symbols, and literal values. Do not use `#` headings or over-format narration.
Keep the note concise and make it match the tool call that follows.

Visible narration is a response-shaping preference, not a runtime validity requirement. A turn with exactly one valid tool call may still be accepted when its assistant text is blank.
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
The failing test identifies the behavior, but the implementation path still needs inspection. I’ll read the relevant implementation file before editing so the change stays focused.
[exactly one real tool call to read the implementation file]

Valid non-final response:
The implementation is understood and the change is isolated. I’ll apply one focused patch now.
[exactly one real tool call to apply the patch]

Valid non-final response:
The focused change is in place but has not been verified. I’ll run the most relevant verification now.
[exactly one real tool call to run verification]

Valid final response:
Implemented the requested change and verified it with the relevant test suite.
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
        "Use commands, quoting, and path syntax valid for this environment.",
    ]
    if platform_context.is_windows:
        lines.extend(
            [
                "Use PowerShell syntax for run_command.",
                "Do not assume Unix commands such as ls, cat, grep, find, cp, mv, or rm are available.",
                "Prefer Get-ChildItem for listing files and directories.",
                "Prefer Get-Content for reading text files.",
                "Prefer Select-String for searching text.",
                "Prefer Copy-Item, Move-Item, and Remove-Item for file operations.",
                "Quote Windows paths when they contain spaces.",
            ]
        )
    else:
        lines.append(f"Use commands compatible with {platform_context.shell_name}.")
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

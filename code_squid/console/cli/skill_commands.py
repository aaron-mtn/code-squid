"""Skill command and status helpers for the Code Squid CLI."""

from code_squid.app_paths import code_squid_home
from squid_core.skills import discover_skills


SKILL_COMMAND = "/skill"


def _is_skill_input(task: str) -> bool:
    stripped = task.strip()
    return stripped == SKILL_COMMAND or stripped.startswith(f"{SKILL_COMMAND} ")


def _format_skill_details(skill_name: str | None) -> list[str]:
    if skill_name is None:
        return ["Current skill: none"]

    skill = discover_skills(app_home=code_squid_home()).get(skill_name)
    lines = [f"Current skill: {skill_name}"]
    if skill is None:
        return lines

    if skill.allowed_tools:
        lines.append(f"Tools: {', '.join(skill.allowed_tools)}")
    if skill.prompt_sections:
        lines.append(f"Prompt overrides: {', '.join(skill.prompt_sections)}")
    return lines


def _format_available_skills() -> list[str]:
    skills = discover_skills(app_home=code_squid_home())
    if not skills:
        return ["Available skills:", "none"]

    lines = ["Available skills:"]
    for skill in skills.values():
        lines.append(f"- {skill.name}: {skill.description}")
    return lines


def _format_skill_status(skill_name: str | None) -> str:
    return "\n".join(
        [
            *_format_skill_details(skill_name),
            "",
            *_format_available_skills(),
        ]
    )


def _print_skill_status(skill_name: str | None) -> None:
    print(_format_skill_status(skill_name))


def _handle_skill_input(
    task: str,
    skill_name: str | None,
    mod_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Handle one Skill command and return unambiguous Skill/Mod selections."""
    parts = task.strip().split()
    if len(parts) == 1:
        _print_skill_status(skill_name)
        return skill_name, mod_name

    if len(parts) != 2:
        print("Usage: /skill [name|none]")
        return skill_name, mod_name

    requested_skill = parts[1]
    if requested_skill == "none":
        print("Active skill cleared.")
        return None, mod_name

    skills = discover_skills(app_home=code_squid_home())
    skill = skills.get(requested_skill)
    if skill is None:
        print(f"Unknown skill: {requested_skill}")
        print("Run /skill to see available skills.")
        return skill_name, mod_name

    if mod_name is not None:
        print(f"Active Mod {mod_name} cleared by standalone skill selection.")
    print(f"Active skill set to: {skill.name}")
    if skill.allowed_tools:
        print(f"Tools: {', '.join(skill.allowed_tools)}")
    return skill.name, None


def handle_skill_listing() -> int:
    """Print standalone Skills for the singular shell ``skill`` command."""

    print("\n".join(_format_available_skills()))
    return 0

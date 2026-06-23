# core/skills.py

"""Minimal built-in Code Squid skill loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills" / "builtin"
PROMPT_SECTION_MODES = {"replace", "append"}
SUPPORTED_PROMPT_SECTIONS = {
    "SYSTEM_PROMPT_INTRO",
    "TASK_PROMPT",
    "FOLLOW_UP_PROMPT",
    "TOOL_USAGE_GUIDANCE",
    "FINAL_SUMMARY_REQUIREMENTS",
}
UNSUPPORTED_PROMPT_SECTIONS = {
    "VISIBLE_NARRATION_REQUIREMENTS",
    "REQUIRED_RESPONSE_FORMAT",
    "CORRECTION_MESSAGES",
    "COMPACTION_PROMPT",
}


@dataclass(frozen=True)
class PromptSectionOverride:
    section: str
    mode: str
    content: str


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...]
    path: Path
    prompt_sections: dict[str, PromptSectionOverride] = field(default_factory=dict)


def parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    frontmatter, instructions = _split_frontmatter(text, path)
    data = _parse_simple_frontmatter(frontmatter, path)

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    if not name:
        raise ValueError(f"{path}: missing required frontmatter field: name")
    if not description:
        raise ValueError(f"{path}: missing required frontmatter field: description")

    allowed_tools_text = data.get("allowed-tools", "").strip()
    allowed_tools = tuple(allowed_tools_text.split()) if allowed_tools_text else ()

    instructions, prompt_sections = _parse_prompt_section_overrides(instructions, path)

    return Skill(
        name=name,
        description=description,
        instructions=instructions.strip(),
        allowed_tools=allowed_tools,
        path=path,
        prompt_sections=prompt_sections,
    )


def discover_builtin_skills() -> dict[str, Skill]:
    if not BUILTIN_SKILLS_DIR.exists():
        return {}

    skills = {}
    for skill_file in sorted(BUILTIN_SKILLS_DIR.glob("*/SKILL.md")):
        skill = parse_skill_file(skill_file)
        skills[skill.name] = skill
    return skills


def _split_frontmatter(text: str, path: Path) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: SKILL.md must start with YAML frontmatter")

    end_marker = "\n---\n"
    end = text.find(end_marker, 4)
    if end == -1:
        raise ValueError(f"{path}: SKILL.md frontmatter must end with ---")

    return text[4:end], text[end + len(end_marker) :]


def _parse_simple_frontmatter(frontmatter: str, path: Path) -> dict[str, str]:
    data = {}
    for line_number, line in enumerate(frontmatter.splitlines(), start=2):
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            raise ValueError(f"{path}:{line_number}: invalid frontmatter line")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"{path}:{line_number}: invalid empty frontmatter key")
        data[key] = value.strip().strip("\"'")
    return data


def _parse_prompt_section_overrides(
    instructions: str,
    path: Path,
) -> tuple[str, dict[str, PromptSectionOverride]]:
    lines = instructions.splitlines()
    normal_lines = []
    prompt_sections = {}
    current_section = None
    current_mode = None
    current_content = []

    for line_number, line in enumerate(lines, start=1):
        heading = _parse_prompt_section_heading(line, path, line_number)
        if heading is None:
            if current_section is None:
                normal_lines.append(line)
            else:
                current_content.append(line)
            continue

        if current_section is not None:
            prompt_sections[current_section] = PromptSectionOverride(
                section=current_section,
                mode=current_mode,
                content="\n".join(current_content).strip(),
            )

        current_section, current_mode = heading
        current_content = []

    if current_section is not None:
        prompt_sections[current_section] = PromptSectionOverride(
            section=current_section,
            mode=current_mode,
            content="\n".join(current_content).strip(),
        )

    return "\n".join(normal_lines).strip(), prompt_sections


def _parse_prompt_section_heading(
    line: str,
    path: Path,
    line_number: int,
) -> tuple[str, str] | None:
    if not line.startswith("## "):
        return None

    parts = line[3:].strip().split()
    if len(parts) != 2:
        return None

    section, mode = parts
    looks_like_prompt_section = section.isupper() and "_" in section
    if not looks_like_prompt_section:
        return None

    if section in UNSUPPORTED_PROMPT_SECTIONS:
        raise ValueError(f"{path}:{line_number}: prompt section override is not supported: {section}")
    if section not in SUPPORTED_PROMPT_SECTIONS:
        raise ValueError(f"{path}:{line_number}: unknown prompt section override: {section}")
    if mode not in PROMPT_SECTION_MODES:
        raise ValueError(f"{path}:{line_number}: unsupported prompt section override mode: {mode}")

    return section, mode

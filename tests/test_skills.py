from pathlib import Path

from core.skills import parse_skill_file


def _write_skill(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_valid_skill_file(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name: bug-fix
description: Fix bugs with small targeted edits.
allowed-tools: read_file apply_patch run_command
---

Focus on the requested bug.
""",
    )

    skill = parse_skill_file(path)

    assert skill.name == "bug-fix"
    assert skill.description == "Fix bugs with small targeted edits."
    assert skill.allowed_tools == ("read_file", "apply_patch", "run_command")
    assert skill.instructions == "Focus on the requested bug."
    assert skill.path == path


def test_missing_required_skill_fields_fail(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name:
---

Instructions.
""",
    )

    try:
        parse_skill_file(path)
    except ValueError as error:
        assert "missing required frontmatter field: name" in str(error)
    else:
        raise AssertionError("Expected missing name to fail")


def test_allowed_tools_may_be_missing(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name: review
description: Review only.
---

Review the code.
""",
    )

    skill = parse_skill_file(path)

    assert skill.allowed_tools == ()


def test_parse_skill_prompt_section_overrides(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name: review
description: Review only.
---

Review instructions.

## TASK_PROMPT replace

Review this: {task}

## TOOL_USAGE_GUIDANCE append

Use inspection tools only.
""",
    )

    skill = parse_skill_file(path)

    assert skill.instructions == "Review instructions."
    assert skill.prompt_sections["TASK_PROMPT"].section == "TASK_PROMPT"
    assert skill.prompt_sections["TASK_PROMPT"].mode == "replace"
    assert skill.prompt_sections["TASK_PROMPT"].content == "Review this: {task}"
    assert skill.prompt_sections["TOOL_USAGE_GUIDANCE"].mode == "append"
    assert skill.prompt_sections["TOOL_USAGE_GUIDANCE"].content == "Use inspection tools only."


def test_parse_follow_up_prompt_override_still_supported(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name: review
description: Review only.
---

Review instructions.

## FOLLOW_UP_PROMPT replace

Continue review: {task}
""",
    )

    skill = parse_skill_file(path)

    assert skill.prompt_sections["FOLLOW_UP_PROMPT"].section == "FOLLOW_UP_PROMPT"
    assert skill.prompt_sections["FOLLOW_UP_PROMPT"].mode == "replace"
    assert skill.prompt_sections["FOLLOW_UP_PROMPT"].content == "Continue review: {task}"


def test_architecture_review_parses_without_follow_up_prompt_override() -> None:
    skill = parse_skill_file(Path("skills/builtin/architecture-review/SKILL.md"))

    assert "FOLLOW_UP_PROMPT" not in skill.prompt_sections
    assert skill.prompt_sections["TASK_PROMPT"].mode == "replace"
    assert skill.prompt_sections["FINAL_SUMMARY_REQUIREMENTS"].mode == "replace"
    assert skill.prompt_sections["TOOL_USAGE_GUIDANCE"].mode == "append"


def test_unknown_prompt_section_override_fails(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name: review
description: Review only.
---

## MADE_UP_SECTION replace

Nope.
""",
    )

    try:
        parse_skill_file(path)
    except ValueError as error:
        assert "unknown prompt section override: MADE_UP_SECTION" in str(error)
    else:
        raise AssertionError("Expected unknown prompt section override to fail")


def test_unsupported_prompt_section_override_fails(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name: review
description: Review only.
---

## REQUIRED_RESPONSE_FORMAT replace

Nope.
""",
    )

    try:
        parse_skill_file(path)
    except ValueError as error:
        assert "prompt section override is not supported: REQUIRED_RESPONSE_FORMAT" in str(error)
    else:
        raise AssertionError("Expected unsupported prompt section override to fail")


def test_unsupported_prompt_section_mode_fails(tmp_path: Path) -> None:
    path = _write_skill(
        tmp_path / "SKILL.md",
        """---
name: review
description: Review only.
---

## TASK_PROMPT overwrite

Nope.
""",
    )

    try:
        parse_skill_file(path)
    except ValueError as error:
        assert "unsupported prompt section override mode: overwrite" in str(error)
    else:
        raise AssertionError("Expected unsupported prompt section mode to fail")

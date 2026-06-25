# Code Squid Skills

Code Squid skills are file-backed prompt/tool profiles stored as `SKILL.md`
files.

## Location

```text
skills/builtin/<skill-name>/SKILL.md
skills/user/<skill-name>/SKILL.md
```

## Frontmatter

Supported fields:

- `name`
- `description`
- `allowed-tools`

Example:

```yaml
---
name: architecture-review
description: Review architecture and design without modifying files.
allowed-tools: read_file run_command
---
```

Missing or empty `allowed-tools` means the default full tool set. Unknown tool
names fail during run construction.

## Instructions

Markdown before any recognized override heading becomes the skill instructions
and is inserted into the system prompt under `## Active Skill`.

## Prompt section overrides

Use headings like:

```md
## TASK_PROMPT replace

Review this repository or code area: {task}

## TOOL_USAGE_GUIDANCE append

Prefer reading high-level files before implementation details.
```

Supported sections:

- `SYSTEM_PROMPT_INTRO`
- `TASK_PROMPT`
- `FOLLOW_UP_PROMPT`
- `TOOL_USAGE_GUIDANCE`
- `FINAL_SUMMARY_REQUIREMENTS`

Supported modes:

- `replace`
- `append`

## Protected prompt rails

Skills cannot override:

- `VISIBLE_NARRATION_REQUIREMENTS`
- `REQUIRED_RESPONSE_FORMAT`
- `CORRECTION_MESSAGES`
- `COMPACTION_PROMPT`

## CLI usage

```bash
python main.py skills
python main.py --skill architecture-review
```

Inside interactive CLI:

```text
/skill
/skill architecture-review
/skill none
/skill default
```

## Debugging

Saved sessions include non-transcript `run_context` entries showing the active
skill, filtered tools, and prompt overrides for each run. Use:

```bash
python main.py show latest
```

to inspect them.

## Current built-in skills

Default/no skill = normal Code Squid coding behavior.

`architecture-review` is an inspection-only review skill. It allows only
`read_file` and `run_command`, replaces `TASK_PROMPT`, replaces
`FINAL_SUMMARY_REQUIREMENTS`, and appends `TOOL_USAGE_GUIDANCE`.

## Not implemented yet

- Desktop skill picker/API support
- Skill builder
- New skill-specific tools

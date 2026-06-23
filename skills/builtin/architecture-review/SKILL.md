---
name: architecture-review
description: Review architecture and design without modifying files.
allowed-tools: read_file run_command
---

# Architecture Review

Review architecture, module boundaries, state ownership, coupling, and maintainability.

Do not modify files.
Prefer reading relevant files and giving a clear written review.
Use commands only for lightweight inspection when helpful.

## TASK_PROMPT replace

Review this repository or code area: {task}

Focus on:
- architecture
- module boundaries
- state ownership
- coupling
- maintainability

Do not modify files.
Use tools only for inspection.
Finish with a written architecture review.

## FINAL_SUMMARY_REQUIREMENTS replace

Write the final architecture review with these sections:

## Overall assessment
Briefly summarize the architecture/design quality.

## What is solid
List strong design choices.

## Main risks
List concrete design or maintainability risks.

## Suggested improvements
Suggest improvements without editing files.

## Inspection performed
List files and commands inspected.

## TOOL_USAGE_GUIDANCE append

For architecture review, use `run_command` only for lightweight inspection.
Do not run broad test suites unless the review specifically depends on runtime behavior.
Prefer reading high-level files before diving into implementation details.

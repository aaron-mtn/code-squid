"""Render Code Squid runtime facts for deterministic compaction context."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable


_DIRECT_MUTATION_TOOLS = {"apply_patch", "write_file"}
_MAX_OUTPUT_EXCERPT_CHARS = 600
_OUTPUT_OMISSION_MARKER = "\n... omitted ...\n"


@dataclass(frozen=True)
class _ToolEvent:
    """One canonical tool result paired with its original call metadata."""

    index: int
    tool: str
    arguments: dict
    result: dict


class CodeSquidCompactionContextProvider:
    """Build authoritative context from the session's canonical messages."""

    def __init__(self, load_messages: Callable[[], list[dict]]) -> None:
        self._load_messages = load_messages

    def __call__(self) -> str | None:
        return authoritative_compaction_context(self._load_messages())


def authoritative_compaction_context(messages: list[dict]) -> str | None:
    """Describe mechanically known mutations, verification, and open failures."""
    events = _tool_events(messages)
    latest_mutation = _latest(
        event
        for event in events
        if event.tool in _DIRECT_MUTATION_TOOLS and event.result.get("ok") is True
    )
    latest_verification = _latest(
        event
        for event in events
        if event.tool == "run_command"
        and _field(event, "verification") is True
    )
    unresolved_failure = _latest_unresolved_failure(events)

    if latest_mutation is None and latest_verification is None and unresolved_failure is None:
        return None

    sections = ["# Authoritative Runtime Facts"]
    if latest_mutation is not None:
        sections.append(
            "Latest known direct mutation:\n\n"
            f"- {_render_mutation(latest_mutation)}"
        )
    if latest_verification is not None:
        sections.append(
            "Latest verification:\n\n"
            + "\n".join(_render_verification(latest_verification))
        )
        sections.append(
            "Verification status:\n\n"
            f"- {_verification_status(latest_verification, latest_mutation)}"
        )
    if unresolved_failure is not None:
        sections.append(
            "Latest unresolved tool failure:\n\n"
            f"- {_render_failure(unresolved_failure)}"
        )
    sections.append(
        "These runtime facts supersede conflicting statements in the compacted "
        "summary above."
    )
    return "\n\n".join(sections)


def _tool_events(messages: list[dict]) -> list[_ToolEvent]:
    calls: dict[str, tuple[str, dict]] = {}
    events = []
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                call_id = call.get("id")
                function = call.get("function") or {}
                if isinstance(call_id, str):
                    calls[call_id] = (
                        function.get("name", ""),
                        _arguments(function.get("arguments")),
                    )
            continue
        if message.get("role") != "tool":
            continue
        try:
            result = json.loads(message.get("content", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict):
            continue
        call_tool, arguments = calls.get(message.get("tool_call_id"), ("", {}))
        tool = result.get("tool") or call_tool
        if isinstance(tool, str) and tool:
            events.append(_ToolEvent(index, tool, arguments, result))
    return events


def _arguments(raw_arguments) -> dict:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str):
        return {}
    try:
        value = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _latest(events) -> _ToolEvent | None:
    return max(events, key=lambda event: event.index, default=None)


def _field(event: _ToolEvent, name: str):
    value = event.result.get(name)
    return event.arguments.get(name) if value is None else value


def _render_mutation(event: _ToolEvent) -> str:
    path = _field(event, "path") or "unknown target"
    details = []
    if event.tool == "apply_patch":
        if isinstance(event.result.get("replacements"), int):
            count = event.result["replacements"]
            details.append(f"{count} replacement{'s' if count != 1 else ''}")
        start = event.result.get("start_line")
        end = event.result.get("end_line_after")
        if isinstance(start, int) and isinstance(end, int):
            details.append(f"result lines {start}-{end}")
    elif isinstance(event.result.get("summary"), str):
        details.append(event.result["summary"].rstrip("."))
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{event.tool} on {_code(str(path))} succeeded{suffix}."


def _render_verification(event: _ToolEvent) -> list[str]:
    command = str(_field(event, "command") or "unknown command")
    lines = [
        f"- {_code(command)}",
        f"- {'PASSED' if event.result.get('ok') is True else 'FAILED'}",
    ]
    excerpt = _output_excerpt(event.result) if event.result.get("ok") is not True else ""
    if excerpt:
        lines.append(f"- {_code(excerpt)}")
    return lines


def _verification_status(
    verification: _ToolEvent,
    mutation: _ToolEvent | None,
) -> str:
    if mutation is not None and mutation.index > verification.index:
        return (
            "A successful known direct mutation occurred after this verification, "
            "so it does not describe the latest known directly edited state."
        )
    return "No known direct mutation occurred after this verification."


def _latest_unresolved_failure(events: list[_ToolEvent]) -> _ToolEvent | None:
    failures = []
    for event in events:
        if event.result.get("ok") is False and _failure_detail(event):
            failures.append(event)
            continue
        if event.result.get("ok") is not True:
            continue
        if event.tool == "run_command" and _field(event, "verification") is True:
            # A later successful verification supersedes prior verification
            # failures even when the app used a different verification command.
            failures = [
                failure
                for failure in failures
                if not (
                    failure.tool == "run_command"
                    and _field(failure, "verification") is True
                )
            ]
        success_key = _operation_key(event)
        failures = [
            failure
            for failure in failures
            if _operation_key(failure) != success_key
        ]
    return failures[-1] if failures else None


def _operation_key(event: _ToolEvent) -> tuple[str, str]:
    if event.tool == "run_command":
        identity = _field(event, "command")
        category = event.tool
    else:
        identity = _field(event, "path")
        category = (
            "direct_mutation"
            if event.tool in _DIRECT_MUTATION_TOOLS
            else event.tool
        )
    return category, str(identity or "")


def _render_failure(event: _ToolEvent) -> str:
    detail = _failure_detail(event)
    if event.tool == "run_command":
        subject = _code(str(_field(event, "command") or "unknown command"))
    else:
        path = _field(event, "path")
        subject = event.tool + (f" on {_code(str(path))}" if path else "")
    return f"{subject} failed with {_code(detail)}."


def _failure_detail(event: _ToolEvent) -> str:
    return _output_excerpt(event.result) or str(
        event.result.get("error")
        or event.result.get("reason")
        or event.result.get("failure_class")
        or ""
    )


def _output_excerpt(result: dict) -> str:
    output = result.get("output")
    if not isinstance(output, str) or not output.strip():
        return ""
    if len(output) <= _MAX_OUTPUT_EXCERPT_CHARS:
        return output

    # Do not guess which part of a failure is useful. Retain both ends of the
    # raw evidence while keeping the carry-forward context predictably small.
    retained_chars = _MAX_OUTPUT_EXCERPT_CHARS - len(_OUTPUT_OMISSION_MARKER)
    head_chars = (retained_chars + 1) // 2
    tail_chars = retained_chars - head_chars
    return (
        output[:head_chars]
        + _OUTPUT_OMISSION_MARKER
        + output[-tail_chars:]
    )


def _code(value: str) -> str:
    return f"`{value.replace('`', chr(92) + '`')}`"

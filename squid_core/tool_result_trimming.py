"""Render canonical tool results into a bounded, model-visible history view."""

from __future__ import annotations

import json
from copy import deepcopy

from squid_core.settings import ToolResultTrimmingSettings


_OMITTED_MARKERS = {
    "read_file": "[older read content omitted; reread if needed]",
    "run_command": "[older command output omitted; rerun if needed]",
    "apply_patch": "[older patch diagnostic omitted]",
    "write_file": "[older written content omitted; reread if needed]",
}


def render_messages_for_model(
    messages: list[dict],
    settings: ToolResultTrimmingSettings,
) -> list[dict]:
    """Return a request-only history view without mutating canonical messages."""
    if not settings.enabled:
        return list(messages)

    tool_indexes = [
        index for index, message in enumerate(messages) if message.get("role") == "tool"
    ]
    old_count = max(0, len(tool_indexes) - settings.recent_full_results)
    old_indexes = set(tool_indexes[:old_count])
    if not old_indexes:
        return list(messages)

    tool_names = _tool_names_by_call_id(messages)
    rendered = []
    for index, message in enumerate(messages):
        if index not in old_indexes:
            rendered.append(message)
            continue

        rendered.append(
            _render_tool_message(
                message,
                tool_names.get(message.get("tool_call_id")),
                settings,
            )
        )
    return rendered


def render_tool_result_for_model(
    canonical_result: dict,
    *,
    is_recent: bool,
    settings: ToolResultTrimmingSettings,
    tool_name: str | None = None,
) -> dict:
    """Return one full or reduced result copy for model-visible rendering."""
    if not settings.enabled or is_recent:
        return canonical_result

    name = tool_name or canonical_result.get("tool")
    if name == "read_file":
        return _trim_payload(
            canonical_result,
            "content",
            settings.read_old_content_chars,
            name,
        )
    if name == "run_command":
        return _trim_payload(
            canonical_result,
            "output",
            settings.command_old_output_chars,
            name,
        )
    if name == "apply_patch" and canonical_result.get("ok") is False:
        return _trim_patch_diagnostics(
            canonical_result, settings.patch_old_diagnostic_chars
        )
    if name == "write_file":
        return _trim_payload(
            canonical_result,
            "content",
            settings.write_old_content_chars,
            name,
        )

    # Future and caller-defined tools retain all information until they opt in.
    return canonical_result


def _render_tool_message(
    message: dict,
    paired_tool_name: str | None,
    settings: ToolResultTrimmingSettings,
) -> dict:
    content = message.get("content")
    if not isinstance(content, str):
        return message
    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return message
    if not isinstance(result, dict):
        return message

    rendered_result = render_tool_result_for_model(
        result,
        tool_name=paired_tool_name,
        is_recent=False,
        settings=settings,
    )
    if rendered_result is result:
        return message

    rendered_message = dict(message)
    # Match ToolResults' canonical serialization so only the payload differs.
    rendered_message["content"] = json.dumps(rendered_result, indent=2)
    return rendered_message


def _tool_names_by_call_id(messages: list[dict]) -> dict[str, str]:
    names = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or ():
            call_id = call.get("id")
            function = call.get("function") or {}
            name = function.get("name")
            if isinstance(call_id, str) and isinstance(name, str):
                names[call_id] = name
    return names


def _trim_payload(result: dict, field: str, limit: int, tool_name: str) -> dict:
    payload = result.get(field)
    if not isinstance(payload, str) or len(payload) <= limit:
        return result

    rendered = dict(result)
    rendered[field] = _bounded_text(payload, limit, _OMITTED_MARKERS[tool_name])
    rendered[f"model_{field}_truncated"] = True
    rendered[f"model_{field}_original_chars"] = len(payload)
    rendered[f"model_{field}_returned_chars"] = len(rendered[field])
    return rendered


def _trim_patch_diagnostics(result: dict, limit: int) -> dict:
    rendered = deepcopy(result)
    changed = False
    remaining = limit
    for container, field in _patch_diagnostic_fields(rendered):
        value = container.get(field)
        if not isinstance(value, str):
            continue
        if len(value) <= remaining:
            remaining -= len(value)
            continue
        changed = True
        if remaining:
            container[field] = _bounded_text(value, remaining, "")
            remaining = 0
        else:
            container.pop(field)
    if not changed:
        return result
    rendered["model_diagnostic_truncated"] = True
    rendered["model_diagnostic_note"] = _OMITTED_MARKERS["apply_patch"]
    return rendered


def _patch_diagnostic_fields(result: dict):
    closest_match = result.get("closest_match")
    if isinstance(closest_match, dict):
        yield closest_match, "content"
    for collection_name in ("candidates", "matches"):
        collection = result.get(collection_name)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            for field in ("text", "context", "content"):
                if field in item:
                    yield item, field


def _bounded_text(text: str, limit: int, omitted_marker: str) -> str:
    """Use deterministic head/tail retention with an exact output bound."""
    if limit == 0:
        return omitted_marker
    marker = "\n[older payload truncated]\n"
    if limit <= len(marker):
        return marker[:limit]
    remaining = limit - len(marker)
    head_chars = (remaining + 1) // 2
    tail_chars = remaining // 2
    tail = text[-tail_chars:] if tail_chars else ""
    return text[:head_chars] + marker + tail

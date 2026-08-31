"""Small stateless API for one plain-text model response."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from config.settings import Settings, load_settings
from core.model_adapter import ModelAdapter
from providers.factory import build_provider, tool_call_content_mode


def generate_text(
    input: str | list[dict],
    *,
    settings: Settings | None = None,
    please_stop_contemplating_the_void: bool = False,
) -> str:
    """Generate one text response from a prompt or existing conversation."""

    settings = load_settings(Path.cwd()) if settings is None else settings
    provider = build_provider(settings)
    model_adapter = ModelAdapter(
        provider=provider,
        model_name=settings.model.name,
        tool_call_content_mode=tool_call_content_mode(settings),
        provider_name=settings.model.provider,
    )
    messages = [{"role": "user", "content": input}] if isinstance(input, str) else input

    if please_stop_contemplating_the_void:
        return model_adapter.complete_text(
            messages,
            please_stop_contemplating_the_void=True,
        )["content"]
    return model_adapter.complete_text(messages)["content"]


def stream_text(
    input: str | list[dict],
    on_text_delta: Callable[[str], None],
    *,
    settings: Settings | None = None,
    trace_callback: Callable[[dict], None] | None = None,
    please_stop_contemplating_the_void: bool = False,
) -> str:
    """Stream one plain-text response and return its assembled content.

    ``trace_callback`` is an opt-in diagnostic seam for callers that need the
    provider's raw streaming boundary. Normal generation leaves it unset, so
    provider behavior and ordinary debug output remain unchanged.
    """

    settings = load_settings(Path.cwd()) if settings is None else settings
    provider = build_provider(settings)
    model_adapter = ModelAdapter(
        provider=provider,
        model_name=settings.model.name,
        tool_call_content_mode=tool_call_content_mode(settings),
        provider_name=settings.model.provider,
    )
    messages = [{"role": "user", "content": input}] if isinstance(input, str) else input

    request_options = {}
    if trace_callback is not None:
        request_options["trace_callback"] = trace_callback
    if please_stop_contemplating_the_void:
        request_options["please_stop_contemplating_the_void"] = True
    return model_adapter.complete_text_streaming(
        messages,
        on_text_delta,
        **request_options,
    )

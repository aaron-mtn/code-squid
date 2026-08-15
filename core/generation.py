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

    return model_adapter.complete_text(messages)["content"]


def stream_text(
    input: str | list[dict],
    on_text_delta: Callable[[str], None],
    *,
    settings: Settings | None = None,
) -> str:
    """Stream one plain-text response and return its assembled content."""

    settings = load_settings(Path.cwd()) if settings is None else settings
    provider = build_provider(settings)
    model_adapter = ModelAdapter(
        provider=provider,
        model_name=settings.model.name,
        tool_call_content_mode=tool_call_content_mode(settings),
        provider_name=settings.model.provider,
    )
    messages = [{"role": "user", "content": input}] if isinstance(input, str) else input

    return model_adapter.complete_text_streaming(messages, on_text_delta)

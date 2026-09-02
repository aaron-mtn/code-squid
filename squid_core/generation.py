"""Small stateless API for one plain-text model response."""

from __future__ import annotations

from typing import Callable

from squid_core.model_adapter import ModelAdapter
from squid_core.providers import build_provider, tool_call_content_mode
from squid_core.settings import RuntimeSettings


def _resolve_model_adapter(
    settings: RuntimeSettings | None,
    model_adapter: ModelAdapter | None,
) -> ModelAdapter:
    if model_adapter is not None:
        return model_adapter
    if settings is None or settings.provider is None:
        raise ValueError("settings or model_adapter must be supplied")

    provider = build_provider(settings.provider)
    return ModelAdapter(
        provider=provider,
        model_name=settings.provider.model_name,
        tool_call_content_mode=tool_call_content_mode(settings.provider),
        provider_name=settings.provider.provider,
    )


def generate_text(
    input: str | list[dict],
    *,
    settings: RuntimeSettings | None = None,
    model_adapter: ModelAdapter | None = None,
    please_stop_contemplating_the_void: bool = False,
) -> str:
    """Generate one text response from a prompt or existing conversation."""

    model_adapter = _resolve_model_adapter(settings, model_adapter)
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
    settings: RuntimeSettings | None = None,
    model_adapter: ModelAdapter | None = None,
    trace_callback: Callable[[dict], None] | None = None,
    please_stop_contemplating_the_void: bool = False,
) -> str:
    """Stream one plain-text response and return its assembled content.

    ``trace_callback`` is an opt-in diagnostic seam for callers that need the
    provider's raw streaming boundary. Normal generation leaves it unset, so
    provider behavior and ordinary debug output remain unchanged.
    """

    model_adapter = _resolve_model_adapter(settings, model_adapter)
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

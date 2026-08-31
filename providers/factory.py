# providers/factory.py

"""Provider selection and provider-specific runtime choices."""

from __future__ import annotations

from config.settings import DEFAULT_BASE_URL, Settings
from providers.openai_compatible import OpenAICompatibleProvider
from providers.ollama import OllamaProvider


def build_provider(settings: Settings, debug: bool | None = None):
    provider_debug = settings.display.debug if debug is None else debug

    if settings.model.provider == "ollama":
        if settings.model.base_url == DEFAULT_BASE_URL:
            return OllamaProvider(temperature=settings.model.temperature)
        return OllamaProvider(
            base_url=settings.model.base_url,
            temperature=settings.model.temperature,
        )

    return OpenAICompatibleProvider(
        base_url=settings.model.base_url,
        api_key=settings.model.api_key,
        temperature=settings.model.temperature,
        debug=provider_debug,
        provider_name=settings.model.provider,
    )


def tool_call_content_mode(settings: Settings) -> str:
    if settings.model.provider == "openrouter":
        return "null"
    return "empty"

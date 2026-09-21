"""First-party provider transports and simple settings-based construction."""

from squid_core.providers.base import BaseProvider
from squid_core.providers.ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_REQUEST_TIMEOUT,
    OllamaProvider,
)
from squid_core.providers.openai_compatible import OpenAICompatibleProvider
from squid_core.settings import ProviderSettings


OPENAI_COMPATIBLE_PROVIDERS = frozenset(
    {"lm_studio", "openai_compatible", "openrouter", "squid_models"}
)


def build_provider(
    settings: ProviderSettings,
    *,
    for_inference: bool = True,
) -> BaseProvider:
    """Construct a built-in provider for inference or model discovery."""

    if settings.provider == "ollama":
        return OllamaProvider(
            base_url=settings.base_url or DEFAULT_OLLAMA_BASE_URL,
            temperature=settings.temperature,
            request_timeout=getattr(settings, "ollama_request_timeout", None),
        )

    if settings.provider in OPENAI_COMPATIBLE_PROVIDERS:
        if settings.base_url is None:
            raise ValueError(f"base_url is required for provider {settings.provider!r}")
        if not settings.api_key and (for_inference or settings.provider != "openrouter"):
            raise ValueError(f"api_key is required for provider {settings.provider!r}")
        return OpenAICompatibleProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            temperature=settings.temperature,
            reasoning_mode=settings.reasoning_mode,
            reasoning_token_budget=getattr(settings, "reasoning_token_budget", None),
            provider_name=settings.provider,
        )

    raise ValueError(f"Unsupported built-in provider: {settings.provider}")


def tool_call_content_mode(settings: ProviderSettings) -> str:
    """Return replay content behavior intrinsic to the selected backend."""

    return "null" if settings.provider == "openrouter" else "empty"


__all__ = [
    "BaseProvider",
    "DEFAULT_OLLAMA_REQUEST_TIMEOUT",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "build_provider",
    "tool_call_content_mode",
]

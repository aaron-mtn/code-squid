"""First-party provider transports and simple settings-based construction."""

from squid_core.providers.base import BaseProvider
from squid_core.providers.ollama import DEFAULT_OLLAMA_BASE_URL, OllamaProvider
from squid_core.providers.openai_compatible import OpenAICompatibleProvider
from squid_core.settings import ProviderSettings


OPENAI_COMPATIBLE_PROVIDERS = frozenset(
    {"lm_studio", "openai_compatible", "openrouter", "squid_models"}
)


def build_provider(settings: ProviderSettings) -> BaseProvider:
    """Construct one of Core's built-in providers from effective settings."""

    if settings.provider == "ollama":
        return OllamaProvider(
            base_url=settings.base_url or DEFAULT_OLLAMA_BASE_URL,
            temperature=settings.temperature,
        )

    if settings.provider in OPENAI_COMPATIBLE_PROVIDERS:
        if settings.base_url is None:
            raise ValueError(f"base_url is required for provider {settings.provider!r}")
        if settings.api_key is None:
            raise ValueError(f"api_key is required for provider {settings.provider!r}")
        return OpenAICompatibleProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            temperature=settings.temperature,
            provider_name=settings.provider,
        )

    raise ValueError(f"Unsupported built-in provider: {settings.provider}")


def tool_call_content_mode(settings: ProviderSettings) -> str:
    """Return replay content behavior intrinsic to the selected backend."""

    return "null" if settings.provider == "openrouter" else "empty"


__all__ = [
    "BaseProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "build_provider",
    "tool_call_content_mode",
]

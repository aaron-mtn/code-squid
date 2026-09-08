"""Provider/model setup integration tests across app settings and Core transports."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from code_squid.provider_setup import (
    PROVIDER_PROFILES,
    discover_models,
    friendly_provider_name,
    select_model,
    select_provider,
)
from code_squid.settings import load_settings
from squid_core.model_adapter import ModelAdapter
from squid_core.providers import build_provider
from squid_core.providers.ollama import OllamaProvider
from squid_core.providers.openai_compatible import OpenAICompatibleProvider


class JsonResponse:
    """Small urllib response used to exercise real request-building code."""

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_friendly_profiles_map_to_existing_transports() -> None:
    profiles = {profile.friendly_name: profile for profile in PROVIDER_PROFILES}
    assert list(profiles) == [
        "Squid Models",
        "LM Studio",
        "Ollama",
        "OpenRouter",
        "OpenAI Compatible",
    ]
    for friendly_name in ("Squid Models", "LM Studio", "OpenRouter", "OpenAI Compatible"):
        profile = profiles[friendly_name]
        provider = build_provider(
            SimpleNamespace(
                provider=profile.provider_id,
                model_name="selected-model",
                base_url=profile.base_url,
                api_key=profile.api_key or "test-key",
                temperature=None,
            )
        )
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.provider_name == profile.provider_id
    ollama = profiles["Ollama"]
    provider = build_provider(
        SimpleNamespace(
            provider=ollama.provider_id,
            model_name="selected-model",
            base_url=ollama.base_url,
            api_key=None,
            temperature=None,
        )
    )
    assert isinstance(provider, OllamaProvider)


def test_lm_studio_and_generic_defaults_are_distinct(tmp_path) -> None:
    profiles = {profile.provider_id: profile for profile in PROVIDER_PROFILES}
    assert profiles["lm_studio"].base_url == "http://127.0.0.1:1234/v1"
    assert profiles["openai_compatible"].base_url == "http://127.0.0.1:8000/v1"
    assert load_settings(tmp_path).model.provider == "lm_studio"


def test_lm_studio_native_discovery_and_loaded_readiness(monkeypatch) -> None:
    requests = []

    def urlopen(http_request, timeout):
        requests.append((http_request, timeout))
        return JsonResponse({
            "models": [
                {"type": "embedding", "key": "ignore"},
                {"type": "llm", "key": "model-a", "loaded_instances": [{}]},
                {"type": "llm", "key": "model-b", "loaded_instances": []},
            ]
        })

    monkeypatch.setattr("squid_core.providers.openai_compatible.request.urlopen", urlopen)
    provider = OpenAICompatibleProvider(
        "http://127.0.0.1:1234/v1", "lm-studio", provider_name="lm_studio"
    )
    assert provider.is_ready() is True
    assert provider.list_models() == ["model-a", "model-b"]
    assert all(item[0].full_url.endswith("/api/v1/models") for item in requests)


def test_squid_models_health_and_real_model_discovery(monkeypatch) -> None:
    requests = []

    def urlopen(http_request, timeout):
        requests.append(http_request)
        if http_request.full_url.endswith("/health"):
            return JsonResponse({"status": "ok"})
        return JsonResponse({"data": [{"id": "squid-a"}, {"id": "squid-b"}]})

    monkeypatch.setattr("squid_core.providers.openai_compatible.request.urlopen", urlopen)
    provider = OpenAICompatibleProvider(
        "http://127.0.0.1:8080/v1", "local", provider_name="squid_models"
    )
    assert provider.is_ready() is True
    assert provider.list_models() == ["squid-a", "squid-b"]
    assert [item.full_url for item in requests] == [
        "http://127.0.0.1:8080/health",
        "http://127.0.0.1:8080/v1/models",
    ]


def test_ollama_native_discovery(monkeypatch) -> None:
    requests = []

    def urlopen(http_request, timeout):
        requests.append(http_request)
        return JsonResponse({"models": [{"name": "qwen:latest"}, {"model": "gemma:2b"}]})

    monkeypatch.setattr("squid_core.providers.ollama.request.urlopen", urlopen)
    provider = OllamaProvider()
    assert provider.is_ready() is True
    assert provider.list_models() == ["qwen:latest", "gemma:2b"]
    assert all(item.full_url.endswith("/api/tags") for item in requests)


def test_openrouter_discovery_auth_and_env_key_reach_construction(monkeypatch, tmp_path) -> None:
    requests = []

    def urlopen(http_request, timeout):
        requests.append(http_request)
        return JsonResponse({"data": [{"id": "vendor/model"}]})

    monkeypatch.setenv("CODE_SQUID_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    monkeypatch.setattr("squid_core.providers.openai_compatible.request.urlopen", urlopen)
    settings = load_settings(tmp_path)
    provider = build_provider(settings.to_runtime_settings().provider)
    assert provider._api_key == "environment-secret"
    assert provider.list_models() == ["vendor/model"]
    assert requests[0].get_header("Authorization") == "Bearer environment-secret"


def test_openrouter_saved_key_is_used_when_default_env_is_absent(tmp_path) -> None:
    settings_dir = tmp_path / ".code-squid"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps({"model": {"provider": "openrouter", "api_key": "saved-secret"}}),
        encoding="utf-8",
    )
    provider = build_provider(load_settings(tmp_path).to_runtime_settings().provider)
    assert provider._api_key == "saved-secret"


class RecordingProvider:
    """Capture the model passed through ModelAdapter's inference boundary."""

    def __init__(self) -> None:
        self.models = []

    def create_response(self, *, model, messages, tools):
        self.models.append(model)
        message = SimpleNamespace(content="ok", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


@pytest.mark.parametrize("model_id", ["squid-model-a", "squid-model-b"])
def test_exact_squid_model_selection_reaches_inference(tmp_path, model_id) -> None:
    settings = select_model(tmp_path, model_id)
    runtime = settings.to_runtime_settings().provider
    provider = RecordingProvider()
    adapter = ModelAdapter(provider, runtime.model_name, provider_name="squid_models")
    adapter.respond([{"role": "user", "content": "hello"}], [])
    assert provider.models == [model_id]


def test_provider_selection_failure_keeps_active_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("code_squid.provider_setup.provider_ready", lambda _settings: False)
    # select_provider constructs directly, so make the candidate provider fail
    # through the same Core readiness method used in production.
    monkeypatch.setattr(
        "code_squid.provider_setup.build_provider",
        lambda _settings: SimpleNamespace(is_ready=lambda: False),
    )
    original = load_settings(tmp_path)
    settings, explanation = select_provider(tmp_path, "ollama")
    assert settings == original
    assert explanation == "Ollama is not connected."
    assert not (tmp_path / ".code-squid" / "settings.json").exists()


def test_discovery_uses_shared_provider_seam(monkeypatch, tmp_path) -> None:
    fake = SimpleNamespace(is_ready=lambda: True, list_models=lambda: ["z", "a", "a"])
    monkeypatch.setattr("code_squid.provider_setup.build_provider", lambda _settings: fake)
    assert discover_models(load_settings(tmp_path)) == ["a", "z"]
    assert friendly_provider_name("lm_studio") == "LM Studio"

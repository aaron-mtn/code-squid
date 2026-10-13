"""Provider/model setup integration tests across app settings and Core transports."""

from __future__ import annotations

import json
from squid_core.model_response import ModelResponse
from types import SimpleNamespace

import pytest

from code_squid.app_paths import settings_path
from code_squid.provider_setup import (
    PROVIDER_PROFILES,
    discover_models,
    friendly_provider_name,
    provider_ready,
    select_model,
    select_provider,
)
from code_squid.settings import load_settings
from squid_core.model_adapter import ModelAdapter
from squid_providers.catalog import build_provider
from squid_providers.openai_compatible import OpenAICompatibleProvider


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




def test_lm_studio_and_generic_defaults_are_distinct(tmp_path) -> None:
    profiles = {profile.provider_id: profile for profile in PROVIDER_PROFILES}
    assert profiles["lm_studio"].base_url == "http://127.0.0.1:1234/v1"
    assert profiles["openai_compatible"].base_url == "http://127.0.0.1:8000/v1"
    assert load_settings(tmp_path).model.provider == "lm_studio"








def test_openrouter_public_discovery_omits_auth_and_env_key_reaches_inference(
    monkeypatch,
    tmp_path,
) -> None:
    requests = []

    def urlopen(http_request, timeout):
        requests.append(http_request)
        return JsonResponse({"data": [{"id": "vendor/model"}]})

    monkeypatch.setenv("CODE_SQUID_PROVIDER", "openrouter")
    monkeypatch.setenv("CODE_SQUID_REASONING_MODE", "medium")
    monkeypatch.setenv("CODE_SQUID_REASONING_TOKEN_BUDGET", "4000")
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    monkeypatch.setattr("squid_providers.openai_compatible.request.urlopen", urlopen)
    settings = load_settings(tmp_path)
    provider = build_provider(settings.to_provider_settings())
    assert provider._api_key == "environment-secret"
    assert provider.reasoning_mode == "medium"
    assert provider.reasoning_token_budget == 4_000
    assert provider.list_models() == ["vendor/model"]
    assert requests[0].get_header("Authorization") is None


def test_openrouter_public_discovery_without_key_is_not_inference_ready(
    monkeypatch,
    tmp_path,
) -> None:
    requests = []

    def urlopen(http_request, timeout):
        requests.append(http_request)
        return JsonResponse({"data": [{"id": "vendor/public-model"}]})

    monkeypatch.setattr("squid_providers.openai_compatible.request.urlopen", urlopen)
    monkeypatch.setenv("CODE_SQUID_PROVIDER", "openrouter")
    monkeypatch.delenv("CODE_SQUID_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = OpenAICompatibleProvider(
        "https://openrouter.ai/api/v1",
        None,
        provider_name="openrouter",
    )

    assert provider.list_models() == ["vendor/public-model"]
    assert requests[0].get_header("Authorization") is None
    assert provider.is_ready() is False
    assert provider_ready(load_settings(tmp_path)) is False
    with pytest.raises(ValueError, match="api_key is required.*inference"):
        provider.create_response(model="vendor/public-model", messages=[], tools=[])




def test_openrouter_saved_key_is_used_when_default_env_is_absent(tmp_path) -> None:
    from code_squid.app_paths import code_squid_home
    settings_dir = code_squid_home()
    settings_dir.mkdir(exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"model": {"provider": "openrouter"}, "providers": {"openrouter": {"api_key": "saved-secret"}}}),
        encoding="utf-8",
    )
    provider = build_provider(load_settings(tmp_path).to_provider_settings())
    assert provider._api_key == "saved-secret"


class RecordingProvider:
    """Capture the model passed through ModelAdapter's inference boundary."""

    def __init__(self) -> None:
        self.models = []

    def create_response(self, *, model, messages, tools):
        self.models.append(model)
        return ModelResponse("ok")


@pytest.mark.parametrize("model_id", ["squid-model-a", "squid-model-b"])
def test_exact_squid_model_selection_reaches_inference(tmp_path, model_id) -> None:
    settings = select_model(tmp_path, model_id)
    runtime = settings.to_provider_settings()
    provider = RecordingProvider()
    adapter = ModelAdapter(provider, runtime.model_name, provider_name="squid_models")
    adapter.respond([{"role": "user", "content": "hello"}], [])
    assert provider.models == [model_id]


def test_disconnected_provider_selection_persists_for_configuration(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "squid_providers.catalog.build_provider",
        lambda _settings, **_kwargs: SimpleNamespace(is_ready=lambda: False),
    )
    settings, explanation = select_provider(tmp_path, "ollama")

    persisted = json.loads(settings_path().read_text(encoding="utf-8"))
    assert settings.model.provider == "ollama"
    assert persisted["model"]["provider"] == "ollama"
    assert explanation == "Ollama is not connected."


def test_disconnected_openrouter_selection_does_not_weaken_inference_checks(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("CODE_SQUID_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    settings, explanation = select_provider(tmp_path, "openrouter")

    assert settings.model.provider == "openrouter"
    assert explanation == "OpenRouter is not connected."
    with pytest.raises(ValueError, match="api_key is required"):
        build_provider(settings.to_provider_settings())


def test_readiness_and_discovery_delegate_to_public_provider_apis(monkeypatch, tmp_path) -> None:
    settings = load_settings(tmp_path)
    expected = settings.to_provider_settings()
    calls = []

    def ready(provider_settings):
        assert provider_settings == expected
        calls.append("ready")
        return False

    def discover(provider_settings):
        assert provider_settings == expected
        calls.append("discover")
        return ["a", "z"]

    monkeypatch.setattr("squid_providers.catalog.provider_ready", ready)
    monkeypatch.setattr("squid_providers.catalog.discover_models", discover)
    assert provider_ready(settings) is False
    assert discover_models(settings) == ["a", "z"]
    assert calls == ["ready", "discover"]
    assert friendly_provider_name("lm_studio") == "LM Studio"

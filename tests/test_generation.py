import inspect

import pytest

import squid_core.generation as generation
from squid_core.model_adapter import ModelRequestError
from squid_core.settings import CompactionSettings, ProviderSettings, RuntimeSettings


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeChoice(content)]
        self.usage = None


class FakeProvider:
    def __init__(self, content: str = "generated text") -> None:
        self.content = content
        self.requests = []

    def create_response(self, model: str, messages: list[dict], tools: list[dict]):
        self.requests.append({"model": model, "messages": messages, "tools": tools})
        return FakeResponse(self.content)


class StreamingProvider(FakeProvider):
    def __init__(self, content: str, deltas: list[str]) -> None:
        super().__init__(content)
        self.deltas = deltas

    def supports_streaming(self) -> bool:
        return True

    def stream_chat(self, model: str, messages: list[dict], tools: list[dict], on_text_delta):
        self.requests.append({"model": model, "messages": messages, "tools": tools})
        for delta in self.deltas:
            on_text_delta(delta)
        return FakeResponse(self.content)


class FailingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_response(self, model: str, messages: list[dict], tools: list[dict]):
        raise self.error


def settings(
    *,
    model_name: str = "generation-model",
    provider: str = "openai_compatible",
) -> RuntimeSettings:
    return RuntimeSettings(
        provider=ProviderSettings(
            provider=provider,
            model_name=model_name,
            base_url="http://127.0.0.1:1234/v1",
            api_key="test-key",
        ),
        approval_mode="never",
        max_tool_steps=None,
        stream_assistant_text=False,
        compaction=CompactionSettings(
            enabled=False,
            trigger_input_tokens=25_000,
            compact_fraction=0.8,
            min_recent_chunks=2,
        ),
    )


def test_string_input_becomes_user_message_and_request_uses_no_tools(monkeypatch) -> None:
    provider = FakeProvider("a short title")
    monkeypatch.setattr(generation, "build_provider", lambda supplied_settings: provider)

    text = generation.generate_text("Give me a title.", settings=settings())

    assert text == "a short title"
    assert provider.requests == [
        {
            "model": "generation-model",
            "messages": [{"role": "user", "content": "Give me a title."}],
            "tools": [],
        }
    ]


def test_reasoning_control_defaults_to_false() -> None:
    assert inspect.signature(generation.generate_text).parameters[
        "please_stop_contemplating_the_void"
    ].default is False
    assert inspect.signature(generation.stream_text).parameters[
        "please_stop_contemplating_the_void"
    ].default is False


def test_generate_text_forwards_requested_reasoning_control(monkeypatch) -> None:
    calls = []

    class CapturingAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def complete_text(self, messages, **options):
            calls.append((messages, options))
            return {"content": "done", "usage": None}

    monkeypatch.setattr(generation, "build_provider", lambda _settings: object())
    monkeypatch.setattr(generation, "ModelAdapter", CapturingAdapter)

    generation.generate_text(
        "Hello",
        settings=settings(),
        please_stop_contemplating_the_void=True,
    )

    assert calls[0][1] == {"please_stop_contemplating_the_void": True}


def test_message_list_is_passed_through_to_model_adapter(monkeypatch) -> None:
    messages = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hello"},
    ]
    calls = []

    class CapturingAdapter:
        def __init__(self, **kwargs) -> None:
            pass

        def complete_text(self, supplied_messages: list[dict]) -> dict:
            calls.append(supplied_messages)
            return {"content": "Hello!", "usage": None}

    monkeypatch.setattr(generation, "build_provider", lambda supplied_settings: object())
    monkeypatch.setattr(generation, "ModelAdapter", CapturingAdapter)

    assert generation.generate_text(messages, settings=settings()) == "Hello!"
    assert calls == [messages]
    assert calls[0] is messages


def test_supplied_settings_configure_provider_and_model_adapter(monkeypatch) -> None:
    supplied_settings = settings(model_name="custom-model", provider="openrouter")
    provider = object()
    provider_settings = []
    adapter_kwargs = []

    class CapturingAdapter:
        def __init__(self, **kwargs) -> None:
            adapter_kwargs.append(kwargs)

        def complete_text(self, messages: list[dict]) -> dict:
            return {"content": "done", "usage": None}

    monkeypatch.setattr(
        generation,
        "build_provider",
        lambda actual_settings: provider_settings.append(actual_settings) or provider,
    )
    monkeypatch.setattr(generation, "ModelAdapter", CapturingAdapter)

    generation.generate_text("Hello", settings=supplied_settings)

    assert provider_settings == [supplied_settings.provider]
    assert adapter_kwargs == [
        {
            "provider": provider,
            "model_name": "custom-model",
            "tool_call_content_mode": "null",
            "provider_name": "openrouter",
        }
    ]


def test_generation_requires_explicit_core_settings_or_adapter() -> None:
    with pytest.raises(ValueError, match="settings or model_adapter"):
        generation.generate_text("Hello")


def test_supplied_adapter_bypasses_settings_and_provider_construction(monkeypatch) -> None:
    class Adapter:
        def complete_text(self, messages, **_options):
            return {"content": messages[0]["content"], "usage": None}

    monkeypatch.setattr(
        generation,
        "build_provider",
        lambda _settings: (_ for _ in ()).throw(AssertionError("provider built")),
    )

    assert generation.generate_text("direct", model_adapter=Adapter()) == "direct"


def test_model_request_failure_preserves_model_request_error(monkeypatch) -> None:
    provider_error = RuntimeError("provider unavailable")
    monkeypatch.setattr(
        generation,
        "build_provider",
        lambda supplied_settings: FailingProvider(provider_error),
    )

    with pytest.raises(ModelRequestError) as exc_info:
        generation.generate_text("Hello", settings=settings())

    assert str(exc_info.value) == (
        "Model request failed: RuntimeError: provider unavailable"
    )
    assert exc_info.value.__cause__ is provider_error


def test_stream_text_converts_string_input_forwards_deltas_and_returns_content(monkeypatch) -> None:
    provider = StreamingProvider("a short title", ["a short ", "title"])
    monkeypatch.setattr(generation, "build_provider", lambda supplied_settings: provider)
    deltas = []

    text = generation.stream_text(
        "Give me a title.",
        deltas.append,
        settings=settings(),
    )

    assert text == "a short title"
    assert deltas == ["a short ", "title"]
    assert provider.requests == [
        {
            "model": "generation-model",
            "messages": [{"role": "user", "content": "Give me a title."}],
            "tools": [],
        }
    ]


def test_stream_text_forwards_requested_reasoning_control(monkeypatch) -> None:
    calls = []

    class CapturingAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def complete_text_streaming(self, messages, callback, **options):
            calls.append((messages, options))
            callback("done")
            return "done"

    monkeypatch.setattr(generation, "build_provider", lambda _settings: object())
    monkeypatch.setattr(generation, "ModelAdapter", CapturingAdapter)

    generation.stream_text(
        "Hello",
        lambda _delta: None,
        settings=settings(),
        please_stop_contemplating_the_void=True,
    )

    assert calls[0][1] == {"please_stop_contemplating_the_void": True}


def test_stream_text_passes_message_list_through_unchanged(monkeypatch) -> None:
    messages = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hello"},
    ]
    calls = []

    class CapturingAdapter:
        def __init__(self, **kwargs) -> None:
            pass

        def complete_text_streaming(self, supplied_messages, on_text_delta) -> str:
            calls.append(supplied_messages)
            on_text_delta("Hello!")
            return "Hello!"

    monkeypatch.setattr(generation, "build_provider", lambda supplied_settings: object())
    monkeypatch.setattr(generation, "ModelAdapter", CapturingAdapter)
    deltas = []

    assert generation.stream_text(messages, deltas.append, settings=settings()) == "Hello!"
    assert deltas == ["Hello!"]
    assert calls == [messages]
    assert calls[0] is messages


def test_stream_text_falls_back_when_provider_does_not_support_streaming(monkeypatch) -> None:
    provider = FakeProvider("completed response")
    monkeypatch.setattr(generation, "build_provider", lambda supplied_settings: provider)
    deltas = []

    text = generation.stream_text("Hello", deltas.append, settings=settings())

    assert text == "completed response"
    assert deltas == ["completed response"]


def test_stream_text_preserves_model_request_error_chaining(monkeypatch) -> None:
    provider_error = RuntimeError("provider unavailable")

    class FailingStreamingProvider:
        def supports_streaming(self) -> bool:
            return True

        def stream_chat(self, **kwargs):
            raise provider_error

    monkeypatch.setattr(
        generation,
        "build_provider",
        lambda supplied_settings: FailingStreamingProvider(),
    )

    with pytest.raises(ModelRequestError) as exc_info:
        generation.stream_text("Hello", lambda _delta: None, settings=settings())

    assert str(exc_info.value) == (
        "Model request failed: RuntimeError: provider unavailable"
    )
    assert exc_info.value.__cause__ is provider_error


def test_generation_module_has_no_agent_or_session_dependencies() -> None:
    assert "AgentLoop" not in generation.__dict__
    assert "CodingAgent" not in generation.__dict__
    assert "Session" not in generation.__dict__
    assert "ToolExecutor" not in generation.__dict__

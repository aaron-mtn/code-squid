import json

import pytest

from squid_core.model_adapter import ModelAdapter
from squid_core.providers import build_provider, tool_call_content_mode
from squid_core.providers.base import StreamCancelled
from squid_core.providers.ollama import OllamaProvider, adapt_response, convert_messages
from squid_core.providers.openai_compatible import OpenAICompatibleProvider
from squid_core.settings import ProviderSettings


class CapturingOllamaProvider(OllamaProvider):
    def __init__(self, temperature=None) -> None:
        super().__init__(temperature=temperature)
        self.payloads = []

    def _post_chat(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {"message": {"role": "assistant", "content": "Done."}}


class StreamingOllamaProvider(OllamaProvider):
    def __init__(self, chunks: list[dict]) -> None:
        super().__init__()
        self.chunks = chunks
        self.payloads = []

    def _post_chat_stream(self, payload: dict):
        self.payloads.append(payload)
        yield from self.chunks


class ClosableStream:
    """Small iterator double that records the provider cleanup contract."""

    def __init__(self, chunks: list[dict]) -> None:
        self._chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self) -> None:
        self.closed = True


class ClosableStreamingOllamaProvider(OllamaProvider):
    def __init__(self, stream: ClosableStream) -> None:
        super().__init__()
        self.stream = stream

    def _post_chat_stream(self, payload: dict):
        return self.stream


def test_stream_trace_reports_native_raw_thinking_and_summary() -> None:
    chunks = [
        {"id": "ollama_trace", "message": {"thinking": "thinking"}},
        {
            "message": {"content": "Ready."},
            "done": True,
            "done_reason": "stop",
        },
    ]
    provider = StreamingOllamaProvider(chunks)
    events = []

    provider.stream_chat(
        model="test-model",
        messages=[{"role": "user", "content": "prompt"}],
        tools=[],
        on_text_delta=lambda _delta: None,
        trace_callback=events.append,
    )

    assert [event["type"] for event in events] == [
        "request_start", "raw_chunk", "raw_chunk", "request_complete",
    ]
    assert events[1]["raw"] is chunks[0]
    assert events[1]["thinking_delta"] == "thinking"
    assert events[2]["content_delta"] == "Ready."
    assert events[-1]["response_id"] == "ollama_trace"
    assert events[-1]["finish_reason"] == "stop"
    assert events[-1]["first_raw_chunk_elapsed"] is not None
    assert events[-1]["first_reasoning_delta_elapsed"] is not None
    assert events[-1]["first_visible_content_delta_elapsed"] is not None
    assert events[-1]["total_reasoning_characters"] == len("thinking")
    assert events[-1]["total_visible_content_characters"] == len("Ready.")
    assert events[-1]["total_raw_chunk_count"] == 2


def test_assistant_tool_call_arguments_are_converted_to_dict() -> None:
    converted = convert_messages(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "/tmp/input.py"}',
                        },
                    }
                ],
            }
        ]
    )

    assert converted == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": "/tmp/input.py"},
                    },
                }
            ],
        }
    ]


def test_tool_result_uses_tool_name_from_previous_assistant_call() -> None:
    converted = convert_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "/tmp/input.py"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"ok": true}',
            },
        ]
    )

    assert converted[1] == {
        "role": "tool",
        "tool_name": "read_file",
        "content": '{"ok": true}',
    }


def test_unknown_tool_result_id_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="unknown tool_call_id: call_missing"):
        convert_messages(
            [
                {
                    "role": "tool",
                    "tool_call_id": "call_missing",
                    "content": "{}",
                }
            ]
        )


def test_native_response_with_content_adapts_to_openai_like_shape() -> None:
    response = adapt_response({"message": {"role": "assistant", "content": "Done."}})

    assert response.choices[0].message.content == "Done."
    assert response.choices[0].message.tool_calls == []


def test_native_response_preserves_available_thinking_finish_reason_and_id() -> None:
    response = adapt_response(
        {
            "id": "ollama_response_1",
            "message": {
                "role": "assistant",
                "content": "Done.",
                "thinking": "provider-exposed thinking",
            },
            "done_reason": "stop",
        }
    )

    assert response.id == "ollama_response_1"
    assert response.choices[0].finish_reason == "stop"
    assert response.choices[0].message.thinking == "provider-exposed thinking"
    assert not hasattr(response.choices[0].message, "reasoning")


def test_native_tool_calls_get_generated_ids_and_json_string_arguments() -> None:
    response = adapt_response(
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "read_file",
                            "arguments": {"path": "/tmp/input.py"},
                        }
                    }
                ],
            }
        }
    )

    tool_call = response.choices[0].message.tool_calls[0]

    assert tool_call.id == "ollama_call_0"
    assert tool_call.function.name == "read_file"
    assert json.loads(tool_call.function.arguments) == {"path": "/tmp/input.py"}


def test_temperature_none_omits_options_temperature_from_payload() -> None:
    provider = CapturingOllamaProvider(temperature=None)

    provider.create_response(model="test-model", messages=[], tools=[])

    payload = provider.payloads[0]
    assert "options" not in payload


def test_native_ollama_thinking_control_is_request_scoped() -> None:
    provider = CapturingOllamaProvider()

    provider.create_response(model="test-model", messages=[], tools=[])
    provider.create_response(
        model="test-model",
        messages=[],
        tools=[],
        please_stop_contemplating_the_void=True,
    )

    assert "think" not in provider.payloads[0]
    assert provider.payloads[1]["think"] is False


def test_native_ollama_streaming_thinking_control_is_request_scoped() -> None:
    provider = StreamingOllamaProvider([
        {"message": {"content": "Done."}, "done": True},
    ])

    provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[],
        on_text_delta=lambda _delta: None,
        please_stop_contemplating_the_void=True,
    )

    assert provider.payloads[0]["think"] is False


def test_zero_temperature_is_included_in_options_payload() -> None:
    provider = CapturingOllamaProvider(temperature=0)

    provider.create_response(model="test-model", messages=[], tools=[])

    assert provider.payloads[0]["options"]["temperature"] == 0


def test_native_ollama_payload_does_not_include_parallel_tool_calls() -> None:
    provider = CapturingOllamaProvider()

    provider.create_response(
        model="test-model",
        messages=[],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert "parallel_tool_calls" not in provider.payloads[0]


def test_native_ollama_streaming_accumulates_text_and_tool_calls_once() -> None:
    provider = StreamingOllamaProvider(
        [
            {"message": {"role": "assistant", "content": "I will "}, "done": False},
            {"message": {"role": "assistant", "content": "read the file."}, "done": False},
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "read_file",
                                "arguments": {"path": "/tmp/example.py"},
                            }
                        }
                    ],
                },
                "done": False,
            },
            {"done": True, "done_reason": "stop"},
        ]
    )
    adapter = ModelAdapter(provider, model_name="test-model")
    deltas = []
    preparing_events = []

    reply = adapter.respond_streaming(
        messages=[],
        tool_definitions=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ],
        on_text_delta=deltas.append,
        on_tool_preparing=preparing_events.append,
    )

    assert provider.payloads[0]["stream"] is True
    assert deltas == ["I will ", "read the file."]
    assert reply["message"]["content"] == "I will read the file."
    assert reply["actions"] == [
        {
            "tool": "read_file",
            "args": {"path": "/tmp/example.py"},
            "tool_call_id": "ollama_call_0",
            "raw_arguments": '{"path": "/tmp/example.py"}',
        }
    ]
    assert reply["message"]["tool_calls"] == [
        {
            "id": "ollama_call_0",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "/tmp/example.py"}',
            },
        }
    ]
    assert preparing_events == [{"tool": "read_file", "tool_call_index": 0}]


@pytest.mark.parametrize(
    "chunks",
    [
        [{"message": {"content": "partial"}, "done": False}],
        [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "read_file",
                                "arguments": {"path": "/tmp/incomplete"},
                            }
                        }
                    ]
                },
                "done": False,
            }
        ],
        [],
    ],
    ids=["partial-text", "partial-tool-call", "empty"],
)
def test_native_ollama_incomplete_stream_fails_and_closes(chunks) -> None:
    stream = ClosableStream(chunks)
    provider = ClosableStreamingOllamaProvider(stream)

    with pytest.raises(RuntimeError, match="ended before provider signaled completion"):
        provider.stream_chat(
            model="test-model",
            messages=[],
            tools=[],
            on_text_delta=lambda _delta: None,
        )

    assert stream.closed is True


def test_native_ollama_completed_stream_closes() -> None:
    stream = ClosableStream(
        [{"message": {"content": "complete"}, "done": True, "done_reason": "stop"}]
    )
    provider = ClosableStreamingOllamaProvider(stream)

    response = provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[],
        on_text_delta=lambda _delta: None,
    )

    assert response.choices[0].message.content == "complete"
    assert stream.closed is True


def test_native_ollama_stream_cancellation_remains_distinct_and_closes() -> None:
    stream = ClosableStream(
        [
            {"message": {"content": "first"}, "done": False},
            {"message": {"content": "second"}, "done": False},
        ]
    )
    provider = ClosableStreamingOllamaProvider(stream)
    cancelled = False

    def on_delta(_delta: str) -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(StreamCancelled):
        provider.stream_chat(
            model="test-model",
            messages=[],
            tools=[],
            on_text_delta=on_delta,
            should_cancel=lambda: cancelled,
        )

    assert stream.closed is True


def test_provider_selection_defaults_to_openai_compatible() -> None:
    settings = ProviderSettings(
        provider="openai_compatible",
        model_name="model",
        base_url="http://127.0.0.1:1234/v1",
        api_key="key",
    )

    provider = build_provider(settings)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.temperature is None


def test_openai_compatible_construction_requires_effective_api_key() -> None:
    settings = ProviderSettings(
        provider="openai_compatible",
        model_name="model",
        base_url="http://127.0.0.1:1234/v1",
        api_key=None,
    )

    with pytest.raises(ValueError, match="api_key"):
        build_provider(settings)


def test_provider_selection_uses_native_ollama_when_configured() -> None:
    settings = ProviderSettings(
        provider="ollama",
        model_name="model",
        base_url="http://127.0.0.1:11434/v1",
        api_key=None,
    )

    provider = build_provider(settings)

    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://127.0.0.1:11434"
    assert provider.temperature is None


def test_provider_selection_uses_native_ollama_default_base_url() -> None:
    settings = ProviderSettings(
        provider="ollama",
        model_name="model",
        base_url=None,
        api_key=None,
    )

    provider = build_provider(settings)

    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://127.0.0.1:11434"


def test_provider_selection_threads_temperature() -> None:
    settings = ProviderSettings(
        provider="openai_compatible",
        model_name="model",
        base_url="http://127.0.0.1:1234/v1",
        api_key="key",
        temperature=0,
    )

    provider = build_provider(settings)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.temperature == 0


def test_provider_selection_uses_openai_compatible_for_openrouter() -> None:
    settings = ProviderSettings(
        provider="openrouter",
        model_name="model",
        base_url="https://openrouter.ai/api/v1",
        api_key="key",
        temperature=0,
        reasoning_mode="medium",
    )

    provider = build_provider(settings)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.temperature == 0
    assert provider.reasoning_mode == "medium"
    assert provider.provider_name == "openrouter"


def test_provider_selection_preserves_managed_llama_cpp_identity() -> None:
    settings = ProviderSettings(
        provider="squid_models",
        model_name="model",
        base_url="http://127.0.0.1:1234/v1",
        api_key="key",
    )

    provider = build_provider(settings)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.provider_name == "squid_models"


def test_openrouter_uses_null_tool_call_content_mode() -> None:
    settings = ProviderSettings(
        provider="openrouter",
        model_name="model",
        base_url="https://openrouter.ai/api/v1",
        api_key="key",
    )

    assert tool_call_content_mode(settings) == "null"


def test_openai_compatible_preserves_default_tool_call_content_mode() -> None:
    settings = ProviderSettings(
        provider="openai_compatible",
        model_name="model",
        base_url="http://127.0.0.1:1234/v1",
        api_key="key",
    )

    assert tool_call_content_mode(settings) == "empty"


def test_provider_selection_threads_temperature_to_ollama() -> None:
    settings = ProviderSettings(
        provider="ollama",
        model_name="model",
        base_url=None,
        api_key=None,
        temperature=0,
    )

    provider = build_provider(settings)

    assert isinstance(provider, OllamaProvider)
    assert provider.temperature == 0

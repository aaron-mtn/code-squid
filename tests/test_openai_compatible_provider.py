from types import SimpleNamespace

import pytest

from squid_core.providers.openai_compatible import OpenAICompatibleProvider
from squid_core.providers.base import StreamCancelled


class FakeCompletions:
    def __init__(self) -> None:
        self.payloads = []
        self.response = object()

    def create(self, **payload):
        self.payloads.append(payload)
        return self.response


class FakeChat:
    def __init__(self) -> None:
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self) -> None:
        self.chat = FakeChat()


def provider_with_fake_client(
    temperature=None,
    reasoning_mode=None,
    reasoning_token_budget=None,
    provider_name: str = "openai_compatible",
) -> tuple[OpenAICompatibleProvider, FakeClient]:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.temperature = temperature
    provider.reasoning_mode = reasoning_mode
    provider.reasoning_token_budget = reasoning_token_budget
    provider.provider_name = provider_name
    provider.client = FakeClient()
    return provider, provider.client


def test_temperature_none_omits_temperature_from_payload() -> None:
    provider, client = provider_with_fake_client(temperature=None)

    provider.create_response(model="test-model", messages=[], tools=[])

    assert "temperature" not in client.chat.completions.payloads[0]


def test_zero_temperature_is_included_in_payload() -> None:
    provider, client = provider_with_fake_client(temperature=0)

    provider.create_response(model="test-model", messages=[], tools=[])

    assert client.chat.completions.payloads[0]["temperature"] == 0


def test_tools_present_disable_parallel_tool_calls() -> None:
    provider, client = provider_with_fake_client()

    provider.create_response(
        model="test-model",
        messages=[],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert client.chat.completions.payloads[0]["parallel_tool_calls"] is False


def test_no_tools_omits_parallel_tool_calls() -> None:
    provider, client = provider_with_fake_client()

    provider.create_response(model="test-model", messages=[], tools=[])

    assert "parallel_tool_calls" not in client.chat.completions.payloads[0]


def test_tool_choice_is_forwarded_when_supplied() -> None:
    provider, client = provider_with_fake_client()

    provider.create_response(
        model="test-model",
        messages=[],
        tools=[],
        tool_choice={"type": "function", "function": {"name": "read_file"}},
    )

    assert client.chat.completions.payloads[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "read_file"},
    }


def test_generic_openai_compatible_omits_speculative_reasoning_fields() -> None:
    provider, client = provider_with_fake_client(provider_name="openai_compatible")

    provider.create_response(
        model="test-model",
        messages=[],
        tools=[],
        please_stop_contemplating_the_void=True,
    )

    payload = client.chat.completions.payloads[0]
    assert "extra_body" not in payload
    assert "reasoning" not in payload
    assert "chat_template_kwargs" not in payload


def test_managed_llama_cpp_disables_thinking_when_requested() -> None:
    provider, client = provider_with_fake_client(
        provider_name="squid_models",
        reasoning_token_budget=4_000,
    )

    provider.create_response(
        model="test-model",
        messages=[],
        tools=[],
        please_stop_contemplating_the_void=True,
    )

    assert client.chat.completions.payloads[0]["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_openrouter_disables_optional_reasoning_when_requested() -> None:
    provider, client = provider_with_fake_client(provider_name="openrouter")

    provider.create_response(
        model="test-model",
        messages=[],
        tools=[],
        please_stop_contemplating_the_void=True,
    )

    assert client.chat.completions.payloads[0]["extra_body"] == {
        "reasoning": {"effort": "none"},
    }


def test_reasoning_controls_are_omitted_by_default() -> None:
    for provider_name in ("squid_models", "openrouter"):
        provider, client = provider_with_fake_client(provider_name=provider_name)
        provider.create_response(model="test-model", messages=[], tools=[])
        assert "extra_body" not in client.chat.completions.payloads[0]


def test_openrouter_translates_normalized_reasoning_modes() -> None:
    expected_efforts = {
        "off": "none",
        "low": "low",
        "medium": "medium",
        "high": "high",
    }
    for reasoning_mode, effort in expected_efforts.items():
        provider, client = provider_with_fake_client(
            provider_name="openrouter",
            reasoning_mode=reasoning_mode,
        )

        provider.create_response(model="test-model", messages=[], tools=[])

        assert client.chat.completions.payloads[0]["extra_body"] == {
            "reasoning": {"effort": effort},
        }


def test_openrouter_uses_separate_reasoning_token_budget() -> None:
    provider, client = provider_with_fake_client(
        provider_name="openrouter",
        reasoning_token_budget=4_000,
    )

    provider.create_response(model="test-model", messages=[], tools=[])

    payload = client.chat.completions.payloads[0]
    assert payload["extra_body"] == {"reasoning": {"max_tokens": 4_000}}
    assert "max_tokens" not in payload
    assert "max_output_tokens" not in payload


def test_openrouter_explicit_budget_takes_precedence_over_reasoning_mode() -> None:
    provider, client = provider_with_fake_client(
        provider_name="openrouter",
        reasoning_mode="low",
        reasoning_token_budget=4_000,
    )

    provider.create_response(model="test-model", messages=[], tools=[])

    assert client.chat.completions.payloads[0]["extra_body"] == {
        "reasoning": {"max_tokens": 4_000},
    }


def test_openrouter_does_not_send_undocumented_zero_reasoning_budget() -> None:
    provider, client = provider_with_fake_client(
        provider_name="openrouter",
        reasoning_token_budget=0,
    )

    provider.create_response(model="test-model", messages=[], tools=[])

    assert "extra_body" not in client.chat.completions.payloads[0]


def test_openrouter_no_reasoning_override_takes_precedence_over_budget() -> None:
    provider, client = provider_with_fake_client(
        provider_name="openrouter",
        reasoning_mode="high",
        reasoning_token_budget=4_000,
    )

    provider.create_response(
        model="test-model",
        messages=[],
        tools=[],
        please_stop_contemplating_the_void=True,
    )

    assert client.chat.completions.payloads[0]["extra_body"] == {
        "reasoning": {"effort": "none"},
    }


def test_unsupported_providers_ignore_reasoning_token_budget() -> None:
    for provider_name in ("openai_compatible", "lm_studio", "squid_models"):
        provider, client = provider_with_fake_client(
            provider_name=provider_name,
            reasoning_token_budget=4_000,
        )

        provider.create_response(model="test-model", messages=[], tools=[])

        payload = client.chat.completions.payloads[0]
        assert "extra_body" not in payload
        assert "max_tokens" not in payload
        assert "max_output_tokens" not in payload


def test_generic_openai_compatible_ignores_normalized_reasoning_mode() -> None:
    provider, client = provider_with_fake_client(
        provider_name="openai_compatible",
        reasoning_mode="high",
    )

    provider.create_response(model="test-model", messages=[], tools=[])

    payload = client.chat.completions.payloads[0]
    assert "extra_body" not in payload
    assert "reasoning" not in payload


def test_transport_does_not_print_request_summary(capsys) -> None:
    provider, _client = provider_with_fake_client()

    provider.create_response(
        model="test-model",
        messages=[{"role": "user", "content": "secret task"}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert capsys.readouterr().out == ""


def chunk(content=None, tool_calls=None, *, reasoning_content=None, finish_reason=None, id=None):
    delta = SimpleNamespace(content=content)
    if tool_calls is not None:
        delta.tool_calls = tool_calls
    if reasoning_content is not None:
        delta.reasoning_content = reasoning_content
    return SimpleNamespace(
        id=id,
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
    )


def tool_call_delta(index, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class ClosableStream:
    """Small iterator double that records the provider cleanup contract."""

    def __init__(self, chunks) -> None:
        self.closed = False
        self.chunks = iter(chunks)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.chunks)

    def close(self) -> None:
        self.closed = True


def test_stream_chat_requests_stream_true_and_assembles_text() -> None:
    provider, client = provider_with_fake_client()
    client.chat.completions.response = [
        chunk(content="hello "),
        chunk(content="world", finish_reason="stop"),
    ]
    deltas = []

    response = provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[],
        on_text_delta=deltas.append,
    )

    assert client.chat.completions.payloads[0]["stream"] is True
    assert deltas == ["hello ", "world"]
    assert response.choices[0].message.content == "hello world"
    assert response.choices[0].message.tool_calls == []


def test_stream_cancellation_stops_consumption_and_closes_response() -> None:
    provider, client = provider_with_fake_client()
    stream = ClosableStream([chunk(content="first"), chunk(content="second")])
    client.chat.completions.response = stream
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


def test_stream_chat_preserves_exposed_reasoning_finish_reason_and_response_id() -> None:
    provider, client = provider_with_fake_client()
    client.chat.completions.response = [
        chunk(reasoning_content="first ", id="chatcmpl_123"),
        chunk(reasoning_content="second", finish_reason="stop"),
    ]

    response = provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[],
        on_text_delta=lambda _delta: None,
    )

    assert response.id == "chatcmpl_123"
    assert response.choices[0].finish_reason == "stop"
    assert response.choices[0].message.reasoning_content == "first second"
    assert not hasattr(response.choices[0].message, "reasoning")


def test_stream_trace_reports_raw_reasoning_before_visible_content() -> None:
    provider, client = provider_with_fake_client()
    client.chat.completions.response = [
        chunk(reasoning_content="thinking", id="chatcmpl_trace"),
        chunk(content="Ready.", finish_reason="stop"),
    ]
    events = []
    deltas = []

    provider.stream_chat(
        model="test-model",
        messages=[{"role": "user", "content": "prompt"}],
        tools=[],
        on_text_delta=deltas.append,
        trace_callback=events.append,
    )

    assert [event["type"] for event in events] == [
        "request_start", "raw_chunk", "raw_chunk", "request_complete",
    ]
    assert events[0]["payload"] == client.chat.completions.payloads[0]
    assert events[1]["raw"] is client.chat.completions.response[0]
    assert events[1]["reasoning_content_delta"] == "thinking"
    assert events[1]["content_delta"] == ""
    assert events[2]["content_delta"] == "Ready."
    assert deltas == ["Ready."]
    assert events[-1]["response_id"] == "chatcmpl_trace"
    assert events[-1]["first_raw_chunk_elapsed"] is not None
    assert events[-1]["first_reasoning_delta_elapsed"] is not None
    assert events[-1]["first_visible_content_delta_elapsed"] is not None
    assert events[-1]["total_reasoning_characters"] == len("thinking")
    assert events[-1]["total_visible_content_characters"] == len("Ready.")
    assert events[-1]["total_raw_chunk_count"] == 2


def test_stream_chat_assembles_tool_call_fragments() -> None:
    provider, client = provider_with_fake_client()
    client.chat.completions.response = [
        chunk(content="Reading file."),
        chunk(
            tool_calls=[
                tool_call_delta(
                    0,
                    id="call_1",
                    name="read_",
                    arguments='{"path": ',
                )
            ]
        ),
        chunk(
            tool_calls=[
                tool_call_delta(
                    0,
                    name="file",
                    arguments='"/tmp/a.txt"}',
                )
            ]
        ),
        chunk(finish_reason="tool_calls"),
    ]
    deltas = []

    response = provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
        on_text_delta=deltas.append,
    )

    tool_call = response.choices[0].message.tool_calls[0]
    assert deltas == ["Reading file."]
    assert response.choices[0].message.content == "Reading file."
    assert tool_call.id == "call_1"
    assert tool_call.function.name == "read_file"
    assert tool_call.function.arguments == '{"path": "/tmp/a.txt"}'


def test_stream_chat_notifies_tool_preparing_once_when_name_appears() -> None:
    provider, client = provider_with_fake_client()
    client.chat.completions.response = [
        chunk(
            tool_calls=[
                tool_call_delta(
                    0,
                    id="call_1",
                    name="read_file",
                    arguments='{"path": ',
                )
            ]
        ),
        chunk(
            tool_calls=[
                tool_call_delta(
                    0,
                    arguments='"/tmp/a.txt"}',
                )
            ]
        ),
        chunk(finish_reason="tool_calls"),
    ]
    preparing_events = []

    provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
        on_text_delta=lambda _delta: None,
        on_tool_preparing=preparing_events.append,
    )

    assert preparing_events == [
        {
            "tool": "read_file",
            "tool_call_index": 0,
            "tool_call_id": "call_1",
        }
    ]


def test_stream_chat_tool_preparing_does_not_include_arguments() -> None:
    provider, client = provider_with_fake_client()
    client.chat.completions.response = [
        chunk(
            tool_calls=[
                tool_call_delta(
                    0,
                    id="call_1",
                    name="write_file",
                    arguments='{"path": "/tmp/a.txt", "content": "secret"}',
                )
            ]
        ),
        chunk(finish_reason="tool_calls"),
    ]
    preparing_events = []

    provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[{"type": "function", "function": {"name": "write_file"}}],
        on_text_delta=lambda _delta: None,
        on_tool_preparing=preparing_events.append,
    )

    assert preparing_events == [
        {
            "tool": "write_file",
            "tool_call_index": 0,
            "tool_call_id": "call_1",
        }
    ]
    assert "arguments" not in preparing_events[0]
    assert "args" not in preparing_events[0]


@pytest.mark.parametrize(
    "chunks",
    [
        [chunk(content="partial")],
        [
            chunk(
                tool_calls=[
                    tool_call_delta(
                        0,
                        id="call_1",
                        name="read_file",
                        arguments='{"path": ',
                    )
                ]
            )
        ],
        [],
    ],
    ids=["partial-text", "partial-tool-call", "empty"],
)
def test_openai_compatible_incomplete_stream_fails_and_closes(chunks) -> None:
    provider, client = provider_with_fake_client()
    stream = ClosableStream(chunks)
    client.chat.completions.response = stream

    with pytest.raises(RuntimeError, match="ended before provider signaled completion"):
        provider.stream_chat(
            model="test-model",
            messages=[],
            tools=[],
            on_text_delta=lambda _delta: None,
        )

    assert stream.closed is True


def test_openai_compatible_completed_stream_closes() -> None:
    provider, client = provider_with_fake_client()
    stream = ClosableStream([chunk(content="complete", finish_reason="stop")])
    client.chat.completions.response = stream

    response = provider.stream_chat(
        model="test-model",
        messages=[],
        tools=[],
        on_text_delta=lambda _delta: None,
    )

    assert response.choices[0].message.content == "complete"
    assert stream.closed is True

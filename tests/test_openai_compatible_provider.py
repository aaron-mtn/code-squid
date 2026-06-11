from types import SimpleNamespace

from providers.openai_compatible import OpenAICompatibleProvider


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
    debug: bool = False,
) -> tuple[OpenAICompatibleProvider, FakeClient]:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.temperature = temperature
    provider.debug = debug
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


def test_debug_off_does_not_print_request_summary(capsys) -> None:
    provider, _client = provider_with_fake_client(debug=False)

    provider.create_response(
        model="test-model",
        messages=[{"role": "user", "content": "secret task"}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert capsys.readouterr().out == ""


def test_debug_on_prints_parallel_tool_calls_false_without_message_contents(capsys) -> None:
    provider, _client = provider_with_fake_client(debug=True)

    provider.create_response(
        model="test-model",
        messages=[
            {"role": "system"},
            {"role": "user", "content": "secret task"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]},
            {"role": "tool", "content": ""},
        ],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    output = capsys.readouterr().out
    assert "┌─ provider request " in output
    assert "│ provider: openai-compatible" in output
    assert "│ model: test-model" in output
    assert "│ messages: 4" in output
    assert "│ tools: 1" in output
    assert "│ temperature: <missing>" in output
    assert "│ stream: <missing>" in output
    assert "│ parallel_tool_calls: false" in output
    assert "│ tool_choice: <missing>" in output
    assert "secret task" not in output


def chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content)
    if tool_calls is not None:
        delta.tool_calls = tool_calls
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def tool_call_delta(index, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_stream_chat_requests_stream_true_and_assembles_text() -> None:
    provider, client = provider_with_fake_client()
    client.chat.completions.response = [
        chunk(content="hello "),
        chunk(content="world"),
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

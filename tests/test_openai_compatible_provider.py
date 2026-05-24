from providers.openai_compatible import OpenAICompatibleProvider


class FakeCompletions:
    def __init__(self) -> None:
        self.payloads = []

    def create(self, **payload):
        self.payloads.append(payload)
        return object()


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
    assert "parallel_tool_calls=False" in output
    assert "tools_count=1" in output
    assert "temperature=<missing>" in output
    assert "tool_choice=<missing>" in output
    assert "message_count=4" in output
    assert "'role': 'user'" in output
    assert "'content': 'non-empty'" in output
    assert "'content': 'None'" in output
    assert "'content': 'empty'" in output
    assert "'tool_calls': 1" in output
    assert "secret task" not in output

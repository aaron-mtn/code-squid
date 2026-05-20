import pytest

from core.model_adapter import ModelAdapter, ModelRequestError


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content: str | None, tool_calls: list[FakeToolCall] | None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message


class FakeResponse:
    def __init__(self, message: FakeMessage) -> None:
        self.choices = [FakeChoice(message)]


class FakeProvider:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests = []

    def create_response(self, model: str, messages: list[dict], tools: list[dict]) -> FakeResponse:
        self.requests.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
            }
        )
        return self.response


class FailingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_response(self, model: str, messages: list[dict], tools: list[dict]) -> FakeResponse:
        raise self.error


def tool_definition(name: str, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": required,
            },
        },
    }


def adapter_response(
    tool_call: FakeToolCall,
    tool_definitions: list[dict],
    content: str | None = None,
) -> dict:
    provider = FakeProvider(FakeResponse(FakeMessage(content=content, tool_calls=[tool_call])))
    adapter = ModelAdapter(provider=provider, model_name="test-model")

    return adapter.respond(messages=[{"role": "user", "content": "hi"}], tool_definitions=tool_definitions)


def test_valid_tool_call_succeeds_when_tool_is_passed_in_definitions() -> None:
    reply = adapter_response(
        FakeToolCall("call_1", "local_tool", '{"path": "/tmp/input.txt"}'),
        [tool_definition("local_tool", ["path"])],
    )

    assert reply["format_error"] == ""
    assert reply["message"]["content"] == ""
    assert reply["actions"] == [
        {
            "tool": "local_tool",
            "args": {"path": "/tmp/input.txt"},
            "tool_call_id": "call_1",
            "raw_arguments": '{"path": "/tmp/input.txt"}',
        }
    ]


def test_tool_only_reply_does_not_get_fallback_narration() -> None:
    reply = adapter_response(
        FakeToolCall("call_1", "read_file", '{"path": "/tmp/input.txt"}'),
        [tool_definition("read_file", ["path"])],
    )

    assert reply["format_error"] == ""
    assert reply["message"]["content"] == ""
    assert reply["message"]["content"] != "Using read_file."


def test_provider_narration_is_preserved_with_tool_call() -> None:
    reply = adapter_response(
        FakeToolCall("call_1", "local_tool", '{"path": "/tmp/input.txt"}'),
        [tool_definition("local_tool", ["path"])],
        content="I need to inspect the input file first.",
    )

    assert reply["format_error"] == ""
    assert reply["message"]["content"] == "I need to inspect the input file first."


def test_unknown_tool_call_is_rejected_when_not_passed_in_definitions() -> None:
    reply = adapter_response(
        FakeToolCall("call_1", "missing_tool", "{}"),
        [tool_definition("local_tool", [])],
    )

    assert reply["actions"] == []
    assert reply["format_error"] == "Unknown tool: missing_tool"


def test_global_registry_tool_is_rejected_when_not_passed_in_definitions() -> None:
    reply = adapter_response(
        FakeToolCall("call_1", "read_file", '{"path": "/tmp/input.txt"}'),
        [tool_definition("local_tool", [])],
    )

    assert reply["actions"] == []
    assert reply["format_error"] == "Unknown tool: read_file"


def test_missing_required_args_are_rejected_from_passed_definitions() -> None:
    reply = adapter_response(
        FakeToolCall("call_1", "local_tool", '{"path": "/tmp/output.txt"}'),
        [tool_definition("local_tool", ["path", "content"])],
    )

    assert reply["actions"] == []
    assert reply["format_error"] == "Missing required arguments for local_tool: content"


def test_assistant_tool_calls_metadata_is_preserved_on_normalized_message() -> None:
    reply = adapter_response(
        FakeToolCall("call_1", "local_tool", '{"path": "/tmp/input.txt"}'),
        [tool_definition("local_tool", ["path"])],
    )

    assert reply["message"]["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "local_tool",
                "arguments": '{"path": "/tmp/input.txt"}',
            },
        }
    ]


def test_provider_exception_is_wrapped_as_model_request_error() -> None:
    provider_error = RuntimeError("provider unavailable")
    adapter = ModelAdapter(provider=FailingProvider(provider_error), model_name="test-model")

    with pytest.raises(ModelRequestError) as exc_info:
        adapter.respond(messages=[{"role": "user", "content": "hi"}], tool_definitions=[])

    assert str(exc_info.value) == "Model request failed"
    assert exc_info.value.__cause__ is provider_error

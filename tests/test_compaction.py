import inspect
from types import SimpleNamespace

import pytest

import core.compaction as compaction_module
from core.compaction import Compactor


class FakeModelAdapter:
    def __init__(self, content: str = "Earlier context summary.") -> None:
        self.content = content
        self.requests = []

    def complete_text(self, messages: list[dict]) -> dict:
        self.requests.append(messages)
        return {"content": self.content, "usage": None}


class FailingModelAdapter:
    def complete_text(self, messages: list[dict]) -> dict:
        raise RuntimeError("summary failed")


def settings(
    enabled: bool = True,
    trigger_input_tokens: int = 1,
    keep_recent_turns: int = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=enabled,
        trigger_input_tokens=trigger_input_tokens,
        keep_recent_turns=keep_recent_turns,
    )


def session(messages: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(messages=messages)


def long_message(role: str, content: str) -> dict:
    return {"role": role, "content": content * 80}


def compactable_messages() -> list[dict]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "original task"},
        long_message("assistant", "read a "),
        long_message("tool", "file result "),
        long_message("assistant", "changed a "),
        long_message("user", "please continue "),
    ]


def test_disabled_compaction_returns_none_and_does_not_mutate_messages() -> None:
    messages = compactable_messages()
    original_messages = list(messages)
    current_session = session(messages)
    compactor = Compactor(settings(enabled=False), FakeModelAdapter())

    result = compactor.maybe_compact(current_session)

    assert result is None
    assert current_session.messages == original_messages


def test_below_threshold_returns_none_and_does_not_mutate_messages() -> None:
    messages = compactable_messages()
    original_messages = list(messages)
    current_session = session(messages)
    compactor = Compactor(settings(trigger_input_tokens=100_000), FakeModelAdapter())

    result = compactor.maybe_compact(current_session)

    assert result is None
    assert current_session.messages == original_messages


def test_above_threshold_replaces_older_chunks_with_one_compacted_context_message() -> None:
    current_session = session(compactable_messages())
    compactor = Compactor(settings(keep_recent_turns=2), FakeModelAdapter("summary text"))

    result = compactor.maybe_compact(current_session)

    assert result is not None
    compacted_message = current_session.messages[2]
    assert compacted_message["role"] == "user"
    assert compacted_message["content"].startswith("# Compacted Prior Context")
    assert "summary text" in compacted_message["content"]
    assert len(
        [
            message
            for message in current_session.messages
            if message["content"].startswith("# Compacted Prior Context")
        ]
    ) == 1


def test_initial_system_and_user_messages_are_preserved() -> None:
    messages = compactable_messages()
    current_session = session(messages)
    compactor = Compactor(settings(keep_recent_turns=2), FakeModelAdapter())

    compactor.maybe_compact(current_session)

    assert current_session.messages[:2] == messages[:2]


def test_recent_chunks_are_preserved() -> None:
    messages = compactable_messages()
    current_session = session(messages)
    compactor = Compactor(settings(keep_recent_turns=2), FakeModelAdapter())

    compactor.maybe_compact(current_session)

    assert current_session.messages[-2:] == messages[-2:]


def test_assistant_tool_call_and_following_tool_result_stay_together_when_kept_recent() -> None:
    tool_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
    }
    tool_result = {"role": "tool", "tool_call_id": "call_1", "content": "file contents"}
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "original task"},
        long_message("assistant", "older "),
        tool_call,
        tool_result,
    ]
    current_session = session(messages)
    compactor = Compactor(settings(keep_recent_turns=1), FakeModelAdapter())

    compactor.maybe_compact(current_session)

    assert current_session.messages[-2:] == [tool_call, tool_result]


def test_complete_text_failure_does_not_mutate_session_messages() -> None:
    messages = compactable_messages()
    original_messages = list(messages)
    current_session = session(messages)
    compactor = Compactor(settings(keep_recent_turns=2), FailingModelAdapter())

    with pytest.raises(RuntimeError, match="summary failed"):
        compactor.maybe_compact(current_session)

    assert current_session.messages == original_messages


def test_returned_metadata_includes_token_message_counts_and_summary_chars() -> None:
    current_session = session(compactable_messages())
    compactor = Compactor(settings(keep_recent_turns=2), FakeModelAdapter("summary text"))

    result = compactor.maybe_compact(current_session)

    assert result is not None
    assert result["estimated_tokens_before"] > 0
    assert result["estimated_tokens_after"] > 0
    assert result["messages_before"] == 6
    assert result["messages_after"] == len(current_session.messages)
    assert result["summary_chars"] == len("summary text")


def test_summary_request_uses_compaction_prompt_with_json_context() -> None:
    model_adapter = FakeModelAdapter()
    current_session = session(compactable_messages())
    compactor = Compactor(settings(keep_recent_turns=2), model_adapter)

    compactor.maybe_compact(current_session)

    assert model_adapter.requests[0][0] == {
        "role": "system",
        "content": "You summarize prior agent interaction context for safe continuation.",
    }
    assert model_adapter.requests[0][1]["role"] == "user"
    assert "Prior context:" in model_adapter.requests[0][1]["content"]


def test_compaction_does_not_import_code_squid_application_prompts() -> None:
    source = inspect.getsource(compaction_module)

    assert "agent.prompts" not in source
    assert "squid_core.compaction.prompts" in source


def test_generic_prompt_carries_task_tool_verification_and_failure_context() -> None:
    model_adapter = FakeModelAdapter("continuation summary")
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "original research task"},
        long_message("assistant", "important finding in resource.txt "),
        long_message("tool", "command failed, corrected invocation "),
        long_message("assistant", "verification passed; next inspect remaining risk "),
        long_message("user", "retain this recent request "),
    ]
    current_session = session(messages)

    Compactor(settings(keep_recent_turns=1), model_adapter).maybe_compact(
        current_session
    )

    prompt = model_adapter.requests[0][1]["content"]
    assert "important finding in resource.txt" in prompt
    assert "command failed, corrected invocation" in prompt
    assert "verification passed; next inspect remaining risk" in prompt
    assert "tool and command results" in prompt
    assert "failed attempts and corrections" in prompt
    assert current_session.messages[:2] == messages[:2]

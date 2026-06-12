from agent.coding import CodingAgent
from core.session import Session


def test_validate_reply_accepts_no_tool_normal_answer_as_final() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "The answer is already available from the transcript.",
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_accepts_coding_summary_without_task_complete_as_final() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": (
                "## Files changed\n"
                "- `a.py`\n"
                "\n"
                "## What changed\n"
                "- Fixed the bug.\n"
                "\n"
                "## Verification\n"
                "- `pytest`\n"
                "\n"
                "## Remaining risks / notes\n"
                "- No known remaining risks; pytest passed."
            ),
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_rejects_empty_no_tool_reply() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "   \n",
        },
        "actions": [],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": False,
        "reason": "empty_final_reply",
    }


def test_validate_reply_accepts_exactly_one_tool_call_as_tool_turn() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "I need to inspect a.py before editing.",
        },
        "actions": [
            {
                "tool": "read_file",
                "args": {"path": "a.py"},
                "tool_call_id": "call_1",
            }
        ],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_accepts_one_tool_call_with_blank_content() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "   \n",
        },
        "actions": [
            {
                "tool": "read_file",
                "args": {"path": "a.py"},
                "tool_call_id": "call_1",
            }
        ],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": True,
        "reason": "",
    }


def test_validate_reply_rejects_more_than_one_tool_call() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "I need to inspect both files.",
        },
        "actions": [
            {
                "tool": "read_file",
                "args": {"path": "a.py"},
                "tool_call_id": "call_1",
            },
            {
                "tool": "read_file",
                "args": {"path": "b.py"},
                "tool_call_id": "call_2",
            },
        ],
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": False,
        "reason": "non_final_too_many_tool_calls",
    }


def test_validate_reply_rejects_malformed_tool_call() -> None:
    agent = CodingAgent("demo task")
    reply = {
        "message": {
            "content": "I need to inspect a.py.",
        },
        "actions": [],
        "format_error": "Unknown tool: missing_tool",
    }

    validation = agent.validate_reply(reply)

    assert validation == {
        "ok": False,
        "reason": "malformed_tool_call",
    }


def test_should_stop_returns_true_for_latest_assistant_no_tool_non_empty_message() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "Done. Verification passed.",
        }
    ]

    assert agent.should_stop(session) is True


def test_should_stop_returns_false_if_latest_assistant_has_tool_calls() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "I am reading a.py next.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        }
    ]

    assert agent.should_stop(session) is False


def test_should_stop_returns_false_after_newer_user_message() -> None:
    agent = CodingAgent("demo task")
    session = Session(repo_root=None)
    session.messages = [
        {
            "role": "assistant",
            "content": "Done. Verification passed.",
        },
        {
            "role": "user",
            "content": "Continue this saved session with this follow-up task: more",
        },
    ]

    assert agent.should_stop(session) is False


def test_failure_message_for_invalid_replies_includes_reason_and_explanation() -> None:
    agent = CodingAgent("demo task")

    message = agent.failure_message_for_invalid_replies(
        "empty_final_reply",
        3,
    )

    assert message == {
        "role": "assistant",
        "content": (
            "Code Squid stopped after 3 consecutive invalid replies.\n"
            "Last invalid reply reason: empty_final_reply\n"
            "Explanation: the model replied with no tool call and no final content"
        ),
    }


def test_tool_definition_exposes_apply_patch_through_coding_agent() -> None:
    agent = CodingAgent("demo task")

    names = [
        definition["function"]["name"]
        for definition in agent.tool_definitions()
    ]

    assert names == ["read_file", "write_file", "apply_patch", "run_command"]


def test_empty_final_correction_mentions_final_content() -> None:
    agent = CodingAgent("demo task")

    message = agent.correction_message_for("empty_final_reply")

    assert "no tool call and no final content" in message["content"]
    assert "TASK COMPLETE" not in message["content"]


def test_follow_up_message_returns_user_message() -> None:
    agent = CodingAgent("original task")

    message = agent.follow_up_message("show me what changed")

    assert message["role"] == "user"
    assert "show me what changed" in message["content"]
    assert "existing transcript" in message["content"]
    assert "without running extra commands" in message["content"]
    assert "do not use write_file" in message["content"]


def test_initial_prompts_encourage_compact_markdown_narration() -> None:
    messages = CodingAgent(task="Update the UI").initial_messages()
    combined_prompt = "\n".join(message["content"] for message in messages)

    assert "Write visible action notes in concise lightweight Markdown." in combined_prompt
    assert "keep narration to 2-4 sentences" in combined_prompt
    assert "Use inline code for file names, paths, commands" in combined_prompt
    assert "Do not use `#` headings" in combined_prompt


def test_initial_prompts_keep_markdown_final_summary_guidance() -> None:
    messages = CodingAgent(task="Update the UI").initial_messages()
    combined_prompt = "\n".join(message["content"] for message in messages)

    assert "write the final summary in simple Markdown" in combined_prompt
    assert "Prefer short Markdown headings" in combined_prompt
    assert "Use bullets when they make the summary easier to scan." in combined_prompt
    assert "Use backticks for paths, commands, code symbols" in combined_prompt

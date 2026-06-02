# agent/coding.py

from agent.prompts import SYSTEM_PROMPT, correction_message, follow_up_prompt, task_prompt
from tools import TOOLS

INVALID_REPLY_EXPLANATIONS = {
    "empty_final_reply": "the model replied with no tool call and no final content",
    "non_final_wrong_tool_count": "the model used the wrong number of tool calls",
    "malformed_tool_call": "the model produced an invalid tool call payload",
}


class CodingAgent:
    """Owns coding-agent behavior, allowed tools, and completion rules; must not own low-level loop machinery, provider transport, or tool implementation."""

    # Store the task this coding agent is trying to solve.
    def __init__(self, task: str) -> None:
        self.task = task

    # Return the initial system and user messages for a new session.
    def initial_messages(self) -> list[dict]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt(self.task)},
        ]

    # Return the user message that continues an existing saved session.
    def follow_up_message(self, task: str) -> dict:
        return {"role": "user", "content": follow_up_prompt(task)}

    # Return the tool definitions available to this agent.
    def tool_definitions(self) -> list[dict]:
        return [tool["definition"]() for tool in TOOLS.values()]

    # Decide whether the loop should stop.
    # Look backward through the transcript for the most recent assistant message.
    # If that message has no tool calls and non-empty content, stop the loop.
    def should_stop(self, session) -> bool:
        for message in reversed(session.messages):
            if message["role"] == "user":
                return False

            if message["role"] != "assistant":
                continue

            return (
                not message.get("tool_calls")
                and bool(message.get("content", "").strip())
            )

        return False

    # Validate whether a normalized model reply counts as a real coding-agent turn.
    #
    # Valid reply shapes:
    # 1. A normal tool turn with exactly one tool action
    # 2. A final reply with non-empty content and no tool actions
    #
    # Invalid reply shapes:
    # 1. A reply that carried a format_error from the model adapter
    # 2. A reply with no tool action and empty content
    # 3. A reply with the wrong number of tool actions
    def validate_reply(self, reply: dict) -> dict:
        actions = reply["actions"]
        content = reply["message"]["content"].strip()
        format_error = reply.get("format_error", "").strip()

        # Reject malformed tool-call output from the model adapter before it
        # reaches the normal assistant-turn path.
        if format_error:
            return {
                "ok": False,
                "reason": "malformed_tool_call",
            }

        # No tool call means final answer, as long as the content is not empty.
        if len(actions) == 0:
            if content:
                return {
                    "ok": True,
                    "reason": "",
                }

            return {
                "ok": False,
                "reason": "empty_final_reply",
            }

        # Tool turns must include exactly one tool action.
        if len(actions) != 1:
            return {
                "ok": False,
                "reason": "non_final_wrong_tool_count",
            }

        return {
            "ok": True,
            "reason": "",
        }

    # Return a correction message for a specific invalid-reply reason.
    # This lets the coding agent keep correction policy close to its validation
    # rules, instead of hard-coding one generic reminder in the loop.
    def correction_message_for(self, reason: str) -> dict:
        return {
            "role": "user",
            "content": correction_message(reason),
        }

    def failure_message_for_invalid_replies(self, reason: str, count: int) -> dict:
        explanation = INVALID_REPLY_EXPLANATIONS.get(
            reason,
            "the model produced repeated invalid replies",
        )
        return {
            "role": "assistant",
            "content": (
                f"Code Squid stopped after {count} consecutive invalid replies.\n"
                f"Last invalid reply reason: {reason}\n"
                f"Explanation: {explanation}"
            ),
        }

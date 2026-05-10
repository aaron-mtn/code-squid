# agent/coding.py

from agent.prompts import SYSTEM_PROMPT, correction_message, task_prompt
from tools import TOOLS


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

    # Return the tool definitions available to this agent.
    def tool_definitions(self) -> list[dict]:
        return [tool["definition"]() for tool in TOOLS.values()]

    # Decide whether the loop should stop.
    # Look backward through the transcript for the most recent assistant message.
    # If that message is exactly "TASK COMPLETE", stop the loop.
    def should_stop(self, session) -> bool:
        for message in reversed(session.messages):
            if message["role"] != "assistant":
                continue

            content = message["content"].strip().upper()
            return "TASK COMPLETE" in content

        return False

    # Validate whether a normalized model reply counts as a real coding-agent turn.
    #
    # Valid reply shapes:
    # 1. A non-final reply with non-empty assistant content and exactly one tool action
    # 2. A final reply with content exactly equal to "TASK COMPLETE" and no tool actions
    #
    # Invalid reply shapes:
    # 1. A non-final reply with no tool action
    # 2. A non-final reply with the wrong number of tool actions
    # 3. An empty non-final reply
    # 4. A final reply that also includes tool actions
    #
    # This keeps the response-shape contract strict and obvious, closer to the
    # parser mindset used by mini-swe, while keeping the policy inside the
    # coding agent instead of the generic loop or model adapter.
    def validate_reply(self, reply: dict) -> dict:
        actions = reply["actions"]
        content = reply["message"]["content"].strip()
        normalized_content = content.upper()

        # Final completion is valid when it contains TASK COMPLETE and does not
        # also try to issue tool actions.
        if "TASK COMPLETE" in normalized_content:
            if actions:
                return {
                    "ok": False,
                    "reason": "final_with_tool_call",
                }

            return {
                "ok": True,
                "reason": "",
            }

        if not content:
            return {
                "ok": False,
                "reason": "empty_non_final_reply",
            }

        if len(actions) == 0:
            return {
                "ok": False,
                "reason": "non_final_no_tool_reply",
            }

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
    # rules, instead of hard-coding one generic stall reminder in the loop.
    def correction_message_for(self, reason: str) -> dict:
        return {
            "role": "user",
            "content": correction_message(reason),
        }
# agent/coding.py

from agent.prompts import SYSTEM_PROMPT, correction_message, task_prompt
from tools import TOOLS

# Final summary for task completion must include all these phrases for finalization to be valid. 
# The agent can use any wording it wants, as long as these phrases are present and the final non-empty line is "TASK COMPLETE".
REQUIRED_FINAL_LABELS = [
    "Files changed:",
    "What changed:",
    "Verification run:",
    "Remaining risks:",
]

INVALID_REPLY_EXPLANATIONS = {
    "non_final_no_tool_reply": "the model replied without the required tool call",
    "non_final_wrong_tool_count": "the model used the wrong number of tool calls",
    "final_with_tool_call": "the model tried to finalize while still issuing a tool call",
    "final_missing_required_sections": "the model tried to finalize without the required summary sections",
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

    # Return the tool definitions available to this agent.
    def tool_definitions(self) -> list[dict]:
        return [tool["definition"]() for tool in TOOLS.values()]

    # Return true only when the final non-empty line is the completion marker.
    def is_final_content(self, content: str) -> bool:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return bool(lines) and lines[-1].upper() == "TASK COMPLETE"

    # Return any required final-summary labels that are missing from content.
    def missing_final_labels(self, content: str) -> list[str]:
        return [label for label in REQUIRED_FINAL_LABELS if label not in content]

    # Decide whether the loop should stop.
    # Look backward through the transcript for the most recent assistant message.
    # If that message has no tool calls and ends with TASK COMPLETE, stop the loop.
    def should_stop(self, session) -> bool:
        for message in reversed(session.messages):
            if message["role"] != "assistant":
                continue

            return (
                not message.get("tool_calls")
                and self.is_final_content(message["content"])
                and not self.missing_final_labels(message["content"])
            )

        return False

    # Validate whether a normalized model reply counts as a real coding-agent turn.
    #
    # Valid reply shapes:
    # 1. A non-final reply with exactly one tool action
    # 2. A final reply with TASK COMPLETE on the last non-empty line and no tool actions
    #
    # Invalid reply shapes:
    # 1. A reply that carried a format_error from the model adapter
    # 2. A non-final reply with no tool action
    # 3. A non-final reply with the wrong number of tool actions
    # 4. A final reply that also includes tool actions
    #
    # Non-final assistant text is optional. The selected tool action is the
    # hard contract. If text is missing, the runtime can still proceed and
    # render progress from the selected action.
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

        # Final completion is valid when it ends with TASK COMPLETE and does
        # not also try to issue tool actions.
        if self.is_final_content(content):
            if actions:
                return {
                    "ok": False,
                    "reason": "final_with_tool_call",
                }

            if self.missing_final_labels(content):
                return {
                    "ok": False,
                    "reason": "final_missing_required_sections",
                }

            return {
                "ok": True,
                "reason": "",
            }

        # Non-final replies must include exactly one tool action.
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

# agent/coding.py
from agent.prompts import SYSTEM_PROMPT, STALL_REMINDER, task_prompt
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
    # If that message contains "TASK COMPLETE" anywhere, stop the loop.
    def should_stop(self, session) -> bool:
        for message in reversed(session.messages):
            if message["role"] != "assistant":
                continue

            content = message["content"].strip().upper()
            return "TASK COMPLETE" in content

        return False
    
    # Return the reminder message used when the model stalls.
    def stall_message(self) -> dict:
        return {
            "role": "user",
            "content": STALL_REMINDER,
        }
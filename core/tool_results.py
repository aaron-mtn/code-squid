# core/tool_results.py

import json


class ToolResults:
    """Owns formatting tool outputs back into model-visible messages; must not own tool execution, tool-call parsing, or coding-specific decisions."""

    # Convert one tool result into a transcript message.
    def message_from_result(self, result: dict) -> dict:
        return {
            "role": "tool",
            "content": json.dumps(result, indent=2),
        }

    # Convert multiple tool results into transcript messages in order.
    def messages_from_results(self, results: list[dict]) -> list[dict]:
        return [self.message_from_result(result) for result in results]
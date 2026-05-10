# core/model_adapter.py

import json

from tools import TOOLS


class ModelAdapter:
    """Owns provider communication and tool-call normalization; must not own loop control, session storage, or coding-agent policy."""

    # Store the provider and model name used for requests.
    # The provider handles the raw API call, while this adapter normalizes
    # provider output into the small internal reply shape used by the loop.
    def __init__(self, provider, model_name: str) -> None:
        self.provider = provider
        self.model_name = model_name

    # Send transcript messages and tool definitions to the provider,
    # then normalize the raw provider response into the internal reply shape.
    #
    # If the provider returns malformed tool-call output, convert that into
    # a controlled format_error reply instead of crashing the loop.
    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        raw_response = self.provider.create_response(
            model=self.model_name,
            messages=messages,
            tools=tool_definitions,
        )

        try:
            return self._normalize_response(raw_response)
        except ValueError as e:
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                },
                "actions": [],
                "format_error": str(e),
            }

    # Convert the raw provider response into a consistent internal format.
    # The result contains:
    # - one assistant message dict
    # - a list of normalized tool actions
    # - an optional format_error field when parsing fails upstream
    #
    # Important:
    # We preserve the assistant tool_calls metadata on the transcript message
    # so stricter model templates can reconstruct valid assistant/tool turns
    # on later requests.
    def _normalize_response(self, raw_response) -> dict:
        message = {
            "role": "assistant",
            "content": "",
        }
        actions = []

        assistant_message = raw_response.choices[0].message
        raw_tool_calls = assistant_message.tool_calls or []

        if assistant_message.content:
            message["content"] = assistant_message.content

        # Parse and validate each provider tool call before accepting it as a
        # real internal action. This keeps malformed tool output from slipping
        # into the loop as if it were valid.
        for tool_call in raw_tool_calls:
            tool_name = tool_call.function.name
            raw_arguments = tool_call.function.arguments
            args = self._parse_args(raw_arguments)
            self._validate_tool_action(tool_name, args)

            actions.append(
                {
                    "tool": tool_name,
                    "args": args,
                    "tool_call_id": tool_call.id,
                    "raw_arguments": raw_arguments,
                }
            )

        # Preserve the provider tool_calls structure on the assistant message.
        # This is important for replaying transcript history in a format that
        # stricter OpenAI-compatible model templates accept.
        if raw_tool_calls:
            message["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                for tool_call in raw_tool_calls
            ]

        # If the model returned tool calls but no visible assistant text,
        # create a short fallback narration so the transcript still shows
        # what the agent is doing.
        if not message["content"] and actions:
            message["content"] = self._fallback_message(actions)

        return {
            "message": message,
            "actions": actions,
            "format_error": "",
        }

    # Parse the provider's tool-call arguments into a normal dictionary.
    # OpenAI-compatible APIs usually return tool arguments as a JSON string.
    #
    # Reject non-object JSON so that malformed tool arguments are handled as
    # format errors instead of reaching tool execution in a half-valid shape.
    def _parse_args(self, arguments: str) -> dict:
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as e:
            raise ValueError(f"Tool arguments were not valid JSON: {e}") from e

        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must decode to a JSON object")

        return parsed

    # Validate that a normalized tool action refers to a known tool and
    # includes all required arguments from that tool's definition.
    #
    # This is intentionally shallow for now:
    # - known tool name
    # - required argument presence
    #
    # That gets us much closer to mini-swe's parser mindset without adding
    # a bunch of schema machinery too early.
    def _validate_tool_action(self, tool_name: str, args: dict) -> None:
        tool = TOOLS.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        required_args = self._required_args_for_tool(tool_name)
        missing_args = [name for name in required_args if name not in args]
        if missing_args:
            missing = ", ".join(missing_args)
            raise ValueError(f"Missing required arguments for {tool_name}: {missing}")

    # Read the required argument names directly from the tool definition so
    # the adapter stays aligned with the actual registered tool schema.
    def _required_args_for_tool(self, tool_name: str) -> list[str]:
        definition = TOOLS[tool_name]["definition"]()
        parameters = definition["function"].get("parameters", {})
        return parameters.get("required", [])

    # Create a short assistant message when the model uses tools without
    # returning visible narration text.
    def _fallback_message(self, actions: list[dict]) -> str:
        if len(actions) == 1:
            tool_name = actions[0]["tool"]
            return f"Using {tool_name}."

        tool_names = ", ".join(action["tool"] for action in actions)
        return f"Using tools: {tool_names}."
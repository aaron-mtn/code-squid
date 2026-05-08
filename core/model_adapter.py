# core/model_adapter.py

import json


class ModelAdapter:
    """Owns provider communication and tool-call normalization; must not own loop control, session storage, or coding-agent policy."""

    # Store the provider and model name used for requests.
    # The provider handles the raw API call, while this adapter normalizes responses.
    def __init__(self, provider, model_name: str) -> None:
        self.provider = provider
        self.model_name = model_name

    # Send transcript messages and tool definitions to the provider,
    # then normalize the raw provider response into the small internal shape
    # used by the rest of Code Squid.
    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        raw_response = self.provider.create_response(
            model=self.model_name,
            messages=messages,
            tools=tool_definitions,
        )
        return self._normalize_response(raw_response)

    # Convert the raw provider response into a consistent internal format.
    # The result always contains:
    # - one assistant message dict
    # - a list of normalized tool actions
    def _normalize_response(self, raw_response) -> dict:
        message = {
            "role": "assistant",
            "content": "",
        }
        actions = []

        assistant_message = raw_response.choices[0].message

        if assistant_message.content:
            message["content"] = assistant_message.content

        for tool_call in assistant_message.tool_calls or []:
            actions.append(
                {
                    "tool": tool_call.function.name,
                    "args": self._parse_args(tool_call.function.arguments),
                }
            )

        # If the model returned tool calls but no visible assistant text,
        # create a short fallback narration so the transcript still shows
        # what the agent is doing.
        if not message["content"] and actions:
            message["content"] = self._fallback_message(actions)

        return {
            "message": message,
            "actions": actions,
        }

    # Parse the provider's tool-call arguments into a normal dictionary.
    # OpenAI-compatible APIs usually return tool arguments as a JSON string.
    def _parse_args(self, arguments: str) -> dict:
        return json.loads(arguments)

    # Create a short assistant message when the model uses tools without
    # returning visible narration text.
    def _fallback_message(self, actions: list[dict]) -> str:
        if len(actions) == 1:
            tool_name = actions[0]["tool"]
            return f"Using {tool_name}."

        tool_names = ", ".join(action["tool"] for action in actions)
        return f"Using tools: {tool_names}."
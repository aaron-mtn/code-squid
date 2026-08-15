# core/model_adapter.py

import json

TOOL_CALL_CONTENT_MODES = {"omit", "empty", "null"}


class ModelRequestError(RuntimeError):
    """Raised when the configured model provider request fails."""


class ModelAdapter:
    """Owns provider communication and tool-call normalization; must not own loop control, session storage, or coding-agent policy."""

    # Store the provider and model name used for requests.
    # The provider handles the raw API call, while this adapter normalizes
    # provider output into the small internal reply shape used by the loop.
    def __init__(
        self,
        provider,
        model_name: str,
        tool_call_content_mode: str = "empty",
        provider_name: str | None = None,
    ) -> None:
        if tool_call_content_mode not in TOOL_CALL_CONTENT_MODES:
            valid_modes = ", ".join(sorted(TOOL_CALL_CONTENT_MODES))
            raise ValueError(f"tool_call_content_mode must be one of {valid_modes}")

        self.provider = provider
        self.model_name = model_name
        self.tool_call_content_mode = tool_call_content_mode
        self.provider_name = provider_name or type(provider).__name__

    # Send transcript messages and tool definitions to the provider,
    # then normalize the raw provider response into the internal reply shape.
    #
    # If the provider returns malformed tool-call output, convert that into
    # a controlled format_error reply instead of crashing the loop.
    def respond(self, messages: list[dict], tool_definitions: list[dict]) -> dict:
        tool_metadata = self._tool_metadata_from_definitions(tool_definitions)
        try:
            raw_response = self.provider.create_response(
                model=self.model_name,
                messages=self._messages_for_provider(messages),
                tools=tool_definitions,
            )
        except Exception as exc:
            # Provider-specific failures are wrapped at this boundary so the
            # CLI can handle request failures without hiding Code Squid bugs
            # from normalization, validation, or the rest of the app.
            raise ModelRequestError("Model request failed") from exc

        return self._reply_from_response(raw_response, tool_metadata)

    def supports_streaming(self) -> bool:
        return bool(getattr(self.provider, "supports_streaming", lambda: False)())

    def respond_streaming(
        self,
        messages: list[dict],
        tool_definitions: list[dict],
        on_text_delta,
        on_tool_preparing=None,
    ) -> dict:
        tool_metadata = self._tool_metadata_from_definitions(tool_definitions)
        try:
            raw_response = self.provider.stream_chat(
                model=self.model_name,
                messages=self._messages_for_provider(messages),
                tools=tool_definitions,
                on_text_delta=on_text_delta,
                on_tool_preparing=on_tool_preparing,
            )
        except Exception as exc:
            raise ModelRequestError("Model request failed") from exc

        return self._reply_from_response(raw_response, tool_metadata)

    def complete_text(self, messages: list[dict]) -> dict:
        try:
            raw_response = self.provider.create_response(
                model=self.model_name,
                messages=self._messages_for_provider(messages),
                tools=[],
            )
        except Exception as exc:
            raise ModelRequestError("Model request failed") from exc

        assistant_message = raw_response.choices[0].message
        return {
            "content": assistant_message.content or "",
            "usage": self._usage_from_response(raw_response),
        }

    def complete_text_streaming(self, messages: list[dict], on_text_delta) -> str:
        if not self.supports_streaming():
            content = self.complete_text(messages)["content"]
            if content:
                on_text_delta(content)
            return content

        try:
            raw_response = self.provider.stream_chat(
                model=self.model_name,
                messages=self._messages_for_provider(messages),
                tools=[],
                on_text_delta=on_text_delta,
            )
        except Exception as exc:
            raise ModelRequestError("Model request failed") from exc

        assistant_message = raw_response.choices[0].message
        return assistant_message.content or ""

    # Build the tiny metadata map the adapter needs for validation from the
    # active tool definitions passed into this request.
    def _tool_metadata_from_definitions(self, tool_definitions: list[dict]) -> dict:
        metadata = {}
        for definition in tool_definitions:
            function = definition["function"]
            parameters = function.get("parameters", {})
            metadata[function["name"]] = {
                "required": parameters.get("required", []),
            }
        return metadata

    def _messages_for_provider(self, messages: list[dict]) -> list[dict]:
        provider_messages = []
        for message in messages:
            provider_message = dict(message)
            if (
                provider_message.get("role") == "assistant"
                and provider_message.get("tool_calls")
                and not provider_message.get("content")
            ):
                if self.tool_call_content_mode == "omit":
                    provider_message.pop("content", None)
                elif self.tool_call_content_mode == "empty":
                    provider_message["content"] = ""
                elif self.tool_call_content_mode == "null":
                    provider_message["content"] = None

            provider_messages.append(provider_message)

        return provider_messages

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
    def _normalize_response(self, raw_response, tool_metadata: dict) -> dict:
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
            try:
                args = self._parse_args(raw_arguments)
                self._validate_tool_action(tool_name, args, tool_metadata)
            except ValueError as error:
                error.recoverable_tool_name = tool_name
                error.recoverable_raw_arguments = raw_arguments
                raise

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

        return {
            "message": message,
            "actions": actions,
            "format_error": "",
            "usage": self._usage_from_response(raw_response),
        }

    def _usage_from_response(self, raw_response) -> dict | None:
        if isinstance(raw_response, dict):
            usage = raw_response.get("usage")
        else:
            usage = getattr(raw_response, "usage", None)
        if usage is None:
            return None

        return {
            "input_tokens": self._usage_value(usage, "input_tokens", "prompt_tokens"),
            "output_tokens": self._usage_value(usage, "output_tokens", "completion_tokens"),
            "total_tokens": self._usage_value(usage, "total_tokens"),
        }

    def _usage_value(self, usage, *names: str):
        for name in names:
            if isinstance(usage, dict):
                value = usage.get(name)
            else:
                value = getattr(usage, name, None)
            if value is not None:
                return value

        return None

    def _raw_reply_from_response(self, raw_response) -> dict:
        """Extract only data the provider actually exposed, before parsing tool arguments."""
        choices = self._value(raw_response, "choices") or []
        choice = choices[0] if choices else None
        assistant_message = self._value(choice, "message") or {}
        raw_tool_calls = self._value(assistant_message, "tool_calls") or []

        assistant = {
            "content": self._json_value(self._value(assistant_message, "content")),
            "raw_tool_calls": [self._json_value(tool_call) for tool_call in raw_tool_calls],
        }
        for name in ("reasoning", "reasoning_content", "thinking"):
            value = self._value(assistant_message, name)
            if value is not None:
                assistant[name] = self._json_value(value)

        raw_reply = {
            "provider": self.provider_name,
            "model": self.model_name,
            "assistant": assistant,
        }
        usage = self._usage_from_response(raw_response)
        if usage is not None:
            raw_reply["usage"] = usage

        finish_reason = self._value(choice, "finish_reason")
        if finish_reason is not None:
            raw_reply["finish_reason"] = self._json_value(finish_reason)

        for name in ("id", "response_id", "request_id", "_request_id"):
            value = self._value(raw_response, name)
            if value is not None:
                raw_reply["response_id"] = self._json_value(value)
                break

        return raw_reply

    def _reply_from_response(self, raw_response, tool_metadata: dict) -> dict:
        raw_reply = self._raw_reply_from_response(raw_response)
        try:
            reply = self._normalize_response(raw_response, tool_metadata)
        except ValueError as error:
            reply = {
                "message": {
                    "role": "assistant",
                    "content": raw_reply["assistant"].get("content") or "",
                },
                "actions": [],
                "format_error": str(error),
                "usage": raw_reply.get("usage"),
                **self._recoverable_tool_fields(error),
            }

        reply["raw_reply"] = raw_reply
        return reply

    def _value(self, value, name: str):
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)

    def _json_value(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): self._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_value(item) for item in value]

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return self._json_value(model_dump(mode="json"))
            except TypeError:
                return self._json_value(model_dump())

        try:
            fields = vars(value).items()
        except TypeError:
            return str(value)
        public_fields = {
            name: self._json_value(field_value)
            for name, field_value in fields
            if not name.startswith("_")
        }
        return public_fields or str(value)

    def _recoverable_tool_fields(self, error: ValueError) -> dict:
        fields = {}
        tool_name = getattr(error, "recoverable_tool_name", None)
        raw_arguments = getattr(error, "recoverable_raw_arguments", None)
        if tool_name is not None:
            fields["recoverable_tool_name"] = tool_name
        if raw_arguments is not None:
            fields["recoverable_raw_arguments"] = raw_arguments
        return fields

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
    def _validate_tool_action(self, tool_name: str, args: dict, tool_metadata: dict) -> None:
        if tool_name not in tool_metadata:
            raise ValueError(f"Unknown tool: {tool_name}")

        required_args = tool_metadata[tool_name]["required"]
        missing_args = [name for name in required_args if name not in args]
        if missing_args:
            missing = ", ".join(missing_args)
            raise ValueError(f"Missing required arguments for {tool_name}: {missing}")

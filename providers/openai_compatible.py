# providers/openai_compatible.py

"""OpenAI-compatible chat-completions provider transport."""

from types import SimpleNamespace

from openai import OpenAI

from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """Owns raw OpenAI-compatible API calls; must not own response normalization, agent policy, or tool execution."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        temperature: float | int | None = None,
        debug: bool = False,
    ) -> None:
        self.temperature = temperature
        self.debug = debug
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key or "lm-studio",
        )

    def supports_streaming(self) -> bool:
        return True

    def create_response(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
    ) -> object:
        payload = self._payload(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

        if self.debug:
            self._print_request_summary(payload)

        return self.client.chat.completions.create(**payload)

    def stream_chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        on_text_delta,
        tool_choice=None,
    ) -> object:
        payload = self._payload(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        payload["stream"] = True

        if self.debug:
            self._print_request_summary(payload)

        content_parts = []
        tool_call_parts = {}
        usage = None

        for chunk in self.client.chat.completions.create(**payload):
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = chunk_usage

            for choice in getattr(chunk, "choices", []) or []:
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                content_delta = getattr(delta, "content", None)
                if content_delta:
                    content_parts.append(content_delta)
                    on_text_delta(content_delta)

                for tool_call_delta in getattr(delta, "tool_calls", None) or []:
                    self._accumulate_tool_call_delta(tool_call_parts, tool_call_delta)

        return self._assembled_stream_response(
            content="".join(content_parts),
            tool_call_parts=tool_call_parts,
            usage=usage,
        )

    def _payload(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
    ) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if tools:
            payload["parallel_tool_calls"] = False
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return payload

    def _accumulate_tool_call_delta(self, tool_call_parts: dict, tool_call_delta) -> None:
        index = getattr(tool_call_delta, "index", None)
        if index is None:
            index = len(tool_call_parts)

        part = tool_call_parts.setdefault(
            index,
            {
                "id": "",
                "type": "function",
                "name": "",
                "arguments": [],
            },
        )

        call_id = getattr(tool_call_delta, "id", None)
        if call_id:
            part["id"] = call_id

        call_type = getattr(tool_call_delta, "type", None)
        if call_type:
            part["type"] = call_type

        function = getattr(tool_call_delta, "function", None)
        if function is None:
            return

        name = getattr(function, "name", None)
        if name:
            part["name"] += name

        arguments = getattr(function, "arguments", None)
        if arguments:
            part["arguments"].append(arguments)

    def _assembled_stream_response(
        self,
        content: str,
        tool_call_parts: dict,
        usage,
    ) -> object:
        tool_calls = [
            SimpleNamespace(
                id=part["id"] or f"call_{index}",
                type=part["type"] or "function",
                function=SimpleNamespace(
                    name=part["name"],
                    arguments="".join(part["arguments"]),
                ),
            )
            for index, part in sorted(tool_call_parts.items())
        ]

        message = SimpleNamespace(
            content=content,
            tool_calls=tool_calls,
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=usage,
        )

    def _print_request_summary(self, payload: dict) -> None:
        def field(name: str) -> object:
            return payload[name] if name in payload else "<missing>"

        lines = [
            "provider: openai-compatible",
            f"model: {field('model')}",
            f"messages: {len(payload['messages'])}",
            f"tools: {len(payload.get('tools') or [])}",
            f"temperature: {field('temperature')}",
            f"stream: {str(field('stream')).lower()}",
            f"parallel_tool_calls: {str(field('parallel_tool_calls')).lower()}",
            f"tool_choice: {field('tool_choice')}",
        ]
        self._debug_block("provider request", lines)

    def _debug_block(self, title: str, lines: list[str]) -> None:
        width = 47
        top_label = f"─ {title} "
        print(f"┌{top_label}{'─' * max(width - len(top_label), 0)}")
        for line in lines:
            print(f"│ {line}")
        print(f"└{'─' * width}")

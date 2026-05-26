# providers/openai_compatible.py

"""OpenAI-compatible chat-completions provider transport."""

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

    def create_response(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
    ) -> object:
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

        if self.debug:
            self._print_request_summary(payload)

        return self.client.chat.completions.create(**payload)

    def _print_request_summary(self, payload: dict) -> None:
        def field(name: str) -> object:
            return payload[name] if name in payload else "<missing>"

        lines = [
            "provider: openai-compatible",
            f"model: {field('model')}",
            f"messages: {len(payload['messages'])}",
            f"tools: {len(payload.get('tools') or [])}",
            f"temperature: {field('temperature')}",
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

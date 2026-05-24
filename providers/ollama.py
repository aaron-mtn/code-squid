# providers/ollama.py

"""Native Ollama chat provider transport and response adapter."""

from __future__ import annotations

import json
from types import SimpleNamespace
from urllib import request
from urllib.error import HTTPError, URLError

from .base import BaseProvider


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


class OllamaProvider(BaseProvider):
    """Owns native Ollama /api/chat calls and adapts them to the OpenAI-like shape ModelAdapter expects."""

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        temperature: float | int | None = None,
    ) -> None:
        self.base_url = _native_base_url(base_url)
        self.temperature = temperature

    def create_response(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
    ) -> object:
        payload = {
            "model": model,
            "messages": convert_messages(messages),
            "tools": tools,
            "stream": False,
            "think": False,
        }
        if self.temperature is not None:
            payload["options"] = {"temperature": self.temperature}
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        raw_response = self._post_chat(payload)
        return adapt_response(raw_response)

    def _post_chat(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed with HTTP {error.code}: {details}") from error
        except URLError as error:
            raise RuntimeError(f"Ollama request failed: {error.reason}") from error


def _native_base_url(base_url: str | None) -> str:
    """Return an Ollama native base URL, tolerating existing OpenAI-compatible /v1 settings."""

    if not base_url:
        return DEFAULT_OLLAMA_BASE_URL

    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return normalized[: -len("/v1")]
    return normalized


def convert_messages(messages: list[dict]) -> list[dict]:
    converted = []
    tool_call_names: dict[str, str] = {}

    for message in messages:
        role = message.get("role")
        if role == "tool":
            converted.append(_convert_tool_result(message, tool_call_names))
            continue

        converted_message = {
            "role": role,
            "content": message.get("content") or "",
        }

        if role == "assistant" and message.get("tool_calls"):
            converted_tool_calls = []
            for tool_call in message["tool_calls"]:
                call_id = tool_call.get("id")
                function = tool_call.get("function", {})
                name = function.get("name")
                if call_id and name:
                    tool_call_names[call_id] = name

                converted_tool_calls.append(
                    {
                        "type": tool_call.get("type", "function"),
                        "function": {
                            "name": name,
                            "arguments": _parse_arguments(function.get("arguments", {})),
                        },
                    }
                )
            converted_message["tool_calls"] = converted_tool_calls

        converted.append(converted_message)

    return converted


def _convert_tool_result(message: dict, tool_call_names: dict[str, str]) -> dict:
    tool_call_id = message.get("tool_call_id")
    tool_name = tool_call_names.get(tool_call_id)
    if not tool_name:
        raise ValueError(f"Ollama tool result references unknown tool_call_id: {tool_call_id}")

    return {
        "role": "tool",
        "tool_name": tool_name,
        "content": message.get("content") or "",
    }


def _parse_arguments(arguments):
    if not isinstance(arguments, str):
        return arguments

    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments

    return parsed if isinstance(parsed, dict) else arguments


def adapt_response(raw_response: dict) -> object:
    message = raw_response.get("message", {})
    tool_calls = [
        _adapt_tool_call(index, tool_call)
        for index, tool_call in enumerate(message.get("tool_calls") or [])
    ]

    adapted_message = SimpleNamespace(
        content=message.get("content") or "",
        tool_calls=tool_calls,
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=adapted_message)])


def _adapt_tool_call(index: int, tool_call: dict) -> object:
    function = tool_call.get("function", {})
    arguments = function.get("arguments", {})
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)

    return SimpleNamespace(
        id=tool_call.get("id") or f"ollama_call_{index}",
        function=SimpleNamespace(
            name=function.get("name"),
            arguments=arguments,
        ),
    )

"""Native Ollama chat provider transport and response adapter."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib import request
from urllib.error import HTTPError, URLError

from .base import BaseProvider, StreamCancelled


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

    def supports_streaming(self) -> bool:
        return True

    def is_ready(self) -> bool:
        """Use Ollama's lightweight model-list request as its readiness probe."""
        try:
            self.list_models()
            return True
        except (OSError, RuntimeError, ValueError, HTTPError, URLError):
            return False

    def list_models(self) -> list[str]:
        """Return exact names from Ollama's native ``/api/tags`` API."""
        http_request = request.Request(
            f"{self.base_url}/api/tags",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with request.urlopen(http_request, timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise RuntimeError("Ollama response did not include a model list")
        seen: set[str] = set()
        model_ids: list[str] = []
        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = model.get("name") or model.get("model")
            if isinstance(model_id, str) and model_id and model_id not in seen:
                seen.add(model_id)
                model_ids.append(model_id)
        return model_ids

    def create_response(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
        please_stop_contemplating_the_void: bool = False,
    ) -> object:
        payload = {
            "model": model,
            "messages": convert_messages(messages),
            "tools": tools,
            "stream": False,
        }
        if please_stop_contemplating_the_void:
            payload["think"] = False
        if self.temperature is not None:
            payload["options"] = {"temperature": self.temperature}
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        raw_response = self._post_chat(payload)
        return adapt_response(raw_response)

    def stream_chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        on_text_delta,
        on_tool_preparing=None,
        tool_choice=None,
        trace_callback=None,
        please_stop_contemplating_the_void: bool = False,
        should_cancel=None,
    ) -> object:
        payload = {
            "model": model,
            "messages": convert_messages(messages),
            "tools": tools,
            "stream": True,
        }
        if please_stop_contemplating_the_void:
            payload["think"] = False
        if self.temperature is not None:
            payload["options"] = {"temperature": self.temperature}
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        assembled = _empty_stream_response()
        prepared_tool_call_indexes = set()
        request_started_at = time.perf_counter()
        raw_chunk_count = 0
        total_content_characters = 0
        total_reasoning_characters = 0
        first_raw_chunk_elapsed = None
        first_content_delta_elapsed = None
        first_reasoning_delta_elapsed = None
        response_id = None
        saw_completion = False
        self._trace(
            trace_callback,
            {
                "type": "request_start",
                "timestamp_unix": time.time(),
                "monotonic": request_started_at,
                "provider": "ollama",
                "model": model,
                "base_url": self.base_url,
                "payload": payload,
            },
        )

        stream = self._post_chat_stream(payload)
        try:
            for chunk in stream:
                if should_cancel is not None and should_cancel():
                    raise StreamCancelled
                chunk_elapsed = time.perf_counter() - request_started_at
                raw_chunk_count += 1
                if first_raw_chunk_elapsed is None:
                    first_raw_chunk_elapsed = chunk_elapsed
                response_id = response_id or chunk.get("id")
                message = chunk.get("message") or {}
                content_delta = message.get("content") or ""
                reasoning_deltas = {
                    name: message.get(name) or ""
                    for name in ("reasoning", "reasoning_content", "thinking")
                }
                if content_delta:
                    total_content_characters += len(content_delta)
                    if first_content_delta_elapsed is None:
                        first_content_delta_elapsed = chunk_elapsed
                reasoning_character_count = sum(
                    len(value) for value in reasoning_deltas.values()
                )
                if reasoning_character_count:
                    total_reasoning_characters += reasoning_character_count
                    if first_reasoning_delta_elapsed is None:
                        first_reasoning_delta_elapsed = chunk_elapsed

                self._trace(
                    trace_callback,
                    {
                        "type": "raw_chunk",
                        "elapsed": chunk_elapsed,
                        "chunk_index": raw_chunk_count,
                        "raw": chunk,
                        "response_id": chunk.get("id"),
                        "content_delta": content_delta,
                        "reasoning_delta": reasoning_deltas["reasoning"],
                        "reasoning_content_delta": reasoning_deltas["reasoning_content"],
                        "thinking_delta": reasoning_deltas["thinking"],
                        "finish_reason": chunk.get("done_reason"),
                    },
                )
                _accumulate_stream_chunk(
                    assembled,
                    chunk,
                    on_text_delta=on_text_delta,
                    on_tool_preparing=on_tool_preparing,
                    prepared_tool_call_indexes=prepared_tool_call_indexes,
                )
                if chunk.get("done") is True:
                    saw_completion = True
                    break
            if not saw_completion:
                # EOF is not an Ollama completion signal. Check cancellation
                # once more because it may have closed an otherwise idle stream.
                if should_cancel is not None and should_cancel():
                    raise StreamCancelled
                raise RuntimeError(
                    "Ollama stream ended before provider signaled completion"
                )
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
            self._trace(
                trace_callback,
                {
                    "type": "request_complete",
                    "timestamp_unix": time.time(),
                    "elapsed": time.perf_counter() - request_started_at,
                    "response_id": response_id,
                    "finish_reason": assembled.get("done_reason"),
                    "first_raw_chunk_elapsed": first_raw_chunk_elapsed,
                    "first_reasoning_delta_elapsed": first_reasoning_delta_elapsed,
                    "first_visible_content_delta_elapsed": first_content_delta_elapsed,
                    "total_reasoning_characters": total_reasoning_characters,
                    "total_visible_content_characters": total_content_characters,
                    "total_raw_chunk_count": raw_chunk_count,
                },
            )

        return adapt_response(assembled)

    def _trace(self, trace_callback, event: dict) -> None:
        """Keep optional diagnostic output from changing provider behavior."""
        if trace_callback is None:
            return
        try:
            trace_callback(event)
        except Exception:
            pass

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

    def _post_chat_stream(self, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request) as response:
                for line in response:
                    line = line.strip()
                    if not line:
                        continue
                    yield json.loads(line.decode("utf-8"))
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

    message_fields = {
        "content": message.get("content") or "",
        "tool_calls": tool_calls,
    }
    for name in ("reasoning", "reasoning_content", "thinking"):
        if message.get(name) is not None:
            message_fields[name] = message[name]
    adapted_message = SimpleNamespace(**message_fields)
    return SimpleNamespace(
        id=raw_response.get("id"),
        choices=[
            SimpleNamespace(
                message=adapted_message,
                finish_reason=raw_response.get("done_reason"),
            )
        ],
        usage=_adapt_usage(raw_response),
    )


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


def _empty_stream_response() -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [],
        },
    }


def _accumulate_stream_chunk(
    assembled: dict,
    chunk: dict,
    on_text_delta,
    on_tool_preparing,
    prepared_tool_call_indexes: set,
) -> None:
    message = chunk.get("message") or {}
    assembled_message = assembled["message"]

    content_delta = message.get("content")
    if content_delta:
        assembled_message["content"] += content_delta
        on_text_delta(content_delta)

    for name in ("reasoning", "reasoning_content", "thinking"):
        value = message.get(name)
        if value:
            assembled_message[name] = f"{assembled_message.get(name, '')}{value}"

    for index, tool_call in enumerate(message.get("tool_calls") or []):
        _accumulate_tool_call(assembled_message["tool_calls"], index, tool_call)
        _notify_tool_preparing(
            assembled_message["tool_calls"],
            index,
            prepared_tool_call_indexes,
            on_tool_preparing,
        )

    for name in (
        "done",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    ):
        if name in chunk:
            assembled[name] = chunk[name]


def _accumulate_tool_call(tool_calls: list[dict], index: int, tool_call: dict) -> None:
    while len(tool_calls) <= index:
        tool_calls.append({"type": "function", "function": {"name": "", "arguments": {}}})

    existing = tool_calls[index]
    if tool_call.get("id"):
        existing["id"] = tool_call["id"]
    if tool_call.get("type"):
        existing["type"] = tool_call["type"]

    function = tool_call.get("function") or {}
    existing_function = existing.setdefault("function", {})
    if function.get("name"):
        existing_function["name"] = _append_or_set(existing_function.get("name"), function["name"])
    if "arguments" in function:
        existing_function["arguments"] = _merge_arguments(
            existing_function.get("arguments"),
            function["arguments"],
        )


def _append_or_set(existing, value):
    if not existing:
        return value
    if isinstance(existing, str) and isinstance(value, str) and value not in existing:
        return f"{existing}{value}"
    return existing


def _merge_arguments(existing, value):
    if existing in (None, {}, ""):
        return value
    if isinstance(existing, dict) and isinstance(value, dict):
        return {**existing, **value}
    if isinstance(existing, str) and isinstance(value, str):
        return f"{existing}{value}"
    return value


def _notify_tool_preparing(
    tool_calls: list[dict],
    index: int,
    prepared_tool_call_indexes: set,
    on_tool_preparing,
) -> None:
    if on_tool_preparing is None or index in prepared_tool_call_indexes:
        return

    function = tool_calls[index].get("function") or {}
    tool_name = function.get("name")
    if not tool_name:
        return

    prepared_tool_call_indexes.add(index)
    event = {
        "tool": tool_name,
        "tool_call_index": index,
    }
    call_id = tool_calls[index].get("id")
    if call_id:
        event["tool_call_id"] = call_id
    on_tool_preparing(event)


def _adapt_usage(raw_response: dict) -> object | None:
    prompt_tokens = raw_response.get("prompt_eval_count")
    completion_tokens = raw_response.get("eval_count")
    if prompt_tokens is None and completion_tokens is None:
        return None

    total_tokens = None
    if prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )

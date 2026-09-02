# providers/openai_compatible.py

"""OpenAI-compatible chat-completions provider transport."""

import time
from types import SimpleNamespace

from openai import OpenAI

from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """Owns raw OpenAI-compatible API calls; must not own response normalization, agent policy, or tool execution."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        temperature: float | int | None = None,
        provider_name: str = "openai_compatible",
    ) -> None:
        self.base_url = base_url
        self.temperature = temperature
        self.provider_name = provider_name
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    def supports_streaming(self) -> bool:
        return True

    def create_response(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
        please_stop_contemplating_the_void: bool = False,
    ) -> object:
        payload = self._payload(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            please_stop_contemplating_the_void=please_stop_contemplating_the_void,
        )

        return self.client.chat.completions.create(**payload)

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
    ) -> object:
        payload = self._payload(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            please_stop_contemplating_the_void=please_stop_contemplating_the_void,
        )
        payload["stream"] = True

        content_parts = []
        reasoning_parts = {"reasoning": [], "reasoning_content": [], "thinking": []}
        tool_call_parts = {}
        prepared_tool_call_indexes = set()
        usage = None
        finish_reason = None
        response_id = None
        request_started_at = time.perf_counter()
        raw_chunk_count = 0
        total_content_characters = 0
        total_reasoning_characters = 0
        first_raw_chunk_elapsed = None
        first_content_delta_elapsed = None
        first_reasoning_delta_elapsed = None

        self._trace(
            trace_callback,
            {
                "type": "request_start",
                "timestamp_unix": time.time(),
                "monotonic": request_started_at,
                "provider": "openai_compatible",
                "model": model,
                "base_url": getattr(self, "base_url", None),
                "payload": payload,
            },
        )

        try:
            for chunk in self.client.chat.completions.create(**payload):
                chunk_elapsed = time.perf_counter() - request_started_at
                if trace_callback is not None:
                    raw_chunk_count += 1
                    if first_raw_chunk_elapsed is None:
                        first_raw_chunk_elapsed = chunk_elapsed
                    chunk_content_deltas = []
                    chunk_reasoning_deltas = {
                        "reasoning": [],
                        "reasoning_content": [],
                        "thinking": [],
                    }
                    chunk_finish_reasons = []
                    for choice in getattr(chunk, "choices", []) or []:
                        choice_finish_reason = getattr(choice, "finish_reason", None)
                        if choice_finish_reason is not None:
                            chunk_finish_reasons.append(choice_finish_reason)
                        delta = getattr(choice, "delta", None)
                        if delta is None:
                            continue
                        content_delta = getattr(delta, "content", None)
                        if content_delta:
                            chunk_content_deltas.append(content_delta)
                            total_content_characters += len(content_delta)
                            if first_content_delta_elapsed is None:
                                first_content_delta_elapsed = chunk_elapsed
                        for name in chunk_reasoning_deltas:
                            value = getattr(delta, name, None)
                            if value:
                                chunk_reasoning_deltas[name].append(value)
                                total_reasoning_characters += len(value)
                                if first_reasoning_delta_elapsed is None:
                                    first_reasoning_delta_elapsed = chunk_elapsed

                    # Emit before the original normalization loop and visible
                    # callback so tracing cannot confuse provider and Desktop time.
                    self._trace(
                        trace_callback,
                        {
                            "type": "raw_chunk",
                            "elapsed": chunk_elapsed,
                            "chunk_index": raw_chunk_count,
                            "raw": chunk,
                            "response_id": getattr(chunk, "id", None),
                            "content_delta": "".join(chunk_content_deltas),
                            "reasoning_delta": "".join(chunk_reasoning_deltas["reasoning"]),
                            "reasoning_content_delta": "".join(
                                chunk_reasoning_deltas["reasoning_content"]
                            ),
                            "thinking_delta": "".join(chunk_reasoning_deltas["thinking"]),
                            "finish_reason": chunk_finish_reasons,
                        },
                    )

                # This is the pre-existing response assembly path. Trace mode
                # only observes immediately before it; normal mode stays exact.
                response_id = response_id or getattr(chunk, "id", None)
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage
                for choice in getattr(chunk, "choices", []) or []:
                    choice_finish_reason = getattr(choice, "finish_reason", None)
                    if choice_finish_reason is not None:
                        finish_reason = choice_finish_reason
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    content_delta = getattr(delta, "content", None)
                    if content_delta:
                        content_parts.append(content_delta)
                        on_text_delta(content_delta)
                    for name, parts in reasoning_parts.items():
                        value = getattr(delta, name, None)
                        if value:
                            parts.append(value)
                    for tool_call_delta in getattr(delta, "tool_calls", None) or []:
                        self._accumulate_tool_call_delta(tool_call_parts, tool_call_delta)
                        self._notify_tool_preparing(
                            tool_call_parts=tool_call_parts,
                            tool_call_delta=tool_call_delta,
                            prepared_tool_call_indexes=prepared_tool_call_indexes,
                            on_tool_preparing=on_tool_preparing,
                        )
        finally:
            self._trace(
                trace_callback,
                {
                    "type": "request_complete",
                    "timestamp_unix": time.time(),
                    "elapsed": time.perf_counter() - request_started_at,
                    "response_id": response_id,
                    "finish_reason": finish_reason,
                    "first_raw_chunk_elapsed": first_raw_chunk_elapsed,
                    "first_reasoning_delta_elapsed": first_reasoning_delta_elapsed,
                    "first_visible_content_delta_elapsed": first_content_delta_elapsed,
                    "total_reasoning_characters": total_reasoning_characters,
                    "total_visible_content_characters": total_content_characters,
                    "total_raw_chunk_count": raw_chunk_count,
                },
            )

        return self._assembled_stream_response(
            content="".join(content_parts),
            tool_call_parts=tool_call_parts,
            usage=usage,
            finish_reason=finish_reason,
            response_id=response_id,
            reasoning_parts=reasoning_parts,
        )

    def _trace(self, trace_callback, event: dict) -> None:
        """Keep optional diagnostic output from changing provider behavior."""
        if trace_callback is None:
            return
        try:
            trace_callback(event)
        except Exception:
            pass

    def _payload(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice=None,
        please_stop_contemplating_the_void: bool = False,
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
        if please_stop_contemplating_the_void:
            provider_name = getattr(self, "provider_name", "openai_compatible")
            if provider_name == "squid_models":
                payload["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": False},
                }
            elif provider_name == "openrouter":
                payload["extra_body"] = {"reasoning": {"effort": "none"}}
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

    def _notify_tool_preparing(
        self,
        tool_call_parts: dict,
        tool_call_delta,
        prepared_tool_call_indexes: set,
        on_tool_preparing,
    ) -> None:
        if on_tool_preparing is None:
            return

        index = getattr(tool_call_delta, "index", None)
        if index is None:
            index = len(tool_call_parts) - 1
        if index in prepared_tool_call_indexes:
            return

        part = tool_call_parts.get(index)
        if not part or not part["name"]:
            return

        prepared_tool_call_indexes.add(index)
        event = {
            "tool": part["name"],
            "tool_call_index": index,
        }
        if part["id"]:
            event["tool_call_id"] = part["id"]
        on_tool_preparing(event)

    def _assembled_stream_response(
        self,
        content: str,
        tool_call_parts: dict,
        usage,
        finish_reason=None,
        response_id=None,
        reasoning_parts=None,
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

        message_fields = {"content": content, "tool_calls": tool_calls}
        for name, parts in (reasoning_parts or {}).items():
            if parts:
                message_fields[name] = "".join(parts)
        message = SimpleNamespace(**message_fields)
        return SimpleNamespace(
            id=response_id,
            choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
            usage=usage,
        )


"""Minimal transcript compaction for continuation context."""

from __future__ import annotations

import json
from collections.abc import Callable

from squid_core.compaction.prompts import COMPACTION_SYSTEM_PROMPT, compaction_prompt
from squid_core.compaction.token_estimate import estimate_messages_tokens


class Compactor:
    """Replace older transcript chunks with model-generated continuation context."""

    def __init__(self, settings, model_adapter) -> None:
        self.settings = settings
        self.model_adapter = model_adapter

    def maybe_compact(
        self,
        session,
        *,
        event_callback: Callable[[dict], object] | None = None,
    ) -> dict | None:
        """Compact eligible history and report durable lifecycle diagnostics."""
        if not self.settings.enabled:
            return None

        stage = "prepare"
        try:
            estimated_tokens_before = estimate_messages_tokens(session.messages)
            threshold_crossed = (
                estimated_tokens_before >= self.settings.trigger_input_tokens
            )
            protected_messages, remaining_messages = self._split_protected_prefix(
                session.messages
            )
            chunks = self._chunks(remaining_messages)
            compacted_chunks = chunks[: -self.settings.keep_recent_turns]
            recent_chunks = chunks[-self.settings.keep_recent_turns :]
            will_compact = threshold_crossed and bool(compacted_chunks)

            stage = "persistence"
            self._emit(
                event_callback,
                {
                    "type": "compaction_check",
                    "estimated_tokens": estimated_tokens_before,
                    "trigger_input_tokens": self.settings.trigger_input_tokens,
                    "threshold_crossed": threshold_crossed,
                    "will_compact": will_compact,
                },
            )
            if not will_compact:
                return None

            messages_before = len(session.messages)
            self._emit(
                event_callback,
                {
                    "type": "compaction_started",
                    "estimated_tokens_before": estimated_tokens_before,
                    "messages_before": messages_before,
                    "keep_recent_turns": self.settings.keep_recent_turns,
                },
            )

            stage = "prepare"
            prior_context = json.dumps(compacted_chunks, ensure_ascii=False, indent=2)
            request_messages = [
                {
                    "role": "system",
                    "content": COMPACTION_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": compaction_prompt(prior_context),
                },
            ]
            request_event = {
                "type": "compaction_request",
                "estimated_request_tokens": estimate_messages_tokens(request_messages),
            }
            self._copy_adapter_identity(request_event)
            stage = "persistence"
            self._emit(event_callback, request_event)

            stage = "model_request"
            summary_response = self.model_adapter.complete_text(request_messages)

            stage = "response_parse"
            summary = summary_response.get("content") or ""
            reasoning = summary_response.get("reasoning")
            if reasoning:
                stage = "persistence"
                self._emit(
                    event_callback,
                    {"type": "compaction_reasoning", "content": reasoning},
                )

            # Persist the exact model output before touching session state so a
            # later rebuild or persistence error cannot erase the key evidence.
            stage = "persistence"
            self._emit(
                event_callback,
                {"type": "compaction_summary", "content": summary},
            )
            stage = "response_parse"
            response_meta = self._response_meta(summary_response)
            if response_meta:
                stage = "persistence"
                self._emit(
                    event_callback,
                    {"type": "compaction_response_meta", **response_meta},
                )

            stage = "session_rebuild"
            compacted_message = {
                "role": "user",
                "content": f"# Compacted Prior Context\n\n{summary}",
            }
            session.messages = [
                *protected_messages,
                compacted_message,
                *self._flatten(recent_chunks),
            ]
            metadata = {
                "estimated_tokens_before": estimated_tokens_before,
                "estimated_tokens_after": estimate_messages_tokens(session.messages),
                "messages_before": messages_before,
                "messages_after": len(session.messages),
                "summary_chars": len(summary),
            }

            stage = "persistence"
            self._emit(
                event_callback,
                {"type": "compaction_applied", **metadata},
            )
            return metadata
        except Exception as error:
            # Failure logging is best effort only when persistence itself has
            # failed; the original exception must always remain the one raised.
            try:
                self._emit(
                    event_callback,
                    {
                        "type": "compaction_failed",
                        "stage": stage,
                        "error_type": type(error).__name__,
                        "error": str(error) or type(error).__name__,
                    },
                )
            except Exception:
                pass
            raise

    def _emit(self, callback: Callable[[dict], object] | None, event: dict) -> None:
        if callback is not None:
            callback(event)

    def _copy_adapter_identity(self, event: dict) -> None:
        for event_name, adapter_name in (
            ("provider", "provider_name"),
            ("model", "model_name"),
        ):
            value = getattr(self.model_adapter, adapter_name, None)
            if value is not None:
                event[event_name] = value

    def _response_meta(self, response: dict) -> dict:
        metadata = {}
        if response.get("finish_reason") is not None:
            metadata["finish_reason"] = response["finish_reason"]
        usage = response.get("usage")
        if isinstance(usage, dict):
            available_usage = {
                name: value for name, value in usage.items() if value is not None
            }
            if available_usage:
                metadata["usage"] = available_usage
        return metadata

    def _split_protected_prefix(self, messages: list[dict]) -> tuple[list[dict], list[dict]]:
        protected_count = 0
        if messages and messages[0].get("role") == "system":
            protected_count = 1

        if len(messages) > protected_count and messages[protected_count].get("role") == "user":
            protected_count += 1

        return messages[:protected_count], messages[protected_count:]

    def _chunks(self, messages: list[dict]) -> list[list[dict]]:
        chunks = []
        index = 0
        while index < len(messages):
            message = messages[index]
            chunk = [message]
            index += 1

            if message.get("role") == "assistant" and message.get("tool_calls"):
                while index < len(messages) and messages[index].get("role") == "tool":
                    chunk.append(messages[index])
                    index += 1

            chunks.append(chunk)

        return chunks

    def _flatten(self, chunks: list[list[dict]]) -> list[dict]:
        messages = []
        for chunk in chunks:
            messages.extend(chunk)

        return messages

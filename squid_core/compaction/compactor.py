"""Minimal transcript compaction for continuation context."""

from __future__ import annotations

import json

from squid_core.compaction.prompts import COMPACTION_SYSTEM_PROMPT, compaction_prompt
from squid_core.compaction.token_estimate import estimate_messages_tokens


class Compactor:
    def __init__(self, settings, model_adapter) -> None:
        self.settings = settings
        self.model_adapter = model_adapter

    def maybe_compact(self, session) -> dict | None:
        if not self.settings.enabled:
            return None

        estimated_tokens_before = estimate_messages_tokens(session.messages)
        if estimated_tokens_before < self.settings.trigger_input_tokens:
            return None

        messages_before = len(session.messages)
        protected_messages, remaining_messages = self._split_protected_prefix(session.messages)
        chunks = self._chunks(remaining_messages)
        compacted_chunks = chunks[: -self.settings.keep_recent_turns]
        recent_chunks = chunks[-self.settings.keep_recent_turns :]

        if not compacted_chunks:
            return None

        prior_context = json.dumps(compacted_chunks, ensure_ascii=False, indent=2)
        summary_response = self.model_adapter.complete_text(
            [
                {
                    "role": "system",
                    "content": COMPACTION_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": compaction_prompt(prior_context),
                },
            ]
        )
        summary = summary_response.get("content") or ""
        compacted_message = {
            "role": "user",
            "content": f"# Compacted Prior Context\n\n{summary}",
        }

        session.messages = [
            *protected_messages,
            compacted_message,
            *self._flatten(recent_chunks),
        ]

        return {
            "estimated_tokens_before": estimated_tokens_before,
            "estimated_tokens_after": estimate_messages_tokens(session.messages),
            "messages_before": messages_before,
            "messages_after": len(session.messages),
            "summary_chars": len(summary),
        }

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

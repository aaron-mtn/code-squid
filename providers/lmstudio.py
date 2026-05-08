# providers/lmstudio.py

from openai import OpenAI

from .base import BaseProvider


class LMStudioProvider(BaseProvider):
    """Owns raw LM Studio API calls; must not own response normalization, agent policy, or tool execution."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key or "lm-studio",
        )

    def create_response(self, model: str, messages: list[dict], tools: list[dict]) -> object:
        return self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
        )
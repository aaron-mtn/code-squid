# core/hooks.py

"""Minimal in-process interceptor hook support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptContextBlock:
    title: str
    body: str
    source: str = ""


@dataclass(frozen=True)
class BeforeRunContext:
    session_id: str | None
    repo_root: str
    task: str
    skill_name: str | None = None
    allowed_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class BeforeModelTurnContext:
    session_id: str | None
    repo_root: str
    task: str
    messages: tuple[dict[str, Any], ...]
    tool_steps_used: int


@dataclass(frozen=True)
class RunHookDecision:
    block: bool = False
    reason: str = ""
    guidance: str = ""
    context_blocks: tuple[PromptContextBlock, ...] = ()


class HookRunner:
    def __init__(self, hooks: list[object] | None = None) -> None:
        self.hooks = hooks or []

    def before_run(self, ctx: BeforeRunContext) -> RunHookDecision:
        context_blocks: list[PromptContextBlock] = []

        for hook in self.hooks:
            handler = getattr(hook, "before_run", None)
            if handler is None:
                continue

            decision = handler(ctx)
            if decision is None:
                continue

            context_blocks.extend(decision.context_blocks)
            if decision.block:
                return RunHookDecision(
                    block=True,
                    reason=decision.reason,
                    guidance=decision.guidance,
                    context_blocks=tuple(context_blocks),
                )

        return RunHookDecision(context_blocks=tuple(context_blocks))

    def before_model_turn(self, ctx: BeforeModelTurnContext) -> list[PromptContextBlock]:
        context_blocks: list[PromptContextBlock] = []

        for hook in self.hooks:
            handler = getattr(hook, "before_model_turn", None)
            if handler is None:
                continue

            result = handler(ctx)
            if result is None:
                continue

            context_blocks.extend(_prompt_context_blocks(result))

        return context_blocks


def _prompt_context_blocks(value: object) -> tuple[PromptContextBlock, ...]:
    if isinstance(value, PromptContextBlock):
        return (value,)

    if isinstance(value, (list, tuple)):
        return tuple(value)

    return ()

# core/approval.py

"""Small UI-agnostic approval policy for tool actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


APPROVAL_NEVER = "never"
APPROVAL_ALWAYS = "always"
APPROVAL_GUARDED = "guarded"

USER_DENIED_TOOL_ACTION = "user denied tool action"


class ApprovalPrompter(Protocol):
    def approve_action(self, action: dict) -> "ApprovalDecision":
        """Return the user's approval decision for a tool action."""


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    instruction: str = ""
    reason: str = ""


class ApprovalPolicy:
    """Owns approval-mode decisions without depending on a UI implementation."""

    def __init__(self, mode: str, prompter: ApprovalPrompter | None = None) -> None:
        if mode not in {APPROVAL_NEVER, APPROVAL_ALWAYS, APPROVAL_GUARDED}:
            raise ValueError(f"Unknown approval mode: {mode}")

        self.mode = mode
        self.prompter = prompter

    def check(self, action: dict) -> ApprovalDecision:
        if self.mode == APPROVAL_NEVER:
            return ApprovalDecision(approved=True)

        if self.mode == APPROVAL_GUARDED and not action.get("approval_reason"):
            return ApprovalDecision(approved=True)

        if self.prompter is None:
            return ApprovalDecision(
                approved=False,
                reason="approval prompter required",
            )

        decision = self.prompter.approve_action(action)
        if isinstance(decision, bool):
            decision = ApprovalDecision(approved=decision)

        if decision.approved:
            return ApprovalDecision(approved=True)

        return ApprovalDecision(
            approved=False,
            instruction=decision.instruction,
            reason=decision.reason or USER_DENIED_TOOL_ACTION,
        )


def denied_result(action: dict, reason: str) -> dict:
    return {
        "ok": False,
        "tool": action.get("tool", ""),
        "error": reason,
    }

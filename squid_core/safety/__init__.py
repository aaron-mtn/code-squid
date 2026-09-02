"""Approval and preflight boundaries for tool execution."""

from .approval import (
    APPROVAL_ALWAYS,
    APPROVAL_GUARDED,
    APPROVAL_NEVER,
    USER_DENIED_TOOL_ACTION,
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalPrompter,
    denied_result,
)
from .preflight import ActionPreflight, ActionPreflightDecision

__all__ = [
    "APPROVAL_ALWAYS",
    "APPROVAL_GUARDED",
    "APPROVAL_NEVER",
    "USER_DENIED_TOOL_ACTION",
    "ActionPreflight",
    "ActionPreflightDecision",
    "ApprovalDecision",
    "ApprovalPolicy",
    "ApprovalPrompter",
    "denied_result",
]

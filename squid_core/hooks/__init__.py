"""Lifecycle hook types, execution, and metadata loading."""

from .loader import (
    HookInfo,
    HookLoadError,
    list_user_hooks,
    load_hook_infos,
    load_user_hooks,
    read_hook_info,
)
from .no_progress import (
    DEFAULT_REPEATED_FAILURE_THRESHOLD,
    RepeatedFailureNudge,
)
from .runner import (
    BeforeAcceptFinalContext,
    BeforeModelTurnContext,
    BeforeRunContext,
    BeforeToolExecuteContext,
    FinalHookDecision,
    FollowUpRunRequest,
    HookRunner,
    PromptContextBlock,
    RunFinishedContext,
    RunFinishedDecision,
    RunHookDecision,
    ToolHookDecision,
    ToolResultContext,
)

__all__ = [
    "BeforeAcceptFinalContext",
    "BeforeModelTurnContext",
    "BeforeRunContext",
    "BeforeToolExecuteContext",
    "FinalHookDecision",
    "FollowUpRunRequest",
    "HookInfo",
    "HookLoadError",
    "HookRunner",
    "PromptContextBlock",
    "DEFAULT_REPEATED_FAILURE_THRESHOLD",
    "RepeatedFailureNudge",
    "RunFinishedContext",
    "RunFinishedDecision",
    "RunHookDecision",
    "ToolHookDecision",
    "ToolResultContext",
    "list_user_hooks",
    "load_hook_infos",
    "load_user_hooks",
    "read_hook_info",
]

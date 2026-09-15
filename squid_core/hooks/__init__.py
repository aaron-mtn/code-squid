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
from .post_verification import (
    DEFAULT_POST_VERIFICATION_THRESHOLD,
    POST_VERIFICATION_GUIDANCE,
    PostVerificationNudge,
)
from .redundant_read import (
    DEFAULT_REPEATED_READ_THRESHOLD,
    SUBSTANTIAL_OVERLAP_RATIO,
    RepeatedReadNudge,
)
from .runner import (
    BeforeAcceptFinalContext,
    BeforeModelTurnContext,
    BeforeRunContext,
    BeforeToolExecuteContext,
    CompactionAppliedContext,
    FollowUpRunRequest,
    HookResponse,
    HookRunner,
    PromptContextBlock,
    ReadResultTrimmedContext,
    RunFinishedContext,
    ToolResultContext,
)

__all__ = [
    "BeforeAcceptFinalContext",
    "BeforeModelTurnContext",
    "BeforeRunContext",
    "BeforeToolExecuteContext",
    "CompactionAppliedContext",
    "FollowUpRunRequest",
    "HookInfo",
    "HookLoadError",
    "HookResponse",
    "HookRunner",
    "PromptContextBlock",
    "ReadResultTrimmedContext",
    "DEFAULT_POST_VERIFICATION_THRESHOLD",
    "POST_VERIFICATION_GUIDANCE",
    "PostVerificationNudge",
    "DEFAULT_REPEATED_FAILURE_THRESHOLD",
    "RepeatedFailureNudge",
    "DEFAULT_REPEATED_READ_THRESHOLD",
    "RepeatedReadNudge",
    "RunFinishedContext",
    "SUBSTANTIAL_OVERLAP_RATIO",
    "ToolResultContext",
    "list_user_hooks",
    "load_hook_infos",
    "load_user_hooks",
    "read_hook_info",
]

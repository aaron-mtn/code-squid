"""Presentation metadata for Code Squid's individually configurable hooks.

Desktop and CLI share this inventory; agent_setup still owns construction and
execution order. These entries are application policy, never Mod components.
"""

from code_squid.settings import DEFAULT_BUILT_IN_HOOK_SETTINGS, Settings


BUILT_IN_HOOKS = (
    {
        "id": "too_many_reads", "name": "Read activity guidance",
        "description": "Suggests making an edit after excessive reading without changes.",
        "events": ["before_run", "before_model_turn", "tool_result"],
    },
    {
        "id": "post_verification", "name": "Post-verification guidance",
        "description": "Encourages wrapping up after repeated successful verification.",
        "events": ["before_run", "before_model_turn", "tool_result"],
    },
    {
        "id": "repeated_failure", "name": "Repeated failure guidance",
        "description": "Suggests recovery when tools repeatedly fail.",
        "events": ["before_run", "tool_result"],
    },
)


def built_in_hooks_payload(settings: Settings) -> dict:
    """Expose effective states without importing or constructing runtime hooks."""
    enabled = DEFAULT_BUILT_IN_HOOK_SETTINGS | settings.runtime.built_in_hook_settings
    return {"hooks": [
        dict(hook, source="built_in", enabled=enabled[hook["id"]],
             default_enabled=DEFAULT_BUILT_IN_HOOK_SETTINGS[hook["id"]])
        for hook in BUILT_IN_HOOKS
    ]}

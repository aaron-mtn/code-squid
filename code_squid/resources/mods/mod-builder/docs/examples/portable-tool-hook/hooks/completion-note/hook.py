"""Canonical portable run-finished Hook paired with a bundled Tool."""

from squid_core.hooks import HookResponse


class CompletionNoteHook:
    def tool_result(self, context):
        # Add a model nudge without rewriting the measured Tool output.
        if context.action.get("tool") == "count-text" and context.result.get("ok"):
            return HookResponse(additional_context="Use the measured count when explaining the result.")
        return None

    def run_finished(self, context):
        return HookResponse(notes=("Portable example completed.",))


def create_hook(config=None):
    return CompletionNoteHook()

"""Canonical before-accept-final Hook used by authoring documentation."""

from squid_core.hooks import HookResponse


class FinalNoteHook:
    def before_accept_final(self, context):
        return HookResponse(report_note="Validated by the canonical example Hook.")


def create_hook(config=None):
    return FinalNoteHook()

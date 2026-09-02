"""Install the Squid Bell saved user hook example."""

from __future__ import annotations

from pathlib import Path

from core.app_paths import user_hooks_dir


HOOK_METADATA = """name: squid-bell
description: Visible example hook that marks runs and final reports when user hooks are enabled.
enabled: true
version: 1
"""

HOOK_SOURCE = '''from core.hooks import (
    FinalHookDecision,
    PromptContextBlock,
    RunFinishedDecision,
    RunHookDecision,
)


class SquidBellHook:
    def before_run(self, context):
        return RunHookDecision(
            context_blocks=(
                PromptContextBlock(
                    title="Squid Bell",
                    body="🦑 Squid Bell hook is active for this run.",
                    source="squid-bell",
                ),
            )
        )

    def before_accept_final(self, context):
        return FinalHookDecision(
            report_note="🦑 Squid Bell hook ran for this task."
        )

    def run_finished(self, context):
        return RunFinishedDecision(
            notes=("🦑 Squid Bell observed the run finishing.",)
        )


def create_hook(config=None):
    return SquidBellHook()
'''


def install_squid_bell_hook() -> Path:
    hook_dir = user_hooks_dir() / "squid-bell"
    hook_dir.mkdir(parents=True, exist_ok=True)
    (hook_dir / "hook.yaml").write_text(HOOK_METADATA, encoding="utf-8")
    (hook_dir / "hook.py").write_text(HOOK_SOURCE, encoding="utf-8")
    return hook_dir


def main() -> None:
    hook_dir = install_squid_bell_hook()
    print(f"Installed Squid Bell hook at: {hook_dir}")
    print("Run Code Squid with include_user_hooks=True to use it.")


if __name__ == "__main__":
    main()

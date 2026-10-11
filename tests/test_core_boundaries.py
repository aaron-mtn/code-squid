"""Architecture boundary checks for reusable and application-owned modules."""

import squid_core
import importlib
from pathlib import Path
import re
import subprocess
import sys


REUSABLE_MODULES = (
    "agent",
    "agent_loop",
    "compaction",
    "events",
    "generation",
    "hooks",
    "model_adapter",
    "mods",
    "platform_context",
    "providers",
    "settings",
    "spawner",
    "safety",
    "session",
    "skills",
    "storage",
    "tools",
)


def test_application_setup_has_no_agent_loop_compatibility_wrapper() -> None:
    from code_squid import agent_setup

    assert not hasattr(agent_setup, "build_agent_loop")


def test_application_setup_import_does_not_load_console_or_prompt_toolkit() -> None:
    workspace_root = Path(__file__).resolve().parents[1]
    script = """
import sys

class BlockFrontendImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "code_squid.console" or fullname.startswith("code_squid.console."):
            raise RuntimeError(f"console import attempted: {fullname}")
        if fullname == "prompt_toolkit" or fullname.startswith("prompt_toolkit."):
            raise RuntimeError(f"prompt_toolkit import attempted: {fullname}")
        return None

sys.meta_path.insert(0, BlockFrontendImports())
import code_squid.agent_setup
assert not any(
    name == "code_squid.console" or name.startswith("code_squid.console.")
    for name in sys.modules
)
assert not any(
    name == "prompt_toolkit" or name.startswith("prompt_toolkit.")
    for name in sys.modules
)
"""

    subprocess.run(
        [sys.executable, "-c", script],
        cwd=workspace_root,
        check=True,
    )


def test_code_squid_application_package_has_expected_layout() -> None:
    package_root = Path(__file__).resolve().parents[1] / "code_squid"
    relative_modules = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*.py")
    )

    assert relative_modules == [
        "__init__.py",
        "agent/__init__.py",
        "agent/prompts.py",
        "agent_setup.py",
        "app_paths.py",
        "compaction_context.py",
        "console/__init__.py",
        "console/cli/__init__.py",
        "console/cli/cli_commands.py",
        "console/cli/cli_options.py",
        "console/cli/control_commands.py",
        "console/cli/mod_commands.py",
        "console/cli/prompt_loop.py",
        "console/cli/runtime_commands.py",
        "console/cli/session_runner.py",
        "console/cli/skill_commands.py",
        "console/startup_menu.py",
        "console/ui/__init__.py",
        "console/ui/approval.py",
        "console/ui/banner.py",
        "console/ui/binary_header.py",
        "console/ui/composer_layout.py",
        "console/ui/display.py",
        "console/ui/formatting.py",
        "console/ui/header_layout.py",
        "console/ui/prompt_input.py",
        "console/ui/sessions.py",
        "console/ui/spinner.py",
        "console/ui/startup_application.py",
        "console/ui/streaming_narration.py",
        "console/ui/terminal_session.py",
        "console/ui/tool_display.py",
        "hooks/__init__.py",
        "hooks/no_progress.py",
        "hooks/post_verification.py",
        "hooks/too_many_reads.py",
        "mod_authoring.py",
        "mods.py",
        "provider_setup.py",
        "resources/mods/mod-builder/docs/examples/before-accept-final-hook/hooks/final-note/hook.py",
        "resources/mods/mod-builder/docs/examples/bundled-tool/tools/echo-value/tool.py",
        "resources/mods/mod-builder/docs/examples/portable-tool-hook/hooks/completion-note/hook.py",
        "resources/mods/mod-builder/docs/examples/portable-tool-hook/tools/count-text/tool.py",
        "resources/mods/mod-builder/tools/read-mod-authoring-example/tool.py",
        "resources/mods/mod-builder/tools/read-mod-authoring-guide/tool.py",
        "resources/mods/mod-builder/tools/scaffold-mod-component/tool.py",
        "resources/mods/mod-builder/tools/scaffold-mod-package/tool.py",
        "resources/mods/mod-builder/tools/validate-mod-package/tool.py",
        "settings.py",
    ]


def test_application_owns_only_default_selection_not_backend_policy():
    import code_squid
    from code_squid.settings import DEFAULT_PROVIDER
    from squid_providers import catalog
    from squid_providers.catalog import VALID_PROVIDERS
    assert DEFAULT_PROVIDER in VALID_PROVIDERS
    assert not hasattr(catalog, "DEFAULT_PROVIDER_ID")
    app_root = Path(code_squid.__file__).parent
    forbidden = tuple(VALID_PROVIDERS) + ("OpenAICompatibleProvider", "OllamaProvider")
    for path in app_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if path == app_root / "settings.py":
            # Selecting the application's initial backend belongs here. No
            # transport implementation or backend-specific branches do.
            declaration = f'DEFAULT_PROVIDER = "{DEFAULT_PROVIDER}"'
            assert source.count(declaration) == 1
            source = source.replace(declaration, "")
        assert not any(name in source for name in forbidden), path


def test_runtime_packages_are_external_to_application_checkout():
    import code_squid, squid_core, squid_providers
    app_root = Path(__file__).resolve().parents[1]
    assert not (app_root / "squid_core").exists()
    assert not (app_root / "squid_providers").exists()
    assert not Path(squid_core.__file__).resolve().is_relative_to(app_root)
    assert not Path(squid_providers.__file__).resolve().is_relative_to(app_root)

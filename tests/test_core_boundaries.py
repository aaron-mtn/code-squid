"""Architecture boundary checks for reusable and application-owned modules."""

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


def test_reusable_runtime_modules_import_from_squid_core() -> None:
    for module_name in REUSABLE_MODULES:
        module = importlib.import_module(f"squid_core.{module_name}")
        assert "squid_core" in Path(module.__file__).parts

    from squid_core.agent_loop import AgentLoop, RunResult
    from squid_core.compaction import Compactor

    assert Compactor.__module__ == "squid_core.compaction.compactor"
    assert AgentLoop.__module__ == "squid_core.agent_loop.loop"
    assert RunResult.__module__ == "squid_core.agent_loop.loop"


def test_subsystem_packages_expose_useful_public_seams() -> None:
    from squid_core.hooks import BeforeRunContext, HookRunner
    from squid_core.mods import (
        Mod,
        ResolvedMod,
        discover_mods,
        load_mod,
        resolve_mod,
        validate_mod,
    )
    from squid_core.safety import ActionPreflight, ApprovalPolicy
    from squid_core.tools import TOOLS, ToolExecutor, ToolResults
    from squid_core.tools.builtins import TOOLS as BUILTIN_TOOLS
    from squid_core.storage import SessionStore, UndoStore, write_error_log

    assert all((Mod, ResolvedMod, discover_mods, load_mod, resolve_mod, validate_mod))
    assert all((HookRunner, BeforeRunContext, ActionPreflight, ApprovalPolicy))
    assert all((ToolExecutor, ToolResults))
    assert all((SessionStore, UndoStore, write_error_log))
    assert TOOLS is BUILTIN_TOOLS


def test_events_remains_a_flat_observation_module() -> None:
    from squid_core import events

    source = Path(events.__file__).read_text(encoding="utf-8")
    assert "squid_core.hooks" not in source


def test_old_root_tool_package_is_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert not (repo_root / "tools").exists()


def test_old_core_runner_module_is_removed() -> None:
    package_root = Path(__file__).resolve().parents[1] / "squid_core"

    assert not (package_root / "runner.py").exists()


def test_old_flat_compaction_support_modules_are_removed() -> None:
    package_root = Path(__file__).resolve().parents[1] / "squid_core"

    assert not (package_root / "context_status.py").exists()
    assert not (package_root / "token_estimate.py").exists()


def test_old_provider_source_package_is_removed() -> None:
    provider_root = Path(__file__).resolve().parents[1] / "providers"

    assert not list(provider_root.glob("*.py"))


def test_top_level_storage_package_is_removed() -> None:
    storage_root = Path(__file__).resolve().parents[1] / "storage"

    assert not storage_root.exists()


def test_old_subsystem_import_paths_are_absent() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    stale_patterns = tuple(
        f"squid_core.{module_name}"
        for module_name in (
            "tool_executor",
            "tool_results",
            "user_tools",
            "action_preflight",
            "approval",
            "command_safety",
            "workspace_boundary",
            "hook_loader",
        )
    )

    violations = []
    for root_name in ("squid_core", "code_squid", "providers", "storage", "tests"):
        for source_path in (repo_root / root_name).rglob("*.py"):
            if source_path == Path(__file__).resolve():
                continue
            source = source_path.read_text(encoding="utf-8")
            if any(pattern in source for pattern in stale_patterns):
                violations.append(source_path.relative_to(repo_root).as_posix())

    assert violations == []


def test_squid_core_has_no_code_squid_application_imports() -> None:
    package_root = Path(__file__).resolve().parents[1] / "squid_core"
    forbidden = (
        re.compile(r"^\s*(?:from|import)\s+code_squid(?:\.|\s|$)", re.MULTILINE),
    )

    violations = []
    for source_path in package_root.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if any(pattern.search(source) for pattern in forbidden):
            violations.append(source_path.relative_to(package_root).as_posix())

    assert violations == []


def test_squid_core_storage_has_no_application_path_or_environment_policy() -> None:
    storage_root = Path(__file__).resolve().parents[1] / "squid_core" / "storage"
    forbidden = (".code-squid", "CODE_SQUID_", "code_squid.app_paths", "cli.", "ui.")

    violations = []
    for source_path in storage_root.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if any(pattern in source for pattern in forbidden):
            violations.append(source_path.relative_to(storage_root).as_posix())

    assert violations == []


def test_old_application_packages_are_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    for package_name in ("agent", "cli", "config", "core", "ui"):
        assert not (repo_root / package_name).exists()


def test_repo_root_bundled_skills_are_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    assert not (repo_root / "skills").exists()


def test_application_setup_has_no_agent_loop_compatibility_wrapper() -> None:
    from code_squid import agent_setup

    assert not hasattr(agent_setup, "build_agent_loop")


def test_application_setup_import_does_not_load_console_or_prompt_toolkit() -> None:
    repo_root = Path(__file__).resolve().parents[1]
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
        cwd=repo_root,
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
        "agent/coding.py",
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
        "console/ui/tool_display.py",
        "provider_setup.py",
        "settings.py",
    ]



def test_generic_core_imports_do_not_initialize_concrete_transports() -> None:
    # Use a fresh process: application test imports may already have loaded SDKs.
    script = """
import sys
class BlockTransports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"squid_core.providers.ollama", "squid_core.providers.openai_compatible", "openai", "httpx"}:
            raise AssertionError(f"concrete transport dependency imported: {fullname}")
        return None
sys.meta_path.insert(0, BlockTransports())
from squid_core.providers import BaseProvider, StreamCancelled
import squid_core.spawner
import squid_core.generation
assert BaseProvider and StreamCancelled
"""
    subprocess.run([sys.executable, "-c", script], check=True,
                   cwd=Path(__file__).resolve().parents[1])


def test_core_does_not_select_or_construct_concrete_providers() -> None:
    core_root = Path(__file__).resolve().parents[1] / "squid_core"
    violations = []
    for path in core_root.rglob("*.py"):
        # Transports stay physically in Core for this patch, but nothing else
        # may depend on them. Their protocol behavior is deliberately unchanged.
        if "providers" in path.relative_to(core_root).parts:
            continue
        source = path.read_text(encoding="utf-8")
        if any(name in source for name in (
            "build_provider", "OpenAICompatibleProvider", "OllamaProvider",
            "squid_core.providers.openai_compatible", "squid_core.providers.ollama",
        )):
            violations.append(path.relative_to(core_root).as_posix())
    assert violations == []

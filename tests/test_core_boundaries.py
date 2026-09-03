import importlib
from pathlib import Path
import re


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

    from squid_core.compaction import Compactor

    assert Compactor.__module__ == "squid_core.compaction.compactor"


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
        "console/__init__.py",
        "console/cli/__init__.py",
        "console/cli/cli_commands.py",
        "console/cli/cli_options.py",
        "console/cli/prompt_loop.py",
        "console/cli/session_runner.py",
        "console/cli/skill_commands.py",
        "console/ui/__init__.py",
        "console/ui/approval.py",
        "console/ui/banner.py",
        "console/ui/display.py",
        "console/ui/formatting.py",
        "console/ui/prompt_input.py",
        "console/ui/sessions.py",
        "console/ui/spinner.py",
        "console/ui/tool_display.py",
        "settings.py",
    ]

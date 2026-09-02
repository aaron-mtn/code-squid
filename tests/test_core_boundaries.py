import importlib
from pathlib import Path
import re


REUSABLE_MODULES = (
    "agent",
    "agent_loop",
    "compaction",
    "context_status",
    "events",
    "generation",
    "hooks",
    "model_adapter",
    "mods",
    "platform_context",
    "spawner",
    "safety",
    "session",
    "skills",
    "token_estimate",
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

    assert all((Mod, ResolvedMod, discover_mods, load_mod, resolve_mod, validate_mod))
    assert all((HookRunner, BeforeRunContext, ActionPreflight, ApprovalPolicy))
    assert all((ToolExecutor, ToolResults))
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
    for root_name in ("squid_core", "core", "cli", "providers", "storage", "ui", "tests"):
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
        re.compile(r"^\s*(?:from|import)\s+agent\.prompts\b", re.MULTILINE),
        re.compile(r"^\s*(?:from|import)\s+ui\.terminal\b", re.MULTILINE),
        re.compile(r"^\s*(?:from|import)\s+core\.(?:app_paths|runner)\b", re.MULTILINE),
        re.compile(r"^\s*(?:from|import)\s+cli(?:\.|\s|$)", re.MULTILINE),
    )

    violations = []
    for source_path in package_root.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if any(pattern.search(source) for pattern in forbidden):
            violations.append(source_path.relative_to(package_root).as_posix())

    assert violations == []


def test_transitional_core_contains_only_application_owned_modules() -> None:
    core_root = Path(__file__).resolve().parents[1] / "core"

    assert sorted(path.name for path in core_root.glob("*.py")) == [
        "app_paths.py",
        "runner.py",
    ]

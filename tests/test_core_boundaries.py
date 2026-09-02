import importlib
from pathlib import Path
import re


REUSABLE_MODULES = (
    "action_preflight",
    "agent_loop",
    "approval",
    "command_safety",
    "context_status",
    "events",
    "generation",
    "hook_loader",
    "hooks",
    "model_adapter",
    "mods",
    "platform_context",
    "session",
    "skills",
    "token_estimate",
    "tool_executor",
    "tool_results",
    "user_tools",
    "workspace_boundary",
)


def test_reusable_runtime_modules_import_from_squid_core() -> None:
    for module_name in REUSABLE_MODULES:
        module = importlib.import_module(f"squid_core.{module_name}")
        assert "squid_core" in Path(module.__file__).parts

    from squid_core.compaction import Compactor

    assert Compactor.__module__ == "squid_core.compaction.compactor"


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

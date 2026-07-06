from pathlib import Path

from core.extension_paths import CODE_SQUID_HOME_ENV
from core.extensions import (
    Extension,
    discover_extensions,
    get_active_extension,
    get_active_extension_name,
    load_extension,
    set_active_extension,
)


def _write_extension(
    extensions_dir: Path,
    directory_name: str,
    metadata: str,
) -> Path:
    extension_dir = extensions_dir / directory_name
    extension_dir.mkdir(parents=True)
    (extension_dir / "extension.yaml").write_text(metadata, encoding="utf-8")
    return extension_dir


def _write_valid_files(extension_dir: Path) -> None:
    (extension_dir / "skills" / "repo-inspector").mkdir(parents=True)
    (extension_dir / "skills" / "repo-inspector" / "SKILL.md").write_text(
        "skill",
        encoding="utf-8",
    )
    (extension_dir / "tools" / "line_count").mkdir(parents=True)
    (extension_dir / "tools" / "line_count" / "tool.yaml").write_text(
        "name: line_count\n",
        encoding="utf-8",
    )
    (extension_dir / "hooks" / "squid-bell").mkdir(parents=True)
    (extension_dir / "hooks" / "squid-bell" / "hook.yaml").write_text(
        "name: squid-bell\n",
        encoding="utf-8",
    )
    (extension_dir / "hooks" / "squid-bell" / "hook.py").write_text(
        "def create_hook(config=None):\n    return None\n",
        encoding="utf-8",
    )


def test_missing_extensions_dir_returns_empty_dict(tmp_path: Path) -> None:
    assert discover_extensions(tmp_path / "missing") == {}


def test_valid_extension_yaml_loads_metadata(tmp_path: Path) -> None:
    extension_dir = _write_extension(
        tmp_path,
        "repo-inspector",
        """name: repo-inspector
title: Repo Inspector
description: Inspect repositories with repo-aware tools.
version: 0.1.0
default_skill: repo-inspector
skills:
  - repo-inspector
tools:
  - line_count
hooks:
  - squid-bell
""",
    )
    _write_valid_files(extension_dir)

    extension = load_extension(extension_dir)

    assert extension == Extension(
        name="repo-inspector",
        title="Repo Inspector",
        description="Inspect repositories with repo-aware tools.",
        version="0.1.0",
        default_skill="repo-inspector",
        skills=("repo-inspector",),
        tools=("line_count",),
        hooks=("squid-bell",),
        path=extension_dir,
    )


def test_title_defaults_to_name(tmp_path: Path) -> None:
    extension_dir = _write_extension(tmp_path, "minimal", "name: minimal\n")

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.title == "minimal"


def test_optional_fields_default_correctly(tmp_path: Path) -> None:
    extension_dir = _write_extension(tmp_path, "minimal", "name: minimal\n")

    extension = load_extension(extension_dir)

    assert extension == Extension(
        name="minimal",
        title="minimal",
        description="",
        version="",
        default_skill=None,
        skills=(),
        tools=(),
        hooks=(),
        path=extension_dir,
    )


def test_invalid_name_is_invalid_with_errors(tmp_path: Path) -> None:
    extension_dir = _write_extension(tmp_path, "BadName", "name: BadName\n")

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.valid is False
    assert any("extension name must contain only" in error for error in extension.errors)


def test_name_folder_mismatch_is_invalid(tmp_path: Path) -> None:
    extension_dir = _write_extension(tmp_path, "folder-name", "name: yaml-name\n")

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.valid is False
    assert any("must match folder name" in error for error in extension.errors)


def test_malformed_yaml_does_not_crash_discovery(tmp_path: Path) -> None:
    _write_extension(tmp_path, "broken", "name broken\n")

    discovered = discover_extensions(tmp_path)

    assert discovered["broken"].valid is False
    assert discovered["broken"].errors


def test_malformed_individual_extension_does_not_prevent_valid_load(
    tmp_path: Path,
) -> None:
    _write_extension(tmp_path, "broken", "name broken\n")
    _write_extension(tmp_path, "valid", "name: valid\n")

    discovered = discover_extensions(tmp_path)

    assert discovered["broken"].valid is False
    assert discovered["valid"].valid is True


def test_discover_extensions_uses_custom_state_path_for_active_flag(
    tmp_path: Path,
) -> None:
    extensions_dir = tmp_path / "extensions"
    extension_dir = _write_extension(extensions_dir, "active", "name: active\n")
    _write_extension(extensions_dir, "inactive", "name: inactive\n")
    state_path = tmp_path / "custom-state.json"
    set_active_extension("active", state_path)

    discovered = discover_extensions(extensions_dir, state_path=state_path)

    assert discovered["active"].path == extension_dir
    assert discovered["active"].active is True
    assert discovered["inactive"].active is False


def test_discover_extensions_custom_state_path_ignores_default_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    extensions_dir = tmp_path / "extensions"
    _write_extension(extensions_dir, "custom-active", "name: custom-active\n")
    _write_extension(extensions_dir, "default-active", "name: default-active\n")
    set_active_extension("default-active")
    custom_state_path = tmp_path / "custom-state.json"
    set_active_extension("custom-active", custom_state_path)

    discovered = discover_extensions(extensions_dir, state_path=custom_state_path)

    assert discovered["custom-active"].active is True
    assert discovered["default-active"].active is False


def test_default_skill_must_exist_in_skills(tmp_path: Path) -> None:
    extension_dir = _write_extension(
        tmp_path,
        "example",
        "name: example\ndefault_skill: missing\nskills: []\n",
    )

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.valid is False
    assert any("default_skill" in error for error in extension.errors)


def test_listed_skill_must_have_skill_file(tmp_path: Path) -> None:
    extension_dir = _write_extension(
        tmp_path,
        "example",
        "name: example\nskills:\n  - missing\n",
    )

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.valid is False
    assert any("SKILL.md" in error for error in extension.errors)


def test_listed_tool_must_have_tool_yaml(tmp_path: Path) -> None:
    extension_dir = _write_extension(
        tmp_path,
        "example",
        "name: example\ntools:\n  - missing\n",
    )

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.valid is False
    assert any("tool.yaml" in error for error in extension.errors)


def test_listed_hook_must_have_hook_yaml(tmp_path: Path) -> None:
    extension_dir = _write_extension(
        tmp_path,
        "example",
        "name: example\nhooks:\n  - missing\n",
    )

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.valid is False
    assert any("hook.yaml" in error for error in extension.errors)


def test_listed_hook_must_have_hook_py(tmp_path: Path) -> None:
    extension_dir = _write_extension(
        tmp_path,
        "example",
        "name: example\nhooks:\n  - missing\n",
    )
    hook_dir = extension_dir / "hooks" / "missing"
    hook_dir.mkdir(parents=True)
    (hook_dir / "hook.yaml").write_text("name: missing\n", encoding="utf-8")

    extension = load_extension(extension_dir)

    assert extension is not None
    assert extension.valid is False
    assert any("hook.py" in error for error in extension.errors)


def test_active_state_missing_file_returns_none(tmp_path: Path) -> None:
    assert get_active_extension_name(tmp_path / "missing.json") is None


def test_active_state_can_be_set_to_extension_name_and_cleared(tmp_path: Path) -> None:
    state_path = tmp_path / "extension-state.json"

    set_active_extension("repo-inspector", state_path)
    assert get_active_extension_name(state_path) == "repo-inspector"

    set_active_extension(None, state_path)
    assert get_active_extension_name(state_path) is None


def test_malformed_active_state_json_returns_none(tmp_path: Path) -> None:
    state_path = tmp_path / "extension-state.json"
    state_path.write_text("{bad", encoding="utf-8")

    assert get_active_extension_name(state_path) is None


def test_get_active_extension_returns_active_extension_with_active_true(
    tmp_path: Path,
) -> None:
    extension_dir = _write_extension(tmp_path / "extensions", "active", "name: active\n")
    state_path = tmp_path / "extension-state.json"
    set_active_extension("active", state_path)

    extension = get_active_extension(tmp_path / "extensions", state_path)

    assert extension is not None
    assert extension.path == extension_dir
    assert extension.active is True


def test_get_active_extension_returns_none_for_missing_active_extension(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "extension-state.json"
    set_active_extension("missing", state_path)

    assert get_active_extension(tmp_path / "extensions", state_path) is None

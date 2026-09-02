from pathlib import Path

from core.app_paths import (
    CODE_SQUID_HOME_ENV,
    CODE_SQUID_SESSION_INDEXES_ENV,
    code_squid_home,
    ensure_user_resource_dirs,
    session_indexes_path,
    user_hooks_dir,
    user_mods_dir,
    user_skills_dir,
    user_tools_dir,
    workspace_sessions_dir,
    workspace_state_dir,
    workspace_undo_dir,
)


def test_default_home_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(CODE_SQUID_HOME_ENV, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert code_squid_home() == tmp_path / ".code-squid"


def test_explicit_app_home_wins_over_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "environment"))
    explicit = tmp_path / "explicit"
    assert code_squid_home(explicit) == explicit
    assert user_mods_dir(explicit) == explicit / "mods"


def test_resource_paths_use_configured_home(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "custom-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    assert user_skills_dir() == home / "skills"
    assert user_hooks_dir() == home / "hooks"
    assert user_tools_dir() == home / "tools"
    assert user_mods_dir() == home / "mods"
    assert not home.exists()


def test_ensure_resource_dirs_creates_canonical_layout(tmp_path: Path) -> None:
    home = tmp_path / "home"
    ensure_user_resource_dirs(home)
    assert {path.name for path in home.iterdir()} == {"skills", "hooks", "tools", "mods"}


def test_env_path_expands_user_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, "~/custom-code-squid")
    assert code_squid_home() == tmp_path / "custom-code-squid"


def test_workspace_storage_paths_are_application_owned(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    assert workspace_state_dir(tmp_path) == root / ".code-squid"
    assert workspace_sessions_dir(tmp_path) == root / ".code-squid" / "sessions"
    assert workspace_undo_dir(tmp_path) == root / ".code-squid" / "undo"


def test_session_index_path_uses_override(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "indexes.jsonl"
    monkeypatch.setenv(CODE_SQUID_SESSION_INDEXES_ENV, str(configured))
    assert session_indexes_path() == configured

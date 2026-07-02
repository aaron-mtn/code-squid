from pathlib import Path

from core.extension_paths import (
    CODE_SQUID_HOME_ENV,
    code_squid_home,
    ensure_user_extension_dirs,
    user_hooks_dir,
    user_skills_dir,
    user_tools_dir,
)


def test_default_home_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(CODE_SQUID_HOME_ENV, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert code_squid_home() == tmp_path / ".code-squid"


def test_env_override_places_extension_dirs_under_temp_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "custom-home"))

    assert code_squid_home() == tmp_path / "custom-home"
    assert user_skills_dir() == tmp_path / "custom-home" / "skills"
    assert user_hooks_dir() == tmp_path / "custom-home" / "hooks"
    assert user_tools_dir() == tmp_path / "custom-home" / "tools"


def test_getters_do_not_create_directories(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "extension-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))

    assert user_skills_dir() == home / "skills"
    assert user_hooks_dir() == home / "hooks"
    assert user_tools_dir() == home / "tools"
    assert not home.exists()


def test_ensure_user_extension_dirs_creates_standard_dirs(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "extension-home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))

    ensure_user_extension_dirs()

    assert (home / "skills").is_dir()
    assert (home / "hooks").is_dir()
    assert (home / "tools").is_dir()


def test_env_path_expands_user_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, "~/custom-code-squid")

    assert code_squid_home() == tmp_path / "custom-code-squid"

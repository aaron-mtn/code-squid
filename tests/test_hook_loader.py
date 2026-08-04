from pathlib import Path

import pytest

from core.extension_paths import CODE_SQUID_HOME_ENV
from core.extensions import set_active_extension
from core.hook_loader import (
    HookInfo,
    HookLoadError,
    list_user_hooks,
    load_hook_infos,
    load_user_hooks,
)


def _write_hook(
    hooks_dir: Path,
    directory_name: str,
    metadata: str,
    source: str = "def create_hook(config=None):\n    return config\n",
) -> Path:
    hook_dir = hooks_dir / directory_name
    hook_dir.mkdir(parents=True)
    (hook_dir / "hook.yaml").write_text(metadata, encoding="utf-8")
    (hook_dir / "hook.py").write_text(source, encoding="utf-8")
    return hook_dir


def _write_extension_hook(
    home: Path,
    extension_name: str,
    hook_name: str,
    metadata: str | None = None,
    source: str = "def create_hook(config=None):\n    return config\n",
    *,
    extension_metadata: str | None = None,
) -> Path:
    extension_dir = home / "extensions" / extension_name
    extension_dir.mkdir(parents=True, exist_ok=True)
    (extension_dir / "extension.yaml").write_text(
        extension_metadata
        or f"""name: {extension_name}
hooks:
  - {hook_name}
""",
        encoding="utf-8",
    )
    hook_dir = extension_dir / "hooks" / hook_name
    hook_dir.mkdir(parents=True)
    (hook_dir / "hook.yaml").write_text(
        metadata or f"name: {hook_name}\n",
        encoding="utf-8",
    )
    (hook_dir / "hook.py").write_text(source, encoding="utf-8")
    return hook_dir


def test_missing_hooks_dir_returns_empty_lists(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"

    assert list_user_hooks(hooks_dir) == []
    assert load_user_hooks(hooks_dir) == []


def test_list_enabled_hook_metadata(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    hook_dir = _write_hook(
        hooks_dir,
        "example",
        """name: verification-guard
description: Blocks final responses unless verification is mentioned.
enabled: true
version: 2
""",
    )

    assert list_user_hooks(hooks_dir) == [
        HookInfo(
            name="verification-guard",
            description="Blocks final responses unless verification is mentioned.",
            enabled=True,
            version=2,
            path=hook_dir,
            source="user",
        )
    ]


def test_disabled_hook_is_listed_but_not_loaded(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    _write_hook(
        hooks_dir,
        "disabled",
        """name: disabled
enabled: false
version: 1
""",
        "raise AssertionError('disabled hook should not import')\n",
    )

    hooks = list_user_hooks(hooks_dir)

    assert hooks[0].enabled is False
    assert load_user_hooks(hooks_dir) == []


def test_enabled_hook_loads(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    _write_hook(
        hooks_dir,
        "enabled",
        "name: enabled\nenabled: true\n",
        """
class ExampleHook:
    marker = "loaded"

def create_hook(config=None):
    return ExampleHook()
""",
    )

    hooks = load_user_hooks(hooks_dir)

    assert len(hooks) == 1
    assert hooks[0].marker == "loaded"


def test_selected_hook_info_loads_through_public_api(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    _write_hook(
        hooks_dir,
        "selected",
        "name: selected\nenabled: true\n",
        "def create_hook(config=None):\n    return 'selected:' + config['source']\n",
    )
    info = list_user_hooks(hooks_dir)[0]

    assert load_hook_infos([info]) == ["selected:user"]


def test_hook_metadata_listing_does_not_import_source(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    marker = tmp_path / "imported"
    _write_hook(
        hooks_dir,
        "passive",
        "name: passive\nenabled: true\n",
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n"
        "def create_hook(config=None):\n    return object()\n",
    )

    infos = list_user_hooks(hooks_dir)

    assert [info.name for info in infos] == ["passive"]
    assert not marker.exists()
    assert len(load_hook_infos(infos)) == 1
    assert marker.exists()


def test_factory_receives_config(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    hook_dir = _write_hook(
        hooks_dir,
        "configured",
        """name: configured
description: Uses metadata.
enabled: true
version: 3
""",
    )

    hooks = load_user_hooks(hooks_dir)

    assert hooks == [
        {
            "name": "configured",
            "description": "Uses metadata.",
            "enabled": True,
            "version": 3,
            "path": hook_dir,
            "source": "user",
        }
    ]


def test_factory_without_config_still_works(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    _write_hook(
        hooks_dir,
        "no-config",
        "name: no-config\nenabled: true\n",
        "def create_hook():\n    return 'loaded without config'\n",
    )

    assert load_user_hooks(hooks_dir) == ["loaded without config"]


def test_missing_create_hook_raises(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    _write_hook(
        hooks_dir,
        "missing-factory",
        "name: missing-factory\nenabled: true\n",
        "VALUE = 1\n",
    )

    with pytest.raises(HookLoadError, match="missing callable create_hook"):
        load_user_hooks(hooks_dir)


def test_malformed_metadata_raises(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    _write_hook(
        hooks_dir,
        "bad",
        "name bad\nenabled: true\n",
    )

    with pytest.raises(HookLoadError, match="invalid metadata line"):
        list_user_hooks(hooks_dir)


def test_deterministic_load_order(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    _write_hook(
        hooks_dir,
        "b-hook",
        "name: b-hook\nenabled: true\n",
        "def create_hook(config=None):\n    return config['name']\n",
    )
    _write_hook(
        hooks_dir,
        "a-hook",
        "name: a-hook\nenabled: true\n",
        "def create_hook(config=None):\n    return config['name']\n",
    )

    assert load_user_hooks(hooks_dir) == ["a-hook", "b-hook"]


def test_no_active_extension_leaves_default_hook_loading_unchanged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_hook(
        home / "hooks",
        "loose",
        "name: loose\nenabled: true\n",
        "def create_hook(config=None):\n    return config['name']\n",
    )
    _write_extension_hook(home, "repo-inspector", "squid-bell")

    assert load_user_hooks() == ["loose"]


def test_active_valid_extension_hook_loads(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    hook_dir = _write_extension_hook(
        home,
        "repo-inspector",
        "squid-bell",
        "name: squid-bell\ndescription: Bell.\nenabled: false\nversion: 2\n",
    )
    set_active_extension("repo-inspector")

    hooks = load_user_hooks()

    assert hooks == [
        {
            "name": "squid-bell",
            "description": "Bell.",
            "enabled": True,
            "version": 2,
            "path": hook_dir,
            "source": "extension",
        }
    ]


def test_inactive_extension_hook_does_not_load(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension_hook(
        home,
        "repo-inspector",
        "squid-bell",
        source="raise AssertionError('inactive hook should not import')\n",
    )

    assert load_user_hooks() == []


def test_invalid_active_extension_hook_does_not_load(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    extension_dir = home / "extensions" / "repo-inspector"
    extension_dir.mkdir(parents=True)
    (extension_dir / "extension.yaml").write_text(
        """name: repo-inspector
hooks:
  - missing
""",
        encoding="utf-8",
    )
    set_active_extension("repo-inspector")

    assert load_user_hooks() == []


def test_unlisted_extension_hook_folder_does_not_load(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    extension_dir = home / "extensions" / "repo-inspector"
    extension_dir.mkdir(parents=True)
    (extension_dir / "extension.yaml").write_text(
        "name: repo-inspector\nhooks: []\n",
        encoding="utf-8",
    )
    hook_dir = extension_dir / "hooks" / "unlisted"
    hook_dir.mkdir(parents=True)
    (hook_dir / "hook.yaml").write_text("name: unlisted\n", encoding="utf-8")
    (hook_dir / "hook.py").write_text(
        "raise AssertionError('unlisted hook should not import')\n",
        encoding="utf-8",
    )
    set_active_extension("repo-inspector")

    assert load_user_hooks() == []


def test_missing_listed_extension_hook_is_ignored_when_extension_invalid(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_hook(
        home / "hooks",
        "loose",
        "name: loose\nenabled: true\n",
        "def create_hook(config=None):\n    return config['name']\n",
    )
    extension_dir = home / "extensions" / "repo-inspector"
    extension_dir.mkdir(parents=True)
    (extension_dir / "extension.yaml").write_text(
        """name: repo-inspector
hooks:
  - missing
""",
        encoding="utf-8",
    )
    set_active_extension("repo-inspector")

    assert load_user_hooks() == ["loose"]


def test_loose_user_hooks_load_before_active_extension_hooks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_hook(
        home / "hooks",
        "loose",
        "name: loose\nenabled: true\n",
        "def create_hook(config=None):\n    return config['source'] + ':' + config['name']\n",
    )
    _write_extension_hook(
        home,
        "repo-inspector",
        "squid-bell",
        source="def create_hook(config=None):\n    return config['source'] + ':' + config['name']\n",
    )
    set_active_extension("repo-inspector")

    assert load_user_hooks() == ["user:loose", "extension:squid-bell"]


def test_loose_user_hook_name_wins_over_active_extension_duplicate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_hook(
        home / "hooks",
        "duplicate",
        "name: duplicate\nenabled: true\n",
        "def create_hook(config=None):\n    return 'loose'\n",
    )
    _write_extension_hook(
        home,
        "repo-inspector",
        "duplicate",
        source="def create_hook(config=None):\n    return 'extension'\n",
    )
    set_active_extension("repo-inspector")

    assert load_user_hooks() == ["loose"]

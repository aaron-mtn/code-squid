from pathlib import Path

import pytest

from core.hook_loader import HookInfo, HookLoadError, list_user_hooks, load_user_hooks


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

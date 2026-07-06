from pathlib import Path

from cli.commands import run_cli
from core.extension_paths import CODE_SQUID_HOME_ENV
from core.extensions import get_active_extension_name, set_active_extension


def _write_extension(
    home: Path,
    name: str,
    *,
    title: str | None = None,
    description: str = "",
    valid: bool = True,
) -> Path:
    extension_dir = home / "extensions" / name
    extension_dir.mkdir(parents=True)
    lines = [f"name: {name}"]
    if title is not None:
        lines.append(f"title: {title}")
    if description:
        lines.append(f"description: {description}")
    if not valid:
        lines.extend(["skills:", "  - missing"])
    (extension_dir / "extension.yaml").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return extension_dir


def test_extensions_list_with_no_extensions(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))

    assert run_cli(["--cwd", str(tmp_path), "extensions", "list"]) == 0

    assert capsys.readouterr().out == "No extensions found.\n"


def test_extensions_list_shows_valid_inactive_extension(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "repo-inspector", title="Repo Inspector")

    assert run_cli(["--cwd", str(tmp_path), "extensions", "list"]) == 0

    assert capsys.readouterr().out == (
        "repo-inspector  inactive  valid  Repo Inspector\n"
    )


def test_extensions_list_uses_description_without_explicit_title(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(
        home,
        "repo-inspector",
        description="Inspect repositories with repo-aware tools.",
    )

    assert run_cli(["--cwd", str(tmp_path), "extensions", "list"]) == 0

    assert capsys.readouterr().out == (
        "repo-inspector  inactive  valid  Inspect repositories with repo-aware tools.\n"
    )


def test_extensions_list_marks_active_extension(monkeypatch, tmp_path, capsys) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "repo-inspector", title="Repo Inspector")
    set_active_extension("repo-inspector")

    assert run_cli(["--cwd", str(tmp_path), "extensions", "list"]) == 0

    assert capsys.readouterr().out == "repo-inspector  active  valid  Repo Inspector\n"


def test_extensions_list_shows_invalid_extension(monkeypatch, tmp_path, capsys) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "memory", title="Memory", valid=False)

    assert run_cli(["--cwd", str(tmp_path), "extensions", "list"]) == 0

    assert capsys.readouterr().out == "memory  inactive  invalid  Memory\n"


def test_extensions_active_with_no_active_extension(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))

    assert run_cli(["--cwd", str(tmp_path), "extensions", "active"]) == 0

    assert capsys.readouterr().out == "No active extension.\n"


def test_extensions_active_with_existing_active_extension(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "repo-inspector")
    set_active_extension("repo-inspector")

    assert run_cli(["--cwd", str(tmp_path), "extensions", "active"]) == 0

    assert capsys.readouterr().out == "Active extension: repo-inspector\n"


def test_extensions_active_state_points_to_missing_extension(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))
    set_active_extension("repo-inspector")

    assert run_cli(["--cwd", str(tmp_path), "extensions", "active"]) == 0

    assert capsys.readouterr().out == (
        "Active extension is set to 'repo-inspector', but it was not found.\n"
    )


def test_extensions_activate_valid_extension_writes_state(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "repo-inspector")

    assert (
        run_cli(["--cwd", str(tmp_path), "extensions", "activate", "repo-inspector"])
        == 0
    )

    assert get_active_extension_name() == "repo-inspector"
    assert capsys.readouterr().out == "Activated extension: repo-inspector\n"


def test_extensions_activate_invalid_extension_refuses_and_leaves_state_unchanged(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "repo-inspector")
    _write_extension(home, "memory", valid=False)
    set_active_extension("repo-inspector")

    assert (
        run_cli(["--cwd", str(tmp_path), "extensions", "activate", "memory"])
        == 1
    )

    output = capsys.readouterr().out
    assert output.startswith("Extension memory is invalid:\n- ")
    assert "SKILL.md" in output
    assert get_active_extension_name() == "repo-inspector"


def test_extensions_activate_unknown_extension_returns_failure(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))

    assert (
        run_cli(["--cwd", str(tmp_path), "extensions", "activate", "missing"])
        == 1
    )

    assert capsys.readouterr().out == "Unknown extension: missing\n"


def test_extensions_deactivate_clears_state(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))
    set_active_extension("repo-inspector")

    assert run_cli(["--cwd", str(tmp_path), "extensions", "deactivate"]) == 0

    assert get_active_extension_name() is None
    assert capsys.readouterr().out == "Deactivated extension.\n"


def test_extensions_validate_valid_extension(monkeypatch, tmp_path, capsys) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "repo-inspector")

    assert (
        run_cli(["--cwd", str(tmp_path), "extensions", "validate", "repo-inspector"])
        == 0
    )

    assert capsys.readouterr().out == "Extension repo-inspector is valid.\n"


def test_extensions_validate_invalid_extension_with_errors(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(home))
    _write_extension(home, "memory", valid=False)

    assert (
        run_cli(["--cwd", str(tmp_path), "extensions", "validate", "memory"])
        == 1
    )

    output = capsys.readouterr().out
    assert output.startswith("Extension memory is invalid:\n- ")
    assert "SKILL.md" in output


def test_extensions_validate_unknown_extension(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))

    assert (
        run_cli(["--cwd", str(tmp_path), "extensions", "validate", "missing"])
        == 1
    )

    assert capsys.readouterr().out == "Unknown extension: missing\n"


def test_extensions_deactivate_with_no_active_extension(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    monkeypatch.setenv(CODE_SQUID_HOME_ENV, str(tmp_path / "home"))

    assert run_cli(["--cwd", str(tmp_path), "extensions", "deactivate"]) == 0

    assert capsys.readouterr().out == "No active extension.\n"

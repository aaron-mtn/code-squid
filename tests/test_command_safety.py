from pathlib import Path

from squid_core.command_safety import (
    MUTATING_COMMAND_REASON,
    NOT_ALLOWLISTED_REASON,
    OUTSIDE_PATH_REASON,
    SHELL_SYNTAX_REASON,
    guarded_run_command_reason,
)


def test_pwd_allowed(tmp_path: Path) -> None:
    assert guarded_run_command_reason("pwd", tmp_path) is None


def test_ls_allowed(tmp_path: Path) -> None:
    assert guarded_run_command_reason("ls", tmp_path) is None


def test_rg_inside_workspace_allowed(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("print('ok')\n", encoding="utf-8")

    assert guarded_run_command_reason("rg ok app.py", tmp_path) is None


def test_pytest_allowed(tmp_path: Path) -> None:
    assert guarded_run_command_reason("pytest -q", tmp_path) is None


def test_python_m_pytest_allowed(tmp_path: Path) -> None:
    assert guarded_run_command_reason("python -m pytest -q", tmp_path) is None


def test_node_check_inside_workspace_allowed(tmp_path: Path) -> None:
    script = tmp_path / "app.js"
    script.write_text("const ok = true;\n", encoding="utf-8")

    assert guarded_run_command_reason("node --check app.js", tmp_path) is None


def test_unknown_command_requires_approval(tmp_path: Path) -> None:
    assert guarded_run_command_reason("cat README.md", tmp_path) == NOT_ALLOWLISTED_REASON


def test_mkdir_requires_approval(tmp_path: Path) -> None:
    assert (
        guarded_run_command_reason("mkdir test_guarded", tmp_path)
        == MUTATING_COMMAND_REASON
    )


def test_touch_requires_approval(tmp_path: Path) -> None:
    assert guarded_run_command_reason("touch file.txt", tmp_path) == MUTATING_COMMAND_REASON


def test_rm_requires_approval(tmp_path: Path) -> None:
    assert guarded_run_command_reason("rm file.txt", tmp_path) == MUTATING_COMMAND_REASON


def test_redirect_requires_approval(tmp_path: Path) -> None:
    assert (
        guarded_run_command_reason("pytest -q > out.txt", tmp_path)
        == SHELL_SYNTAX_REASON
    )


def test_or_operator_requires_approval(tmp_path: Path) -> None:
    assert (
        guarded_run_command_reason("echo ok || echo fallback", tmp_path)
        == SHELL_SYNTAX_REASON
    )


def test_python3_c_requires_approval(tmp_path: Path) -> None:
    assert (
        guarded_run_command_reason('python3 -c "print(1)"', tmp_path)
        == SHELL_SYNTAX_REASON
    )


def test_pip3_install_requires_approval(tmp_path: Path) -> None:
    assert (
        guarded_run_command_reason("pip3 install requests", tmp_path)
        == MUTATING_COMMAND_REASON
    )


def test_npm_ci_requires_approval(tmp_path: Path) -> None:
    assert guarded_run_command_reason("npm ci", tmp_path) == MUTATING_COMMAND_REASON


def test_git_reset_requires_approval(tmp_path: Path) -> None:
    assert guarded_run_command_reason("git reset --hard", tmp_path) == MUTATING_COMMAND_REASON


def test_git_status_allowed(tmp_path: Path) -> None:
    assert guarded_run_command_reason("git status", tmp_path) is None


def test_absolute_outside_path_requires_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()

    assert (
        guarded_run_command_reason(f"ls {outside}", workspace)
        == OUTSIDE_PATH_REASON
    )


def test_home_outside_path_requires_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert (
        guarded_run_command_reason("ls ~/definitely-outside-code-squid", workspace)
        == OUTSIDE_PATH_REASON
    )


def test_relative_inside_path_allowed_for_allowlisted_file_command(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    assert guarded_run_command_reason("ls tests", tmp_path) is None

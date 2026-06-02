# core/command_safety.py

"""Conservative guarded-mode checks for run_command approval decisions."""

from __future__ import annotations

import shlex
from pathlib import Path

from core.workspace_boundary import is_inside_workspace


SHELL_SYNTAX_REASON = "Command uses shell syntax that requires approval"
OUTSIDE_PATH_REASON = "Command references a path outside the workspace"
NOT_ALLOWLISTED_REASON = "Command is not on the guarded allowlist"

_SHELL_SYNTAX_PATTERNS = (">", "|", ";", "$(", "`", "\n", "&&")
_RISKY_TOKENS = {
    "tee",
    "xargs",
    "-exec",
    "rm",
    "mv",
    "cp",
    "mkdir",
    "touch",
    "chmod",
    "chown",
    "sudo",
}


def guarded_run_command_reason(command: str, workspace_root: Path) -> str | None:
    """Return a short approval reason, or None when guarded mode can allow it."""

    if any(pattern in command for pattern in _SHELL_SYNTAX_PATTERNS):
        return SHELL_SYNTAX_REASON

    try:
        tokens = shlex.split(command)
    except ValueError:
        return SHELL_SYNTAX_REASON

    if not tokens:
        return NOT_ALLOWLISTED_REASON

    risky_reason = _risky_token_reason(tokens)
    if risky_reason is not None:
        return risky_reason

    if _is_pwd(tokens):
        return None
    if _is_git_status_or_diff(tokens):
        return _outside_path_reason(
            _obvious_path_args(tokens[2:], workspace_root),
            workspace_root,
        )
    if _is_ls(tokens):
        return _outside_path_reason(_non_option_args(tokens[1:]), workspace_root)
    if _is_find(tokens):
        return _outside_path_reason(_find_path_args(tokens[1:]), workspace_root)
    if _is_ripgrep_or_grep(tokens):
        return _outside_path_reason(
            _obvious_path_args(tokens[1:], workspace_root),
            workspace_root,
        )
    if _is_pytest(tokens):
        return _outside_path_reason(
            _obvious_path_args(_pytest_args(tokens), workspace_root),
            workspace_root,
        )
    if _is_node_check(tokens):
        return _outside_path_reason(_non_option_args(tokens[2:]), workspace_root)

    return NOT_ALLOWLISTED_REASON


def _risky_token_reason(tokens: list[str]) -> str | None:
    lowered = [token.lower() for token in tokens]
    if any(token in _RISKY_TOKENS for token in lowered):
        return SHELL_SYNTAX_REASON
    if lowered[:2] in (["bash", "-c"], ["sh", "-c"], ["python", "-c"]):
        return SHELL_SYNTAX_REASON
    if lowered[:2] in (
        ["pip", "install"],
        ["npm", "install"],
        ["git", "reset"],
        ["git", "clean"],
    ):
        return SHELL_SYNTAX_REASON
    return None


def _is_pwd(tokens: list[str]) -> bool:
    return tokens == ["pwd"]


def _is_git_status_or_diff(tokens: list[str]) -> bool:
    return len(tokens) >= 2 and tokens[0] == "git" and tokens[1] in {"status", "diff"}


def _is_ls(tokens: list[str]) -> bool:
    return tokens[0] == "ls"


def _is_find(tokens: list[str]) -> bool:
    return tokens[0] == "find"


def _is_ripgrep_or_grep(tokens: list[str]) -> bool:
    return tokens[0] in {"rg", "grep"}


def _is_pytest(tokens: list[str]) -> bool:
    return tokens[0] == "pytest" or tokens[:3] == ["python", "-m", "pytest"]


def _pytest_args(tokens: list[str]) -> list[str]:
    if tokens[:3] == ["python", "-m", "pytest"]:
        return tokens[3:]
    return tokens[1:]


def _is_node_check(tokens: list[str]) -> bool:
    return len(tokens) >= 2 and tokens[:2] == ["node", "--check"]


def _non_option_args(tokens: list[str]) -> list[str]:
    return [token for token in tokens if not token.startswith("-")]


def _find_path_args(tokens: list[str]) -> list[str]:
    paths = []
    for token in tokens:
        if token.startswith("-") or token in {"(", ")", "!"}:
            break
        paths.append(token)
    return paths


def _obvious_path_args(tokens: list[str], workspace_root: Path) -> list[str]:
    return [
        token
        for token in _non_option_args(tokens)
        if _looks_like_path(token, workspace_root)
    ]


def _looks_like_path(token: str, workspace_root: Path) -> bool:
    path = Path(token)
    if path.is_absolute() or token.startswith("~"):
        return True
    if token.startswith(".") or "/" in token:
        return True
    return (workspace_root / token).exists()


def _outside_path_reason(paths: list[str], workspace_root: Path) -> str | None:
    for path in paths:
        if not _is_guarded_path_inside_workspace(path, workspace_root):
            return OUTSIDE_PATH_REASON
    return None


def _is_guarded_path_inside_workspace(path: str, workspace_root: Path) -> bool:
    path_value = Path(path).expanduser()
    if not path_value.is_absolute():
        path_value = workspace_root / path_value
    return is_inside_workspace(path_value, workspace_root)

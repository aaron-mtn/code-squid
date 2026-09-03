"""Argument parsing and workspace resolution for the Code Squid CLI."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParsedCliArgs:
    repo_root: Path
    skill_name: str | None
    remaining_args: list[str]


def _extract_cwd_arg(args: list[str]) -> tuple[str | None, list[str]]:
    if "--cwd" not in args:
        return None, args

    cwd_index = args.index("--cwd")
    if cwd_index + 1 >= len(args):
        raise ValueError("--cwd requires a path")

    cwd_arg = args[cwd_index + 1]
    remaining_args = args[:cwd_index] + args[cwd_index + 2 :]
    return cwd_arg, remaining_args


def _extract_skill_arg(args: list[str]) -> tuple[str | None, list[str]]:
    if "--skill" not in args:
        return None, args

    skill_index = args.index("--skill")
    if skill_index + 1 >= len(args):
        raise ValueError("--skill requires a skill name")

    skill_name = args[skill_index + 1]
    remaining_args = args[:skill_index] + args[skill_index + 2 :]
    return skill_name, remaining_args


def _resolve_workspace_root(cwd_arg: str | None) -> Path:
    workspace_root = Path.cwd() if cwd_arg is None else Path(cwd_arg).expanduser()
    resolved_root = workspace_root.resolve()

    if not resolved_root.exists():
        raise ValueError(f"--cwd path does not exist: {workspace_root}")
    if not resolved_root.is_dir():
        raise ValueError(f"--cwd path is not a directory: {workspace_root}")

    return resolved_root


def parse_cli_args(args: list[str]) -> ParsedCliArgs:
    cwd_arg, remaining_args = _extract_cwd_arg(args)
    skill_name, remaining_args = _extract_skill_arg(remaining_args)
    repo_root = _resolve_workspace_root(cwd_arg)

    return ParsedCliArgs(
        repo_root=repo_root,
        skill_name=skill_name,
        remaining_args=remaining_args,
    )

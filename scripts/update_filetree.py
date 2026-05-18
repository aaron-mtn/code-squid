#!/usr/bin/env python3
"""Generate docs/filetree.md with the repository tree and Python docstrings."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "docs" / "filetree.md"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".code-squid",
    "node_modules",
}

EXCLUDED_FILES = {
    ".DS_Store",
}

INCLUDED_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
}


def should_skip(path: Path) -> bool:
    """Return True when a path should be excluded from the generated output."""
    relative_parts = set(path.relative_to(REPO_ROOT).parts)

    if relative_parts & EXCLUDED_DIRS:
        return True

    if path.name in EXCLUDED_FILES:
        return True

    return False


def should_include_file(path: Path) -> bool:
    """Return True when a file should appear in the generated tree."""
    if should_skip(path):
        return False

    if path == OUTPUT_PATH:
        return False

    return path.suffix in INCLUDED_SUFFIXES


def first_docstring(path: Path) -> str:
    """Return the first docstring found in a Python file, or an empty string."""
    if path.suffix != ".py":
        return ""

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ""

    candidates: list[tuple[int, str]] = []

    # Module docstrings do not have their own convenient AST node line number,
    # so treat them as line 1.
    module_docstring = ast.get_docstring(tree)
    if module_docstring:
        candidates.append((1, module_docstring))

    # Fall back to the first class/function docstring by source position.
    # This lets files without module docstrings still show their ownership note
    # if the first class or helper has a docstring.
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node)
            if docstring:
                candidates.append((getattr(node, "lineno", 999_999), docstring))

    if not candidates:
        return ""

    return sorted(candidates, key=lambda item: item[0])[0][1]


def visible_children(directory: Path) -> list[Path]:
    """Return sorted visible children for the tree output."""
    children: list[Path] = []

    for child in directory.iterdir():
        if should_skip(child):
            continue

        if child.is_dir():
            if visible_children(child):
                children.append(child)
        elif child.is_file() and should_include_file(child):
            children.append(child)

    return sorted(children, key=lambda path: (path.is_file(), path.name.lower()))


def iter_visible_files(directory: Path) -> list[Path]:
    """Return all visible included files under directory."""
    files: list[Path] = []

    for child in directory.iterdir():
        if should_skip(child):
            continue

        if child.is_dir():
            files.extend(iter_visible_files(child))
        elif child.is_file() and should_include_file(child):
            files.append(child)

    return sorted(
        files,
        key=lambda path: path.relative_to(REPO_ROOT).as_posix().lower(),
    )


def render_tree(directory: Path, prefix: str = "") -> list[str]:
    """Render directory and its children as markdown-friendly tree lines."""
    lines: list[str] = []
    children = visible_children(directory)

    for index, child in enumerate(children):
        is_last = index == len(children) - 1
        branch = "└── " if is_last else "├── "
        next_prefix = prefix + ("    " if is_last else "│   ")

        lines.append(f"{prefix}{branch}{child.name}")

        if child.is_dir():
            lines.extend(render_tree(child, next_prefix))

    return lines


def render_file_notes() -> list[str]:
    """Render Python docstrings as readable markdown notes."""
    lines: list[str] = []

    for path in iter_visible_files(REPO_ROOT):
        docstring = first_docstring(path)
        if not docstring:
            continue

        relative_path = path.relative_to(REPO_ROOT).as_posix()
        first_line = docstring.strip().splitlines()[0]

        lines.extend(
            [
                f"### `{relative_path}`",
                "",
                first_line,
                "",
            ]
        )

    if not lines:
        return ["No Python docstrings found.", ""]

    return lines


def main() -> None:
    """Write the generated repository file tree documentation."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "```text",
        f"{REPO_ROOT.name}/",
        *render_tree(REPO_ROOT),
        "```",
        "",
        "## File notes",
        "",
        *render_file_notes(),
    ]

    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
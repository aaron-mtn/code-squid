# core/user_tools.py

"""Discover saved user tool metadata without executing tool code."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from core.extension_paths import user_tools_dir


SAFE_TOOL_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


@dataclass(frozen=True)
class UserTool:
    name: str
    description: str = ""
    version: str = ""
    entrypoint: str = "tool.py"
    function: str = "run"
    args: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, Any] = field(default_factory=dict)
    source: str = "user"
    editable: bool = True


class UserToolError(RuntimeError):
    pass


def discover_user_tools() -> dict[str, UserTool]:
    """Return valid user tool metadata in deterministic directory order."""
    root = user_tools_dir()
    if not root.exists():
        return {}
    if not root.is_dir():
        raise UserToolError(f"{root}: tools path is not a directory")

    tools: dict[str, UserTool] = {}
    for tool_dir in sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=_path_sort_key,
    ):
        try:
            tool = load_user_tool(tool_dir)
        except UserToolError:
            continue
        if tool is not None:
            tools[tool.name] = tool
    return tools


def load_user_tool(tool_dir: Path | str) -> UserTool | None:
    """Load one user tool manifest as metadata only."""
    tool_dir = Path(tool_dir)
    metadata_path = tool_dir / "tool.yaml"
    if not metadata_path.is_file():
        return None

    folder_name = tool_dir.name
    _validate_tool_name(folder_name, tool_dir)

    metadata = _parse_metadata_file(metadata_path)
    name = _metadata_string(metadata, "name", metadata_path, required=True).strip()
    _validate_tool_name(name, metadata_path)
    if name != folder_name:
        raise UserToolError(
            f"{metadata_path}: tool name {name!r} must match folder name {folder_name!r}"
        )

    entrypoint = _metadata_string(
        metadata,
        "entrypoint",
        metadata_path,
        default="tool.py",
    ).strip()
    _validate_safe_filename(entrypoint, metadata_path, "entrypoint")

    function = _metadata_string(
        metadata,
        "function",
        metadata_path,
        default="run",
    ).strip()
    if not function:
        raise UserToolError(f"{metadata_path}: function must not be empty")

    return UserTool(
        name=name,
        description=_metadata_string(metadata, "description", metadata_path),
        version=_metadata_string(metadata, "version", metadata_path),
        entrypoint=entrypoint,
        function=function,
        args=_metadata_object(metadata, "args", metadata_path),
        safety=_metadata_object(metadata, "safety", metadata_path),
    )


def _parse_metadata_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise UserToolError(f"{path}: could not read tool metadata: {error}") from error

    stripped = text.strip()
    if not stripped:
        raise UserToolError(f"{path}: tool metadata must not be empty")

    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise UserToolError(f"{path}: invalid JSON metadata: {error}") from error
        if not isinstance(data, dict):
            raise UserToolError(f"{path}: tool metadata must be an object")
        return data

    return _parse_simple_yaml_mapping(text, path)


def _parse_simple_yaml_mapping(text: str, path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for line_number, line in enumerate(text.splitlines(), start=1):
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise UserToolError(f"{path}:{line_number}: tabs are not valid indentation")

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise UserToolError(f"{path}:{line_number}: invalid metadata line")

        indent = len(line) - len(line.lstrip(" "))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise UserToolError(f"{path}:{line_number}: invalid empty metadata key")

        parent = stack[-1][1]
        raw_value = raw_value.strip()
        if raw_value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            continue

        parent[key] = _parse_scalar(raw_value, path, line_number)

    return root


def _parse_scalar(value: str, path: Path, line_number: int) -> Any:
    if value.startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise UserToolError(
                f"{path}:{line_number}: invalid inline JSON value: {error}"
            ) from error

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if value and value.lstrip("-").isdigit():
        return int(value)
    return value


def _metadata_string(
    metadata: dict[str, Any],
    key: str,
    path: Path,
    *,
    default: str = "",
    required: bool = False,
) -> str:
    if key not in metadata:
        if required:
            raise UserToolError(f"{path}: missing required metadata field: {key}")
        return default

    value = metadata[key]
    if not isinstance(value, str):
        raise UserToolError(f"{path}: {key} must be a string")
    if required and not value.strip():
        raise UserToolError(f"{path}: missing required metadata field: {key}")
    return value


def _metadata_object(metadata: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = metadata.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise UserToolError(f"{path}: {key} must be an object")
    return value


def _validate_tool_name(name: str, path: Path) -> None:
    if not SAFE_TOOL_NAME_RE.fullmatch(name):
        raise UserToolError(
            f"{path}: tool name must contain only lowercase letters, numbers, underscores, and hyphens"
        )


def _validate_safe_filename(value: str, path: Path, field_name: str) -> None:
    if not value:
        raise UserToolError(f"{path}: {field_name} must not be empty")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise UserToolError(f"{path}: {field_name} must not contain path separators")


def _path_sort_key(path: Path) -> tuple[str, str]:
    return (path.name.lower(), path.name)

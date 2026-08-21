# core/extensions.py

"""Discover user extension bundle metadata without executing extension code."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Any

from core.extension_paths import extension_state_path, user_extensions_dir


SAFE_EXTENSION_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
ALLOWED_EXTENSION_ACCENTS = (
    "cyan",
    "blue",
    "green",
    "yellow",
    "orange",
    "red",
    "pink",
    "purple",
    "white",
    "gray",
)
DEFAULT_EXTENSION_ACCENT = "cyan"


@dataclass(frozen=True)
class Extension:
    name: str
    title: str
    description: str
    version: str
    accent: str
    default_skill: str | None
    skills: tuple[str, ...]
    tools: tuple[str, ...]
    hooks: tuple[str, ...]
    path: Path
    active: bool = False
    valid: bool = True
    errors: tuple[str, ...] = ()


class ExtensionMetadataError(RuntimeError):
    pass


def discover_extensions(
    extensions_dir: Path | None = None,
    *,
    state_path: Path | None = None,
) -> dict[str, Extension]:
    """Return extension metadata in deterministic directory order."""
    root = extensions_dir if extensions_dir is not None else user_extensions_dir()
    if not root.exists():
        return {}
    if not root.is_dir():
        return {}

    active_name = get_active_extension_name(state_path)
    extensions: dict[str, Extension] = {}
    for extension_dir in sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=_path_sort_key,
    ):
        extension = load_extension(extension_dir, active_name=active_name)
        if extension is not None:
            extensions[extension_dir.name] = extension
    return extensions


def load_extension(
    extension_dir: Path,
    *,
    active_name: str | None = None,
) -> Extension | None:
    """Load one extension manifest as metadata only."""
    extension_dir = Path(extension_dir)
    metadata_path = extension_dir / "extension.yaml"
    if not metadata_path.is_file():
        return None

    folder_name = extension_dir.name
    try:
        metadata = _parse_metadata_file(metadata_path)
        name = _metadata_string(metadata, "name", metadata_path, default=folder_name)
        title = _metadata_string(metadata, "title", metadata_path, default=name)
        extension = Extension(
            name=name,
            title=title or name,
            description=_metadata_string(metadata, "description", metadata_path),
            version=_metadata_string(metadata, "version", metadata_path),
            accent=_metadata_string(
                metadata,
                "accent",
                metadata_path,
                default=DEFAULT_EXTENSION_ACCENT,
            ),
            default_skill=_metadata_optional_string(
                metadata,
                "default_skill",
                metadata_path,
            ),
            skills=_metadata_string_list(metadata, "skills", metadata_path),
            tools=_metadata_string_list(metadata, "tools", metadata_path),
            hooks=_metadata_string_list(metadata, "hooks", metadata_path),
            path=extension_dir,
            active=name == active_name,
        )
        errors = validate_extension(extension)
    except ExtensionMetadataError as error:
        extension = Extension(
            name=folder_name,
            title=folder_name,
            description="",
            version="",
            accent=DEFAULT_EXTENSION_ACCENT,
            default_skill=None,
            skills=(),
            tools=(),
            hooks=(),
            path=extension_dir,
            active=folder_name == active_name,
            valid=False,
            errors=(str(error),),
        )
    else:
        extension = replace(extension, valid=not errors, errors=tuple(errors))

    return extension


def validate_extension(extension: Extension) -> tuple[str, ...]:
    """Return validation errors for an extension manifest and its listed files."""
    errors: list[str] = []
    metadata_path = extension.path / "extension.yaml"

    if not SAFE_EXTENSION_NAME_RE.fullmatch(extension.name):
        errors.append(
            f"{metadata_path}: extension name must contain only lowercase letters, "
            "numbers, underscores, and hyphens"
        )
    if extension.name != extension.path.name:
        errors.append(
            f"{metadata_path}: extension name {extension.name!r} must match "
            f"folder name {extension.path.name!r}"
        )
    if extension.accent not in ALLOWED_EXTENSION_ACCENTS:
        allowed_accents = ", ".join(ALLOWED_EXTENSION_ACCENTS)
        errors.append(
            f"{metadata_path}: accent {extension.accent!r} must be one of: "
            f"{allowed_accents}"
        )
    if extension.default_skill is not None and extension.default_skill not in extension.skills:
        errors.append(
            f"{metadata_path}: default_skill {extension.default_skill!r} must be listed in skills"
        )

    for skill in extension.skills:
        if not (extension.path / "skills" / skill / "SKILL.md").is_file():
            errors.append(
                f"{extension.path}: listed skill {skill!r} must have skills/{skill}/SKILL.md"
            )
    for tool in extension.tools:
        if not (extension.path / "tools" / tool / "tool.yaml").is_file():
            errors.append(
                f"{extension.path}: listed tool {tool!r} must have tools/{tool}/tool.yaml"
            )
    for hook in extension.hooks:
        hook_dir = extension.path / "hooks" / hook
        if not (hook_dir / "hook.yaml").is_file():
            errors.append(
                f"{extension.path}: listed hook {hook!r} must have hooks/{hook}/hook.yaml"
            )
        if not (hook_dir / "hook.py").is_file():
            errors.append(
                f"{extension.path}: listed hook {hook!r} must have hooks/{hook}/hook.py"
            )

    return tuple(errors)


def get_active_extension_name(state_path: Path | None = None) -> str | None:
    """Return the active extension name from state, or None if unset/invalid."""
    path = state_path if state_path is not None else extension_state_path()
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    active_extension = data.get("active_extension")
    if not isinstance(active_extension, str):
        return None
    active_extension = active_extension.strip()
    return active_extension or None


def set_active_extension(name: str | None, state_path: Path | None = None) -> None:
    """Persist the active extension name, or clear it with None."""
    path = state_path if state_path is not None else extension_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"active_extension": name if name else None}
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def get_active_extension(
    extensions_dir: Path | None = None,
    state_path: Path | None = None,
) -> Extension | None:
    """Return the active extension metadata if the state points at a discovered extension."""
    active_name = get_active_extension_name(state_path)
    if active_name is None:
        return None

    root = extensions_dir if extensions_dir is not None else user_extensions_dir()
    extension = discover_extensions(root, state_path=state_path).get(active_name)
    if extension is None:
        return None
    return replace(extension, active=True)


def _parse_metadata_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ExtensionMetadataError(
            f"{path}: could not read extension metadata: {error}"
        ) from error

    if not text.strip():
        raise ExtensionMetadataError(f"{path}: extension metadata must not be empty")
    if text.strip().startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ExtensionMetadataError(f"{path}: invalid JSON metadata: {error}") from error
        if not isinstance(data, dict):
            raise ExtensionMetadataError(f"{path}: extension metadata must be an object")
        return data

    return _parse_simple_yaml_mapping(text, path)


def _parse_simple_yaml_mapping(text: str, path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list_key: str | None = None

    for line_number, line in enumerate(text.splitlines(), start=1):
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ExtensionMetadataError(
                f"{path}:{line_number}: tabs are not valid indentation"
            )

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if current_list_key is not None and line[:1].isspace():
            if not stripped.startswith("- "):
                raise ExtensionMetadataError(
                    f"{path}:{line_number}: invalid metadata list item"
                )
            item = stripped[2:].strip()
            if not item:
                raise ExtensionMetadataError(
                    f"{path}:{line_number}: invalid empty metadata list item"
                )
            current_value = data[current_list_key]
            if not isinstance(current_value, list):
                current_value = []
                data[current_list_key] = current_value
            current_value.append(_parse_scalar(item, path, line_number))
            continue

        current_list_key = None
        if ":" not in stripped:
            raise ExtensionMetadataError(f"{path}:{line_number}: invalid metadata line")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        if not key:
            raise ExtensionMetadataError(
                f"{path}:{line_number}: invalid empty metadata key"
            )

        raw_value = raw_value.strip()
        if raw_value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = _parse_scalar(raw_value, path, line_number)

    return data


def _parse_scalar(value: str, path: Path, line_number: int) -> Any:
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ExtensionMetadataError(
                f"{path}:{line_number}: invalid inline JSON value: {error}"
            ) from error

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value.lower() in {"null", "none"}:
        return None
    return value


def _metadata_string(
    metadata: dict[str, Any],
    key: str,
    path: Path,
    *,
    default: str = "",
) -> str:
    value = metadata.get(key, default)
    if not isinstance(value, str):
        raise ExtensionMetadataError(f"{path}: {key} must be a string")
    return value


def _metadata_optional_string(
    metadata: dict[str, Any],
    key: str,
    path: Path,
) -> str | None:
    value = metadata.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ExtensionMetadataError(f"{path}: {key} must be a string")
    return value


def _metadata_string_list(
    metadata: dict[str, Any],
    key: str,
    path: Path,
) -> tuple[str, ...]:
    value = metadata.get(key, [])
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ExtensionMetadataError(f"{path}: {key} must be a list of strings")
    return tuple(value)


def _path_sort_key(path: Path) -> tuple[str, str]:
    return (path.name.lower(), path.name)

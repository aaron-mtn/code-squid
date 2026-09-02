"""Mod metadata models and validation constants."""

from dataclasses import dataclass
from pathlib import Path
import re

from squid_core.skills import Skill


SAFE_MOD_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SAFE_COMPONENT_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
ALLOWED_MOD_ACCENTS = (
    "cyan", "blue", "green", "yellow", "orange",
    "red", "pink", "purple", "white", "gray",
)
DEFAULT_MOD_ACCENT = "cyan"
MOD_FIELDS = {"name", "description", "default_skill", "accent", "tools", "hooks"}


@dataclass(frozen=True)
class Mod:
    name: str
    description: str
    default_skill: str
    accent: str
    tools: tuple[str, ...]
    hooks: tuple[str, ...]
    path: Path
    valid: bool = True
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedMod:
    metadata: Mod
    skill: Skill
    tools: dict
    hooks: tuple[object, ...]


class ModMetadataError(RuntimeError):
    pass


class ModResolutionError(ValueError):
    pass

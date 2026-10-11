"""Select Code Squid's bundled and user Mods through Core's existing APIs.

This application adapter protects the built-in identity and locates installed
resources. Core still owns all manifest parsing, validation, and execution.
CLI selection, presentation, and agent_setup share this seam so they agree on
which package a name selects. No resources are copied into the user's home.
"""

from importlib.resources import files
from pathlib import Path

from squid_core.mods import Mod, ModResolutionError
from squid_core.mods import discover_mods as discover_user_mods
from squid_core.mods import load_mod as load_core_mod
from squid_core.mods import resolve_mod as resolve_core_mod


BUILTIN_MOD_NAMES = frozenset({"mod-builder"})


def bundled_mod_home() -> Path:
    """Return the physical resource home provided by source and pip installs.

    Core imports tool.py lazily from disk. Keep installed resource paths alive
    for the whole process instead of returning an expired extraction context.
    Zip-import execution is intentionally unsupported; pip unpacks wheels.
    """
    home = files("code_squid").joinpath("resources")
    if not isinstance(home, Path):
        raise ModResolutionError("Bundled Mods require an unpacked Code Squid installation")
    return home


def load_mod(name: str, app_home: Path | str, **kwargs) -> Mod:
    """Prefer the reserved bundled identity, even when its resources are damaged."""
    home = bundled_mod_home() if name in BUILTIN_MOD_NAMES else app_home
    return load_core_mod(name, home, **kwargs)


def discover_mods(app_home: Path | str, **kwargs) -> dict[str, Mod]:
    """Merge metadata without executing components or modifying user packages."""
    mods = discover_user_mods(app_home, **kwargs)
    for name in sorted(BUILTIN_MOD_NAMES):
        try:
            mods[name] = load_mod(name, app_home, **kwargs)
        except (OSError, UnicodeError, ModResolutionError) as error:
            # An incomplete installation must remain visible as invalid, rather
            # than silently selecting a same-named user package in its place.
            mods[name] = Mod(
                name=name, description="Built-in Mod Builder", default_skill="",
                accent="cyan", hooks=(), path=Path("resources/mods") / name,
                valid=False, errors=(f"Bundled Mod unavailable: {error}",),
            )
    return mods


def resolve_mod(name: str, app_home: Path | str, **kwargs):
    """Resolve with Core; only the selected package home changes for built-ins."""
    home = bundled_mod_home() if name in BUILTIN_MOD_NAMES else app_home
    return resolve_core_mod(name, home, **kwargs)


def mod_source_label(name: str, app_home: Path | str) -> str:
    """Explain reserved-name collisions without reading or mutating that package."""
    if name not in BUILTIN_MOD_NAMES:
        return ""
    if (Path(app_home) / "mods" / name).is_dir():
        return " (built-in; same-named user Mod is shadowed and unchanged)"
    return " (built-in)"

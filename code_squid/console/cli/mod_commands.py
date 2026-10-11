"""Interactive Mod selection and status helpers for the Code Squid CLI."""

from code_squid.app_paths import code_squid_home
from code_squid.mods import discover_mods, mod_source_label


MOD_COMMAND = "/mod"


def apply_mod_selection(
    requested_mod: str,
    skill_name: str | None,
) -> tuple[str | None, str | None]:
    """Select a Mod's default Skill, replacing the previous specialization."""
    if requested_mod == "none":
        # A packaged Skill must not become a standalone lookup on clearing its
        # owner. Callers preserve standalone state when there is no active Mod.
        return None, None
    mod = discover_mods(code_squid_home()).get(requested_mod)
    if mod is None:
        raise ValueError(f"Unknown Mod: {requested_mod}")
    if not mod.valid:
        raise ValueError(f"Invalid Mod: {requested_mod}")
    return mod.name, mod.default_skill


def _is_mod_input(task: str) -> bool:
    stripped = task.strip()
    return stripped == MOD_COMMAND or stripped.startswith(f"{MOD_COMMAND} ")


def _format_mod_status(mod_name: str | None) -> str:
    mods = discover_mods(code_squid_home())
    lines = [f"Current Mod: {mod_name or 'none'}", "", "Available Mods:"]
    if not mods:
        lines.append("none")
    else:
        for mod in mods.values():
            validity = "" if mod.valid else " (invalid)"
            source = mod_source_label(mod.name, code_squid_home())
            lines.append(f"- {mod.name}: {mod.description}{source}{validity}")
    return "\n".join(lines)


def _handle_mod_input(
    task: str,
    mod_name: str | None,
    skill_name: str | None,
) -> tuple[str | None, str | None]:
    """Handle one Mod command and return unambiguous Mod/Skill selections."""
    parts = task.strip().split()
    if len(parts) == 1:
        print(_format_mod_status(mod_name))
        return mod_name, skill_name
    if len(parts) != 2:
        print("Usage: /mod [name|none]")
        return mod_name, skill_name

    requested_mod = parts[1]
    if requested_mod == "none":
        print("Active Mod cleared.")
        return (None, skill_name) if mod_name is None else apply_mod_selection(requested_mod, skill_name)

    mod = discover_mods(code_squid_home()).get(requested_mod)
    if mod is None:
        print(f"Unknown Mod: {requested_mod}")
        print("Run /mod to see available Mods.")
        return mod_name, skill_name
    if not mod.valid:
        print(f"Invalid Mod: {requested_mod}")
        for error in mod.errors:
            print(f"- {error}")
        return mod_name, skill_name

    if skill_name is not None and mod_name is None:
        print(f"Standalone skill {skill_name} cleared by Mod selection.")
    source = mod_source_label(mod.name, code_squid_home())
    print(f"Active Mod set to: {mod.name}{source}")
    return apply_mod_selection(requested_mod, skill_name)

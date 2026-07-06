# cli/extensions.py

"""Extension management commands for the Code Squid CLI."""

from core.extensions import (
    Extension,
    discover_extensions,
    get_active_extension_name,
    set_active_extension,
)


def _extension_label(extension: Extension) -> str:
    if extension.title and extension.title != extension.name:
        return extension.title
    return extension.description or extension.title or extension.name


def _print_extension_errors(extension: Extension) -> None:
    for error in extension.errors:
        print(f"- {error}")


def _extensions_list() -> int:
    extensions = discover_extensions()
    if not extensions:
        print("No extensions found.")
        return 0

    for extension in extensions.values():
        active = "active" if extension.active else "inactive"
        valid = "valid" if extension.valid else "invalid"
        print(f"{extension.name}  {active}  {valid}  {_extension_label(extension)}")
    return 0


def _extensions_active() -> int:
    active_name = get_active_extension_name()
    if active_name is None:
        print("No active extension.")
        return 0

    extensions = discover_extensions()
    if active_name not in extensions:
        print(f"Active extension is set to '{active_name}', but it was not found.")
        return 0

    print(f"Active extension: {active_name}")
    return 0


def _extensions_activate(name: str) -> int:
    extensions = discover_extensions()
    extension = extensions.get(name)
    if extension is None:
        print(f"Unknown extension: {name}")
        return 1

    if not extension.valid:
        print(f"Extension {name} is invalid:")
        _print_extension_errors(extension)
        return 1

    set_active_extension(name)
    print(f"Activated extension: {name}")
    return 0


def _extensions_deactivate() -> int:
    if get_active_extension_name() is None:
        print("No active extension.")
        return 0

    set_active_extension(None)
    print("Deactivated extension.")
    return 0


def _extensions_validate(name: str) -> int:
    extensions = discover_extensions()
    extension = extensions.get(name)
    if extension is None:
        print(f"Unknown extension: {name}")
        return 1

    if extension.valid:
        print(f"Extension {name} is valid.")
        return 0

    print(f"Extension {name} is invalid:")
    _print_extension_errors(extension)
    return 1


def _extensions(args: list[str]) -> int:
    if args == ["list"]:
        return _extensions_list()
    if args == ["active"]:
        return _extensions_active()
    if args == ["deactivate"]:
        return _extensions_deactivate()
    if len(args) == 2 and args[0] == "activate":
        return _extensions_activate(args[1])
    if len(args) == 2 and args[0] == "validate":
        return _extensions_validate(args[1])

    print(
        "Usage: extensions "
        "list|active|activate <name>|deactivate|validate <name>"
    )
    return 1

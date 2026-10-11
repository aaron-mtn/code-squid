"""Create canonical component folders while shared Code Squid code owns policy."""


def run(args, context=None):
    # Never let an absent execution context turn the working directory into
    # an implicit authoring workspace. Core supplies this boundary at execution.
    if not (context or {}).get("workspace_root"):
        return {"ok": False, "error": "An explicit authoring workspace is required"}
    try:
        from code_squid.mod_authoring import scaffold_mod_component
    except (ImportError, ModuleNotFoundError) as error:
        return {"ok": False, "error_type": type(error).__name__, "error": "Mod component scaffolding is unavailable in this Code Squid installation; reinstall or update Code Squid."}
    # Core supplies the active workspace in its current Tool context.
    try:
        return scaffold_mod_component((context or {}).get("workspace_root", ""), (args or {}).get("package_path", ""), (args or {}).get("kind", ""), (args or {}).get("name", ""))
    except (OSError, ValueError) as error:
        return {"ok": False, "error_type": type(error).__name__, "error": str(error)}

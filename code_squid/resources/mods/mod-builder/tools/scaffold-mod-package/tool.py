"""Expose Code Squid's canonical Mod scaffolder to the Mod Builder Skill.

The reusable implementation lives in code_squid.mod_authoring; this file
does not own package policy or domain-specific Skill content.
"""

def run(args, context=None):
    # Never let an absent execution context turn the working directory into
    # an implicit authoring workspace. Core supplies this boundary at execution.
    if not (context or {}).get("workspace_root"):
        return {"ok": False, "error": "An explicit authoring workspace is required"}
    try:
        # User Tools load dynamically, so turn a missing authoring module
        # into a useful result instead of failing during Tool module import.
        from code_squid.mod_authoring import scaffold_mod_package
    except (ImportError, ModuleNotFoundError) as error:
        return {
            "ok": False,
            "error_type": type(error).__name__,
            "error": "Mod scaffolding is unavailable in this Code Squid installation; reinstall or update Code Squid.",
        }
    # Core supplies the active workspace in its current Tool context.
    try:
        package_name = args.get("package_name")
        return scaffold_mod_package(
            (context or {}).get("workspace_root", ""),
            package_name,
            args.get("description"),
            args.get("destination"),
        )
    except Exception as error:
        return {"ok": False, "error": str(error)}

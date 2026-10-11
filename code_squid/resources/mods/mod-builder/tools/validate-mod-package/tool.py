"""Expose runtime-backed Mod validation to the Mod Builder Skill.

The shared Code Squid implementation returns structured browser-safe diagnostics;
this entrypoint only supplies the active workspace boundary.
"""

def run(args, context=None):
    # Never let an absent execution context turn the working directory into
    # an implicit authoring workspace. Core supplies this boundary at execution.
    if not (context or {}).get("workspace_root"):
        return {"ok": False, "error": "An explicit authoring workspace is required"}
    try:
        # Authoring import failures remain safe, typed, and actionable when Core
        # dynamically loads this lightweight wrapper.
        from code_squid.mod_authoring import validate_mod_package
    except (ImportError, ModuleNotFoundError) as error:
        return {
            "ok": False,
            "error_type": type(error).__name__,
            "errors": [{
                "file": ".",
                "code": "runtime.unavailable",
                "message": "Mod validation is unavailable in this Code Squid installation; reinstall or update Code Squid.",
            }],
        }
    # Core supplies the active workspace in its current Tool context.
    try:
        return validate_mod_package(
            (context or {}).get("workspace_root", ""),
            args.get("package_path") or ".",
        )
    except Exception as error:
        return {"ok": False, "errors": [{"file": ".", "code": "validation.failed", "message": str(error)}]}

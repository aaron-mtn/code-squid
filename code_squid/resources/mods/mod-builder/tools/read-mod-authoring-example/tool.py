"""Expose only allowlisted canonical examples bundled with Mod Builder.

This read-only Tool never accepts a path and never returns the package's source
location. It returns complete examples as browser-safe relative file content.
"""

from pathlib import Path


EXAMPLES = {"skill-only", "builtin-file-tools", "bundled-tool", "before-accept-final-hook", "portable-tool-hook"}


def run(args, context=None):
    name = (args or {}).get("example", "")
    if name not in EXAMPLES:
        return {"ok": False, "error": "Unknown canonical Mod authoring example"}
    root = Path(__file__).resolve().parents[2] / "docs" / "examples" / name
    if not root.is_dir():
        return {"ok": False, "error": "The bundled Mod authoring example is unavailable"}
    # Require the essential files of each shipped example so partial packages
    # never masquerade as complete authoring references.
    required = ["mod.yaml", f"skills/{name}/SKILL.md"]
    components = {
        "bundled-tool": ["tools/echo-value/tool.yaml", "tools/echo-value/tool.py"],
        "before-accept-final-hook": ["hooks/final-note/hook.yaml", "hooks/final-note/hook.py"],
        "portable-tool-hook": ["tools/count-text/tool.yaml", "tools/count-text/tool.py", "hooks/completion-note/hook.yaml", "hooks/completion-note/hook.py"],
    }
    if any(not (root / relative).is_file() for relative in required + components.get(name, [])):
        return {"ok": False, "error": "The bundled Mod authoring example is incomplete"}
    try:
        files = {
            str(path.relative_to(root)).replace("\\", "/"): path.read_text(encoding="utf-8")
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in {".md", ".py", ".yaml", ".yml", ".json", ".txt"}
            and not any(part in {"__pycache__", ".pytest_cache"} for part in path.parts)
        }
    except (OSError, UnicodeError):
        return {"ok": False, "error": "The bundled Mod authoring example is unavailable"}
    return {"ok": True, "example": name, "files": files}

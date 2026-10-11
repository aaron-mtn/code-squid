"""Return the Mod Builder's bundled authoring contract without source access.

This Tool owns read-only access to one packaged documentation resource. It does
not inspect development files or accept an arbitrary path.
"""

from pathlib import Path


def run(args, context=None):
    guide = Path(__file__).resolve().parents[2] / "docs" / "mod-authoring.md"
    try:
        # Core bounds top-level strings. Structured data preserves the complete
        # authoring contract instead of silently truncating its middle sections.
        return {"ok": True, "message": "Complete authoring contract in data.guide", "data": {"guide": guide.read_text(encoding="utf-8")}}
    except (OSError, UnicodeError):
        return {"ok": False, "error": "The bundled Mod authoring guide is unavailable"}

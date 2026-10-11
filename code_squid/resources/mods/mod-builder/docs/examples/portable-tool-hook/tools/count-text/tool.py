"""Canonical portable Tool paired with a bundled Hook."""


def run(args, context=None):
    text = args.get("text")
    if not isinstance(text, str):
        return {"ok": False, "error": "text must be a string"}
    return {"ok": True, "message": str(len(text)), "data": {"characters": len(text)}}

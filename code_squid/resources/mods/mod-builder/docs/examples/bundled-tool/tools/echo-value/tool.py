"""Canonical deterministic Tool used by the bundled authoring examples."""


def run(args, context=None):
    value = args.get("value")
    prefix = args.get("prefix", "")
    if not isinstance(value, str) or not isinstance(prefix, str):
        return {"ok": False, "error": "value and prefix must be strings"}
    return {"ok": True, "message": f"{prefix}{value}", "data": {"value": value}}

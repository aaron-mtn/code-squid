from datetime import datetime, timezone
from typing import Any, Callable


EventCallback = Callable[[dict[str, Any]], None]


def emit_event(on_event: EventCallback | None, event: dict[str, Any]) -> None:
    if on_event is None:
        return

    event_to_emit = dict(event)
    if "timestamp" not in event_to_emit:
        event_to_emit["timestamp"] = datetime.now(timezone.utc).isoformat()

    try:
        on_event(event_to_emit)
    except Exception:
        pass

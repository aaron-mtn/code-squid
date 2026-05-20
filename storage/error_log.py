# storage/error_log.py

"""Tiny diagnostic error logging for Code Squid CLI failures."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import traceback


def write_error_log(code_squid_dir: Path, exc: BaseException) -> Path:
    """Write the latest app error traceback and return the log path."""
    log_dir = code_squid_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / "latest.log"
    # Keep this diagnostic log narrow. Session files own agent transcript data;
    # this log only captures traceback details for app/provider failures, and
    # intentionally avoids prompts, payloads, tool outputs, file contents,
    # headers, and API keys.
    timestamp = datetime.now(timezone.utc).isoformat()
    log_path.write_text(
        f"Timestamp: {timestamp}\n\n"
        + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        encoding="utf-8",
    )
    return log_path

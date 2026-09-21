"""Read append-only session JSONL while tolerating one torn final write."""

import json
from pathlib import Path
from typing import Any


def load_session_jsonl(
    path: Path,
    *,
    truncate_torn_tail: bool = False,
) -> list[dict[str, Any]]:
    """Load complete records, optionally removing a malformed final record."""
    lines: list[tuple[int, bytes]] = []
    offset = 0
    with path.open("rb") as file:
        for line in file:
            if line.strip():
                lines.append((offset, line))
            offset += len(line)

    records: list[dict[str, Any]] = []
    for index, (line_offset, line) in enumerate(lines):
        try:
            records.append(json.loads(line.decode("utf-8")))
        except json.JSONDecodeError:
            # A process can stop midway through its final append. Recovery is
            # safe only when a complete prefix proves this is a session log and
            # no later record exists that would turn the failure into corruption.
            if records and index == len(lines) - 1:
                if truncate_torn_tail:
                    # Continued persistence needs the bad bytes removed; merely
                    # appending a newline would make them middle corruption.
                    with path.open("r+b") as file:
                        file.truncate(line_offset)
                break
            raise

    return records

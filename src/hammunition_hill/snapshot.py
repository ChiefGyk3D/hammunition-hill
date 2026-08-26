"""Snapshot files: the only thing the collector produces.

Each source writes one JSON file into the data directory. The browser polls
those files. That indirection is the whole security story -- the server never
parses a query, so a request cannot influence what gets fetched or from where.

Writes are atomic. A dashboard that reads a half-written file shows garbage, and
on a Pi with a browser polling every ten seconds that is not a rare race.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Snapshot:
    """A source's output, wrapped in enough metadata for the UI to be honest.

    ``stale_after`` is what lets a panel say "solar data is 40 minutes old"
    instead of quietly showing yesterday's numbers as if they were current. With
    the WAN down that distinction is the difference between a useful degraded
    dashboard and a misleading one.
    """

    source_id: str
    kind: str
    fetched_at: datetime
    stale_after_seconds: int
    data: Any
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "source": self.source_id,
            "kind": self.kind,
            "fetched_at": self.fetched_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "stale_after_seconds": self.stale_after_seconds,
            "error": self.error,
            "data": self.data,
        }


def write_snapshot(data_dir: Path, snapshot: Snapshot) -> Path:
    """Write one snapshot atomically. Returns the path written.

    Same-directory temp file plus ``os.replace`` gives us an atomic rename on
    POSIX and Windows alike. Readers see either the old file or the new one.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / f"{snapshot.source_id}.json"
    payload = json.dumps(snapshot.to_dict(), separators=(",", ":"), sort_keys=True)

    fd, tmp_name = tempfile.mkstemp(dir=data_dir, prefix=f".{snapshot.source_id}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.chmod(0o644)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def read_snapshot(data_dir: Path, source_id: str) -> dict[str, Any] | None:
    """Read a snapshot back, or None if it has never been written.

    Used on startup so a restart with the WAN down still serves the last known
    good data rather than an empty dashboard.
    """
    path = data_dir / f"{source_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

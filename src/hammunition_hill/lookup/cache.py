# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A bounded, persistent cache of resolved callsigns.

Two jobs. It stops a busy cluster from turning into thousands of requests
against someone else's free service, and it survives a restart so a night of
resolution is not thrown away.

Entries expire because licences move, are renewed, and lapse. Negative results
are cached too, with a shorter life -- a callsign that is not on file is a fact
worth remembering for a while, but not forever.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .base import LookupResult

log = logging.getLogger(__name__)

DEFAULT_TTL_HOURS = 720          # 30 days: licence data barely moves.
NEGATIVE_TTL_HOURS = 24          # Retry a not-found sooner than a hit.
DEFAULT_MAX_ENTRIES = 5000

CACHE_FILE = "lookup_cache.json"


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


class LookupCache:
    """Callsign -> result or a recorded miss, with expiry."""

    def __init__(
        self,
        data_dir: Path,
        *,
        ttl_hours: int = DEFAULT_TTL_HOURS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._path = data_dir / CACHE_FILE
        self._ttl = timedelta(hours=ttl_hours)
        self._negative_ttl = timedelta(hours=min(NEGATIVE_TTL_HOURS, ttl_hours))
        self._max = max_entries
        self._entries: dict[str, dict[str, Any]] = {}
        self._dirty = False

    # --- persistence -----------------------------------------------------
    def load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("lookup cache unreadable (%s); starting empty", exc)
            return
        if isinstance(raw, dict):
            self._entries = {k: v for k, v in raw.items() if isinstance(v, dict)}
            log.info("lookup cache: %d entries loaded", len(self._entries))

    def save(self) -> None:
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self._entries, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self._path)
            self._dirty = False
        except OSError as exc:
            log.warning("could not write lookup cache: %s", exc)
            tmp.unlink(missing_ok=True)

    # --- access ----------------------------------------------------------
    def _fresh(self, entry: dict[str, Any]) -> bool:
        stamp = _parse(entry.get("cached_at"))
        if stamp is None:
            return False
        ttl = self._negative_ttl if entry.get("miss") else self._ttl
        return _now() - stamp < ttl

    def get(self, callsign: str) -> dict[str, Any] | None:
        """A cached result, or None if absent or stale. A miss returns ``{}``."""
        entry = self._entries.get(callsign.upper())
        if entry is None or not self._fresh(entry):
            return None
        return {} if entry.get("miss") else entry["result"]

    def knows(self, callsign: str) -> bool:
        """True if we have a fresh answer, hit or miss, and need not ask again."""
        return self.get(callsign) is not None

    def put(self, callsign: str, result: LookupResult | None) -> None:
        key = callsign.upper()
        entry: dict[str, Any] = {"cached_at": _now().isoformat().replace("+00:00", "Z")}
        if result is None:
            entry["miss"] = True
        else:
            entry["result"] = result.to_dict()
        self._entries[key] = entry
        self._dirty = True
        self._evict()

    def _evict(self) -> None:
        """Drop expired entries, then the oldest, until we are back under the cap."""
        if len(self._entries) <= self._max:
            return
        self._entries = {k: v for k, v in self._entries.items() if self._fresh(v)}
        if len(self._entries) <= self._max:
            return
        ordered = sorted(self._entries.items(), key=lambda kv: kv[1].get("cached_at", ""))
        for key, _ in ordered[: len(self._entries) - self._max]:
            del self._entries[key]

    # --- publication -----------------------------------------------------
    def hits(self) -> dict[str, Any]:
        """Fresh positive results only, for the snapshot the browser reads."""
        return {
            call: entry["result"]
            for call, entry in self._entries.items()
            if not entry.get("miss") and self._fresh(entry) and "result" in entry
        }

    def stats(self) -> dict[str, Any]:
        fresh = [e for e in self._entries.values() if self._fresh(e)]
        return {
            "entries": len(self._entries),
            "fresh": len(fresh),
            "resolved": sum(1 for e in fresh if not e.get("miss")),
            "not_found": sum(1 for e in fresh if e.get("miss")),
            "max_entries": self._max,
        }

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""What a GPS stream publishes, shared by both transports.

Kept in one place because the privacy decision must not be made twice. gpsd and
a serial receiver produce the same thing, and the rule about what leaves this
module -- a truncated grid square, and coordinates only when explicitly asked
for -- has to hold identically for both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..gps import (
    ALLOWED_PRECISION,
    CLOCK_WARN_SECONDS,
    DEFAULT_PRECISION,
    FIX_STALE_SECONDS,
    Fix,
    clock_offset_seconds,
)


def publish(fix: Fix | None, cfg: Any, *, source: str) -> dict[str, Any]:
    """The snapshot payload for a GPS stream.

    Says "no fix yet" rather than nothing when the receiver has not locked --
    an operator under tree cover wants to know the difference between "still
    searching" and "not plugged in".
    """
    options = getattr(cfg, "options", {}) or {}
    precision = options.get("precision", DEFAULT_PRECISION)
    if precision not in ALLOWED_PRECISION:
        precision = DEFAULT_PRECISION
    coordinates = bool(options.get("publish_coordinates", False))

    if fix is None:
        return {
            "source": source,
            "has_fix": False,
            "reason": "no fix yet — the receiver is searching, or has no sky view",
            "precision": precision,
        }

    offset = clock_offset_seconds(fix.utc)
    age = None
    if fix.utc is not None:
        age = (datetime.now(UTC) - fix.utc).total_seconds()

    return {
        "source": source,
        "has_fix": True,
        "precision": precision,
        "stale": bool(age is not None and age > FIX_STALE_SECONDS),
        "clock_offset_seconds": None if offset is None else round(offset, 2),
        # Surfaced separately from the raw number because this is the one that
        # costs an operator contacts: FT8 stops decoding somewhere around two
        # seconds of error, and a laptop off the network for a day can drift.
        "clock_ok": None if offset is None else abs(offset) <= CLOCK_WARN_SECONDS,
        "clock_warn_seconds": CLOCK_WARN_SECONDS,
        **fix.published(precision=precision, coordinates=coordinates),
    }

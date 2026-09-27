# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Real ionosonde soundings, via KC2G's aggregation of GIRO and NOAA.

This is measurement rather than model. Everywhere else the dashboard predicts
the ionosphere from solar indices -- MINIMUF from SFI and K, with an RMS around
3.8 MHz that the panel admits to. An ionosonde sweeps the sky and reports what
is actually up there: foF2, the highest frequency reflected straight up, and
MUF(D), the usable maximum for a 3000 km hop. Where a sounder is near the path,
that beats anything we can compute.

What the collector does with it is drop the stale ones, and that is the whole
job. The feed is a station roster, not a snapshot: every station KC2G knows
about appears on every fetch, carrying whatever reading it last managed. In one
real response, Austin reported ``fof2`` 8.6 with a confidence score of 100 and
a timestamp six months old; Beijing carried a reading from 2021. Publishing
those next to a live sounding would put a plausible, precise, badly wrong
number on the panel -- the exact failure the proton dial exists to avoid.

Note what does *not* catch this: ``cs``, the confidence score, is about the
quality of the scaling of that sounding, not its age. Austin's stale reading
scores 100. Only the timestamp catches it, and the timestamps arrive without a
timezone, so they have to be read as UTC deliberately rather than by whatever
the collector's machine happens to be set to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ..config import SourceConfig
from .base import FetchError, get_bounded

# An ionosonde sweeps every 5 to 15 minutes. Past this a reading is no longer
# "what the ionosphere is doing", and the station is better shown as absent than
# as confidently wrong -- see the module docstring for the real feed that made
# this necessary.
MAX_AGE_MINUTES = 90

# `cs` below zero is the feed's way of saying the sounding was never scaled.
# It travels with readings that are years old.
MIN_CONFIDENCE = 0.0


def _number(value: Any) -> float | None:
    """A float, or None. The feed mixes floats, numeric strings and nulls.

    Latitude and longitude arrive quoted (``"30.4"``, and ``"38"`` with no
    decimal point at all); ``md`` is quoted while ``mufd`` beside it is not.
    Coercing in one place beats trusting the type of any particular field.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _when(value: Any) -> datetime | None:
    """Parse the feed's timestamp as UTC.

    They arrive as ``2026-09-27T15:10:01`` -- no offset, no trailing Z. Read
    naively they would be interpreted in whatever zone the collector runs in,
    which silently shifts every age by the machine's offset and would mark live
    stations stale (or stale ones live) depending on which side of UTC it sits.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _station(entry: Any, now: datetime) -> dict[str, Any] | None:
    """One roster entry to a published station, or None to drop it."""
    if not isinstance(entry, dict):
        return None
    station = entry.get("station")
    if not isinstance(station, dict):
        return None

    observed = _when(entry.get("time"))
    if observed is None:
        return None
    age = (now - observed).total_seconds() / 60.0
    # Negative ages mean the upstream clock is ahead of ours, which is normal
    # by a few seconds and not a reason to discard a sounding.
    if age > MAX_AGE_MINUTES:
        return None

    confidence = _number(entry.get("cs"))
    if confidence is None or confidence < MIN_CONFIDENCE:
        return None

    lat = _number(station.get("latitude"))
    lon = _number(station.get("longitude"))
    if lat is None or lon is None:
        return None
    # The feed uses 0..360 east; everything else in this project uses -180..180.
    if lon > 180:
        lon -= 360

    fof2 = _number(entry.get("fof2"))
    mufd = _number(entry.get("mufd"))
    if fof2 is None and mufd is None:
        return None  # nothing worth plotting

    return {
        "code": station.get("code"),
        "name": station.get("name"),
        "lat": round(lat, 2),
        "lon": round(lon, 2),
        "fof2": fof2,
        "mufd": mufd,
        "md": _number(entry.get("md")),
        "hmf2": _number(entry.get("hmf2")),
        "tec": _number(entry.get("tec")),
        "confidence": confidence,
        "source": entry.get("source"),
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "age_minutes": round(age, 1),
    }


def _reduce(records: list[Any], now: datetime) -> dict[str, Any]:
    stations = [s for s in (_station(entry, now) for entry in records) if s is not None]
    stations.sort(key=lambda s: (s["code"] or "", s["name"] or ""))

    newest = min((s["age_minutes"] for s in stations), default=None)
    return {
        "stations": stations,
        "station_count": len(stations),
        # Said out loud so the panel can distinguish "the ionosphere is quiet"
        # from "we threw away everything the feed sent".
        "roster_size": len(records),
        "dropped": len(records) - len(stations),
        "max_age_minutes": MAX_AGE_MINUTES,
        "freshest_age_minutes": newest,
    }


class IonosondeSource:
    kind = "ionosonde"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc

        if not isinstance(payload, list):
            raise FetchError(f"{cfg.url}: expected a list of stations")

        return _reduce(payload, datetime.now(UTC))

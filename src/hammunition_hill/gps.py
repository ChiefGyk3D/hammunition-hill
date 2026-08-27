# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""GPS: position parsing, and the precision decision.

## Is reading a GPS "exposing too much of the system"?

Reasonable question, and the answer is no -- with one condition that turns out
to be the same thing as the feature.

Reading a receiver is no more privileged than reading ``rigctld``: both are a
local socket or device the operator opted into by naming it in config. The risk
was never the collector *reading* the position. It is the dashboard
**publishing** it -- a snapshot is served to everyone on the LAN, and a raw fix
is your house to within a few metres.

But a dashboard does not need metres. Everything it does with location --
beam headings, distances, the greyline, band-plan region, and the propagation
model's solar zenith -- is grid-square work. A 6-character Maidenhead locator
is about 3 by 1.5 miles, which is more than precise enough for all of it and
is already what an operator puts in their config by hand and prints on a QSL
card.

So the privacy control and the useful output are the same thing: **truncate to
Maidenhead and publish that**. Raw coordinates are available, off by default,
for an operator who wants them on their own machine.

## What it is actually for

Two things, both about operating away from home:

- **Automatic grid square.** At a park or on a summit, the grid changes and
  nobody wants to edit a config file to get correct bearings. This is the
  feature that makes a grid-aware dashboard usable portable.
- **A time check.** GPS carries UTC from an atomic clock. FT8 needs the system
  clock within about two seconds, and a laptop that has been off the network
  for a day may not be. The panel shows the drift; it does not set the clock,
  because a dashboard has no business holding root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .geo import latlon_to_grid

# Maidenhead characters to publish. 4 is roughly 70 x 35 miles, 6 is 3 x 1.5,
# 8 is about 500 x 250 metres. Six is the default because it is what operators
# already exchange and it is ample for every calculation here.
DEFAULT_PRECISION = 6
ALLOWED_PRECISION = (4, 6, 8)

# A fix older than this is not where you are any more.
FIX_STALE_SECONDS = 120

# The clock error at which FT8 and other timed digital modes start failing.
CLOCK_WARN_SECONDS = 2.0

# Talker ID varies by constellation -- GP, GN, GL, GA, GB -- so match any
# two letters and key on the sentence type that follows.
_SENTENCE = re.compile(
    r"^\$(?P<body>[A-Z]{2}(?P<kind>GGA|RMC),[^*]*)\*(?P<checksum>[0-9A-Fa-f]{2})"
)


@dataclass(frozen=True)
class Fix:
    """One position report, already reduced to what may be published."""

    lat: float
    lon: float
    grid: str
    quality: str
    satellites: int | None = None
    utc: datetime | None = None

    def published(self, *, precision: int, coordinates: bool) -> dict[str, Any]:
        """The publishable form.

        Coordinates are omitted unless explicitly asked for, and even then are
        rounded to the precision the grid square already implies -- publishing
        a truncated grid alongside a six-decimal latitude would give the
        privacy control away for nothing.
        """
        places = {4: 1, 6: 2, 8: 3}.get(precision, 2)
        out: dict[str, Any] = {
            "grid": self.grid[:precision],
            "quality": self.quality,
            "satellites": self.satellites,
            "utc": self.utc.isoformat().replace("+00:00", "Z") if self.utc else None,
        }
        if coordinates:
            out["lat"] = round(self.lat, places)
            out["lon"] = round(self.lon, places)
        return out


def checksum(body: str) -> str:
    """NMEA checksum: XOR of every character between ``$`` and ``*``."""
    value = 0
    for char in body:
        value ^= ord(char)
    return f"{value:02X}"


def _degrees(raw: str, hemisphere: str) -> float | None:
    """NMEA ddmm.mmmm to decimal degrees.

    The degrees field is two digits for latitude and three for longitude, and
    the rest is minutes -- not a decimal degree value. Reading it as one is the
    classic NMEA mistake and puts you a few hundred miles away.
    """
    if not raw or not hemisphere:
        return None
    try:
        point = raw.index(".")
    except ValueError:
        return None
    if point < 3:
        return None
    degrees = float(raw[: point - 2])
    minutes = float(raw[point - 2 :])
    value = degrees + minutes / 60.0
    if hemisphere.upper() in ("S", "W"):
        value = -value
    return value


def _timestamp(hhmmss: str, ddmmyy: str | None = None) -> datetime | None:
    """NMEA time, and date when the sentence carries one.

    GGA has only a time of day, so its result is anchored to today's UTC date.
    Around midnight that can be a day out; RMC carries the date and is
    preferred wherever both are available.
    """
    if not hhmmss or len(hhmmss) < 6:
        return None
    try:
        hour, minute = int(hhmmss[0:2]), int(hhmmss[2:4])
        second = float(hhmmss[4:])
    except ValueError:
        return None

    if ddmmyy and len(ddmmyy) == 6:
        try:
            day, month, year = int(ddmmyy[0:2]), int(ddmmyy[2:4]), int(ddmmyy[4:6])
        except ValueError:
            return None
        # NMEA years are two digits. These receivers did not exist before 2000.
        base = datetime(2000 + year, month, day, tzinfo=UTC)
    else:
        now = datetime.now(UTC)
        base = datetime(now.year, now.month, now.day, tzinfo=UTC)

    return base + timedelta(hours=hour, minutes=minute, seconds=second)


# GGA fix quality codes. Anything above 0 is a position; the distinctions
# matter enough to name, because "DGPS" and "estimated" are not the same claim.
_GGA_QUALITY = {
    "0": "no fix",
    "1": "GPS",
    "2": "DGPS",
    "3": "PPS",
    "4": "RTK fixed",
    "5": "RTK float",
    "6": "estimated",
}


def parse_sentence(line: str) -> Fix | None:
    """One NMEA sentence to a Fix, or None if it is not one we use.

    Returns None rather than raising for anything malformed. A GPS on a serial
    line produces occasional garbage -- a half-written sentence at startup, a
    dropped byte -- and none of it should reach a traceback.
    """
    match = _SENTENCE.match(line.strip())
    if not match:
        return None
    if checksum(match["body"]) != match["checksum"].upper():
        return None

    fields = match["body"].split(",")
    kind = match["kind"]

    if kind == "GGA":
        if len(fields) < 8:
            return None
        quality_code = fields[6]
        if quality_code in ("", "0"):
            return None  # No fix: not a position, and not an error either.
        lat = _degrees(fields[2], fields[3])
        lon = _degrees(fields[4], fields[5])
        if lat is None or lon is None:
            return None
        try:
            satellites = int(fields[7]) if fields[7] else None
        except ValueError:
            satellites = None
        return Fix(
            lat=lat,
            lon=lon,
            grid=latlon_to_grid(lat, lon, precision=8),
            quality=_GGA_QUALITY.get(quality_code, f"code {quality_code}"),
            satellites=satellites,
            utc=_timestamp(fields[1]),
        )

    # RMC
    if len(fields) < 10:
        return None
    if fields[2].upper() != "A":  # V means the data is not valid yet.
        return None
    lat = _degrees(fields[3], fields[4])
    lon = _degrees(fields[5], fields[6])
    if lat is None or lon is None:
        return None
    return Fix(
        lat=lat,
        lon=lon,
        grid=latlon_to_grid(lat, lon, precision=8),
        quality="GPS",
        utc=_timestamp(fields[1], fields[9]),
    )


def parse_gpsd_tpv(payload: dict[str, Any]) -> Fix | None:
    """A gpsd TPV report to a Fix.

    gpsd has already parsed the receiver's sentences, so this is a much simpler
    job than NMEA -- and gpsd is what is already running on most Linux
    handhelds, which is why it is the recommended path.
    """
    if payload.get("class") != "TPV":
        return None
    mode = payload.get("mode", 0)
    if not isinstance(mode, int) or mode < 2:
        return None  # 0 unknown, 1 no fix, 2 is 2D, 3 is 3D.

    lat, lon = payload.get("lat"), payload.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None

    utc = None
    if isinstance(payload.get("time"), str):
        try:
            utc = datetime.fromisoformat(payload["time"].replace("Z", "+00:00"))
        except ValueError:
            utc = None

    return Fix(
        lat=float(lat),
        lon=float(lon),
        grid=latlon_to_grid(float(lat), float(lon), precision=8),
        quality="3D" if mode == 3 else "2D",
        utc=utc,
    )


def clock_offset_seconds(fix_utc: datetime | None, now: datetime | None = None) -> float | None:
    """How far the system clock is from GPS time, in seconds.

    Reported, never corrected. Setting the clock needs privileges a dashboard
    has no business holding, and an operator who wants that has chrony or
    gpsd's own PPS handling, which do it properly.
    """
    if fix_utc is None:
        return None
    return ((now or datetime.now(UTC)) - fix_utc).total_seconds()

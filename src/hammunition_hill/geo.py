# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Maidenhead grids, great-circle bearing, and distance.

All of this runs on the operator's own numbers and never leaves the machine.
The browser needs the same maths for tier 0 panels, so the JavaScript in
``web/lib/geo.js`` mirrors this module -- if you change one, change both, and
the test suite checks them against each other.
"""

from __future__ import annotations

import math
import re

EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius
KM_PER_MILE = 1.609344

_GRID = re.compile(r"^[A-R]{2}(?:[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)?)?$", re.IGNORECASE)


class GridError(ValueError):
    """Raised for a Maidenhead locator that is not well formed."""


def grid_to_latlon(grid: str) -> tuple[float, float]:
    """Maidenhead locator to the latitude and longitude of its centre.

    Accepts 2, 4, 6, or 8 characters. Returning the centre rather than the
    south-west corner matters: a 4-character grid is roughly 70 x 110 km, and
    pointing a beam at its corner is a real error at HF distances.
    """
    text = grid.strip()
    if not _GRID.match(text):
        raise GridError(f"{grid!r} is not a Maidenhead locator")
    text = text.upper()

    lon = (ord(text[0]) - ord("A")) * 20.0 - 180.0
    lat = (ord(text[1]) - ord("A")) * 10.0 - 90.0
    lon_span, lat_span = 20.0, 10.0

    if len(text) >= 4:
        lon += int(text[2]) * 2.0
        lat += int(text[3]) * 1.0
        lon_span, lat_span = 2.0, 1.0

    if len(text) >= 6:
        lon += (ord(text[4]) - ord("A")) * (2.0 / 24.0)
        lat += (ord(text[5]) - ord("A")) * (1.0 / 24.0)
        lon_span, lat_span = 2.0 / 24.0, 1.0 / 24.0

    if len(text) >= 8:
        lon += int(text[6]) * (lon_span / 10.0)
        lat += int(text[7]) * (lat_span / 10.0)
        lon_span, lat_span = lon_span / 10.0, lat_span / 10.0

    return lat + lat_span / 2.0, lon + lon_span / 2.0


def latlon_to_grid(lat: float, lon: float, precision: int = 6) -> str:
    """Latitude and longitude to a Maidenhead locator of 2, 4, 6, or 8 chars."""
    if precision not in (2, 4, 6, 8):
        raise GridError("precision must be 2, 4, 6, or 8")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise GridError(f"({lat}, {lon}) is not a valid coordinate")

    # Clamp the poles and the dateline so the final field never overflows past R/X.
    adj_lon = min(lon + 180.0, 359.999999)
    adj_lat = min(lat + 90.0, 179.999999)

    chars = [
        chr(ord("A") + int(adj_lon // 20)),
        chr(ord("A") + int(adj_lat // 10)),
    ]
    if precision >= 4:
        chars += [str(int(adj_lon % 20 // 2)), str(int(adj_lat % 10 // 1))]
    if precision >= 6:
        chars += [
            chr(ord("A") + int(adj_lon % 2 / (2 / 24))),
            chr(ord("A") + int(adj_lat % 1 / (1 / 24))),
        ]
    if precision >= 8:
        chars += [
            str(int(adj_lon % (2 / 24) / (2 / 240))),
            str(int(adj_lat % (1 / 24) / (1 / 240))),
        ]
    return "".join(chars)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, in degrees true.

    This is the short-path heading. Long path is ``(bearing + 180) % 360``,
    which the UI offers alongside it -- on the low bands in the right conditions
    the long path is the one that works.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres, via haversine."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def km_to_miles(km: float) -> float:
    return km / KM_PER_MILE


def compass_point(bearing: float) -> str:
    """Bearing to a 16-point compass name, for the label next to the number."""
    points = (
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    )
    return points[int((bearing % 360) / 22.5 + 0.5) % 16]


def path(
    from_lat: float, from_lon: float, to_lat: float, to_lon: float
) -> dict[str, float | str]:
    """Everything the UI shows for one path, computed once."""
    short = bearing_deg(from_lat, from_lon, to_lat, to_lon)
    km = distance_km(from_lat, from_lon, to_lat, to_lon)
    return {
        "bearing": round(short, 1),
        "bearing_long": round((short + 180.0) % 360.0, 1),
        "compass": compass_point(short),
        "km": round(km, 1),
        "miles": round(km_to_miles(km), 1),
    }

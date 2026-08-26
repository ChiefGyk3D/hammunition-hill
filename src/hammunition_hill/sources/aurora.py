# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""NOAA's OVATION aurora forecast.

SWPC publishes a global grid of aurora probability -- 1024 longitudes by 181
latitudes, a quarter of a million points, several megabytes. Sending that to a
browser to draw would be absurd, so the collector reduces it to the two things
worth showing:

- **The oval boundary.** For each longitude, the equatorward edge of the aurora
  in each hemisphere. This is the line operators actually care about: HF paths
  crossing it degrade, and VHF paths along it sometimes open.
- **A coarse cell grid** above a visibility threshold, for shading the oval on
  the globe.

Reducing here rather than in the browser is the same principle as everywhere
else: the collector does the work once, on a schedule, and every viewer gets a
small file.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import SourceConfig
from .base import FetchError, get_bounded

# The raw grid is a few megabytes. Explicitly raised rather than loosening the
# global cap.
MAX_BYTES = 24 * 1024 * 1024

# Aurora probability, percent. Below this it is not worth drawing.
VISIBLE_THRESHOLD = 5

# Grid reduction. The source is 1024x181; drawn on a globe a few hundred pixels
# across, anything finer than this is invisible.
LON_STEP = 4
LAT_STEP = 2
MAX_CELLS = 4000


def _reduce(coordinates: list[list[float]]) -> dict[str, Any]:
    """Grid to oval boundaries plus a coarse cell list."""
    # SWPC gives longitude 0..359 east; convert to -180..180 for everything else.
    north: dict[int, int] = {}
    south: dict[int, int] = {}
    cells: list[list[float]] = []
    peak = 0

    for entry in coordinates:
        if len(entry) < 3:
            continue
        lon_raw, lat, value = entry[0], entry[1], entry[2]
        probability = int(value)
        if probability > peak:
            peak = probability
        if probability < VISIBLE_THRESHOLD:
            continue

        lon = lon_raw - 360 if lon_raw > 180 else lon_raw

        # Equatorward edge: the latitude closest to the equator that still has
        # aurora, per longitude, per hemisphere.
        key = int(lon)
        if lat >= 0:
            if key not in north or lat < north[key]:
                north[key] = int(lat)
        else:
            if key not in south or lat > south[key]:
                south[key] = int(lat)

        if int(lon_raw) % LON_STEP == 0 and int(lat) % LAT_STEP == 0:
            cells.append([round(lon, 1), round(lat, 1), probability])

    # Keep the strongest cells if the threshold let too many through.
    cells.sort(key=lambda c: -c[2])
    trimmed = cells[:MAX_CELLS]
    trimmed.sort(key=lambda c: (c[0], c[1]))

    return {
        "peak_probability": peak,
        "north_oval": [[lon, lat] for lon, lat in sorted(north.items())],
        "south_oval": [[lon, lat] for lon, lat in sorted(south.items())],
        "cells": trimmed,
        "cell_count": len(trimmed),
        "truncated": len(cells) > MAX_CELLS,
        "threshold": VISIBLE_THRESHOLD,
    }


class AuroraSource:
    kind = "aurora"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url, max_bytes=MAX_BYTES)
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc

        coordinates = payload.get("coordinates")
        if not isinstance(coordinates, list):
            raise FetchError(f"{cfg.url}: no coordinates grid")

        reduced = _reduce(coordinates)
        return {
            "observed_at": payload.get("Observation Time"),
            "forecast_at": payload.get("Forecast Time"),
            **reduced,
        }

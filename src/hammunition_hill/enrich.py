# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Joining spots to everything the operator already knows.

A raw cluster line is a callsign and a frequency. What an operator actually
wants to know is: *where is that, which way do I point, and do I need it?*
Answering the third question is the thing a hosted dashboard cannot do, because
the log is on this disk.

All three answers are computed here, once per spot, on this machine. The
callsign never leaves it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .adif import LogIndex
from .bands import classify, sort_key
from .geo import GridError, grid_to_latlon, path
from .licensing import guess_class
from .prefix import PrefixTable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Station:
    """Who and where the operator is. Used locally; never transmitted anywhere."""

    callsign: str | None = None
    grid: str | None = None
    lat: float | None = None
    lon: float | None = None
    license_class: str | None = None
    license_certain: bool = False
    license_reason: str | None = None

    @classmethod
    def from_config(cls, station: dict[str, Any], table: Any = None) -> Station:
        """Build from the ``[station]`` table, filling in what can be derived.

        Coordinates come from the grid square when not given explicitly, and the
        licence class is guessed from US callsign format when not configured.
        A configured value always wins -- the guess is a convenience, not a
        claim.
        """
        grid = station.get("grid")
        lat, lon = station.get("lat"), station.get("lon")

        if lat is None or lon is None:
            if grid:
                try:
                    lat, lon = grid_to_latlon(str(grid))
                except GridError:
                    log.warning(
                        "[station] grid %r is not a Maidenhead locator; "
                        "bearings and distances will be unavailable",
                        grid,
                    )
        callsign = str(station["callsign"]).upper() if station.get("callsign") else None

        configured = station.get("license_class")
        if configured:
            license_class: str | None = str(configured).strip().lower()
            certain, reason = True, "set in config"
        elif callsign:
            guess = guess_class(callsign, table)
            if guess is not None:
                license_class, certain, reason = guess.klass, guess.certain, guess.reason
            else:
                license_class, certain, reason = None, False, None
        else:
            license_class, certain, reason = None, False, None

        return cls(
            callsign=callsign,
            grid=str(grid).upper() if grid else None,
            lat=float(lat) if lat is not None else None,
            lon=float(lon) if lon is not None else None,
            license_class=license_class,
            license_certain=certain,
            license_reason=reason,
        )

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lon is not None


class Enricher:
    """Turns raw spots into what the UI renders.

    Holds the prefix table, the operator's location, and the current log index.
    The log index is swapped in wholesale when the log is re-read, so a reload
    never leaves half-updated state behind a spot render.
    """

    def __init__(self, table: PrefixTable, station: Station) -> None:
        self.table = table
        self.station = station
        self.log_index: LogIndex | None = None

    def set_log_index(self, index: LogIndex | None) -> None:
        self.log_index = index

    def _path_to(self, lat: float | None, lon: float | None) -> dict[str, Any] | None:
        if not self.station.located or lat is None or lon is None:
            return None
        return path(self.station.lat, self.station.lon, lat, lon)  # type: ignore[arg-type]

    def enrich_spot(self, raw: dict[str, Any]) -> dict[str, Any]:
        """One cluster spot, with entity, path, and needed status attached."""
        call = raw["call"]
        khz = raw["khz"]
        entity = self.table.lookup(call)

        info = classify(khz, raw.get("mode_from_comment"))
        spot: dict[str, Any] = {
            "call": call,
            "spotter": raw.get("spotter"),
            "khz": khz,
            "band": info.band,
            "mode": info.mode,
            "mode_inferred": info.mode_inferred,
            "comment": raw.get("comment", ""),
            "time": raw.get("time"),
            "spotted_at": raw.get("spotted_at"),
            "band_sort": sort_key(info.band),
        }

        if entity is not None:
            spot["entity"] = entity.name
            spot["continent"] = entity.continent
            spot["entity_approximate"] = entity.approximate
            spot["path"] = self._path_to(entity.lat, entity.lon)
        else:
            spot["entity"] = None
            spot["continent"] = None
            spot["entity_approximate"] = False
            spot["path"] = None

        if self.log_index is not None:
            spot["needed"] = self.log_index.status(spot["entity"], info.band, info.mode)

        return spot

    def enrich_spots(self, raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Newest first, which is the order the panel wants."""
        return [self.enrich_spot(raw) for raw in reversed(raws)]

    def enrich_activation(self, activation: dict[str, Any]) -> dict[str, Any]:
        """A POTA or SOTA activation, given a callsign and optionally a grid.

        Activations carry a park or summit reference with real coordinates far
        more often than a cluster spot does, so we prefer those and only fall
        back to the entity centroid.
        """
        call = activation.get("call")
        lat, lon = activation.get("lat"), activation.get("lon")

        if (lat is None or lon is None) and activation.get("grid"):
            try:
                lat, lon = grid_to_latlon(str(activation["grid"]))
            except GridError:
                lat = lon = None

        entity = self.table.lookup(call) if call else None
        if (lat is None or lon is None) and entity is not None:
            lat, lon = entity.lat, entity.lon

        enriched = dict(activation)
        enriched["entity"] = entity.name if entity else None
        enriched["continent"] = entity.continent if entity else None
        enriched["path"] = self._path_to(lat, lon)

        khz = activation.get("khz")
        if khz:
            info = classify(float(khz), activation.get("mode"))
            enriched["band"] = info.band
            enriched["mode"] = info.mode
            enriched["band_sort"] = sort_key(info.band)
            if self.log_index is not None:
                enriched["needed"] = self.log_index.status(enriched["entity"], info.band, info.mode)

        return enriched

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fixture documents shaped like the engine's `repeaters-list` and `station`.

The shapes are Hammunition's RepeatersListDocument and StationDocument
(docs/reference/json-interface.md there). Every value is invented: the grid is
the project's placeholder, the callsigns are not real, and the positions are
well-known city centres so a reader can check a distance by eye. Nothing here
was copied from a real station or a real layer.
"""

from __future__ import annotations

import copy
from typing import Any

# The station's grid, a placeholder (never a real one in this repository).
GRID = "FN31pr"
# FN31pr's centre, worked out by hand in tests/test_repeaters.py.
GRID_LAT, GRID_LON = 41.72916666666667, -72.70833333333333

REPEATERBOOK_CREDIT = (
    "RepeaterBook data, for personal use on this machine (https://www.repeaterbook.com)"
)
OPEN_CREDIT = "Open Repeater data, CC0-1.0 (fixture)"
OSM_CREDIT = "(c) OpenStreetMap contributors, ODbL (fixture)"


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "callsign": "",
        "output_hz": 0,
        "offset_hz": None,
        "tone": "",
        "mode": "FM",
        "place": "",
        "notes": "",
        "use": "OPEN",
        "status": "",
        "updated": "",
        "label": "",
        "lat": 0.0,
        "lon": 0.0,
        "source": "open-repeater-json",
        "also": [],
        "layer": "open-repeater",
        "personal_use": False,
    }
    row.update(over)
    return row


def station_document(grid: str | None = GRID) -> dict[str, Any]:
    return {
        "schema": "hammunition/1",
        "kind": "station",
        "engine": "0.0-fixture",
        "path": "/nowhere/station.yml",
        "file_exists": True,
        "callsign": "N0CALL",
        "grid_square": grid,
        "node_alias": None,
        "map_regions": [],
    }


def listing_document() -> dict[str, Any]:
    """Two layers: RepeaterBook (personal use) and an open one.

    Rows: W1AAA is open-only; W1BBB is RepeaterBook-only; W1CCC is in both
    (kept from the open layer, `also` naming RepeaterBook, so personal_use is
    true -- the engine's rule, D-081); W1DDD is a DMR repeater on 70 cm.
    """
    return {
        "schema": "hammunition/1",
        "kind": "repeaters-list",
        "engine": "0.0-fixture",
        "directory": "/nowhere/overlays/repeaters",
        "layers": [
            {
                "id": "open-repeater",
                "name": "Open Repeater",
                "description": OPEN_CREDIT,
                "day": "2026-10-01",
                "rows": 3,
                "sources": ["open-repeater-json"],
                "personal_use": False,
                "unverified": False,
                "files": ["rows.json"],
            },
            {
                "id": "repeaterbook",
                "name": "RepeaterBook",
                "description": REPEATERBOOK_CREDIT,
                "day": "2026-10-02",
                "rows": 2,
                "sources": ["repeaterbook-api"],
                "personal_use": True,
                "unverified": True,
                "files": ["rows.json"],
            },
        ],
        "skipped": [{"layer": "osm", "reason": "a layer not present"}],
        "rows": [
            _row(
                callsign="W1AAA",
                output_hz=146_940_000,
                offset_hz=-600_000,
                tone="100.0",
                place="Boston, MA",
                lat=42.3601,
                lon=-71.0589,
            ),
            _row(
                callsign="W1BBB",
                output_hz=147_030_000,
                offset_hz=600_000,
                tone="127.3",
                place="New York, NY",
                lat=40.7128,
                lon=-74.0060,
                source="repeaterbook-api",
                layer="repeaterbook",
                personal_use=True,
            ),
            _row(
                callsign="W1CCC",
                output_hz=145_230_000,
                offset_hz=-600_000,
                tone="88.5",
                place="Hartford, CT",
                lat=41.7658,
                lon=-72.6734,
                also=["repeaterbook-api"],
                personal_use=True,
            ),
            _row(
                callsign="W1DDD",
                output_hz=442_000_000,
                offset_hz=5_000_000,
                mode="DMR",
                place="Providence, RI",
                lat=41.8240,
                lon=-71.4128,
            ),
        ],
        "merged": 1,
        "credits": [OPEN_CREDIT, REPEATERBOOK_CREDIT],
    }


def empty_listing() -> dict[str, Any]:
    doc = copy.deepcopy(listing_document())
    doc.update(layers=[], skipped=[], rows=[], merged=0, credits=[])
    return doc

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
        "modes": ["FM"],
        "band": "2m",
        "digital": {},
        "distance_km": None,
        "bearing_deg": None,
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
                modes=["DMR"],
                band="70cm",
                digital={"dmr_color_code": "1", "dmr_network": "Brandmeister"},
                place="Providence, RI",
                lat=41.8240,
                lon=-71.4128,
            ),
        ],
        "merged": 1,
        "credits": [OPEN_CREDIT, REPEATERBOOK_CREDIT],
        "centre": {"lat": GRID_LAT, "lon": GRID_LON, "source": "station"},
        "within_km": None,
    }


def legacy_listing_document() -> dict[str, Any]:
    """The same document as an engine that predates the mode vocabulary prints it
    (Hammunition before #316): no ``modes``, ``band``, ``digital``, ``distance_km``
    or ``bearing_deg`` on a row, and no ``centre`` or ``within_km``."""
    doc = copy.deepcopy(listing_document())
    for key in ("centre", "within_km"):
        del doc[key]
    for r in doc["rows"]:
        for key in ("modes", "band", "digital", "distance_km", "bearing_deg"):
            del r[key]
    return doc


def modes_listing_document() -> dict[str, Any]:
    """Every mode of the engine's vocabulary, over four bands, all from the open layer
    (so nothing here is RepeaterBook's). Callsigns are invented; positions are city
    centres. Each digital key appears on at least one row."""
    doc = copy.deepcopy(listing_document())
    extra = [
        _row(
            callsign="W1EEE",
            output_hz=147_345_000,
            mode="FM, D-STAR",
            modes=["FM", "D-STAR"],
            digital={"dstar_module": "B", "dstar_gateway": "W1EEE G"},
            place="Worcester, MA",
            lat=42.2626,
            lon=-71.8023,
        ),
        _row(
            callsign="W1FFF",
            output_hz=444_500_000,
            mode="YSF",
            modes=["YSF"],
            band="70cm",
            digital={"ysf_dgid": "00"},
            place="Springfield, MA",
            lat=42.1015,
            lon=-72.5898,
        ),
        _row(
            callsign="W1GGG",
            output_hz=449_925_000,
            mode="P25",
            modes=["P25"],
            band="70cm",
            digital={"p25_nac": "293"},
            place="Albany, NY",
            lat=42.6526,
            lon=-73.7562,
        ),
        _row(
            callsign="W1HHH",
            output_hz=446_000_000,
            mode="NXDN",
            modes=["NXDN"],
            band="70cm",
            digital={"nxdn_ran": "1"},
            place="New Haven, CT",
            lat=41.3083,
            lon=-72.9279,
        ),
        _row(
            callsign="W1III",
            output_hz=223_900_000,
            mode="M17",
            modes=["M17"],
            band="1.25m",
            place="Portland, ME",
            lat=43.6591,
            lon=-70.2568,
        ),
        _row(
            callsign="W1JJJ",
            output_hz=430_000_000,
            mode="TETRA",
            modes=["TETRA"],
            band="70cm",
            place="Burlington, VT",
            lat=44.4759,
            lon=-73.2121,
        ),
        _row(
            callsign="W1KKK",
            output_hz=1_294_500_000,
            mode="ATV",
            modes=["ATV"],
            band="23cm",
            place="Concord, NH",
            lat=43.2081,
            lon=-71.5376,
        ),
        _row(
            callsign="W1LLL",
            output_hz=145_470_000,
            mode="FM, DMR",
            modes=["FM", "DMR"],
            digital={"dmr_color_code": "3", "dmr_id": "310999"},
            place="Manchester, NH",
            lat=42.9956,
            lon=-71.4548,
        ),
    ]
    doc["rows"].extend(extra)
    doc["layers"][0]["rows"] = 3 + len(extra)
    return doc


def empty_listing() -> dict[str, Any]:
    doc = copy.deepcopy(listing_document())
    doc.update(layers=[], skipped=[], rows=[], merged=0, credits=[])
    return doc

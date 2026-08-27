# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""geo.py and web/lib/callsign.js are the same maths written twice.

`tests/test_geo.py` proves the Python is right. Nothing proved the JavaScript
agreed with it, and the browser is where most of these numbers are actually
seen: the callsign panel resolves a prefix and shows a bearing without asking
the collector for anything, which is the whole point of publishing the prefix
table as a snapshot.

So a grid square that converts one way in a test and another way on screen is a
bug nothing else here would catch. This runs the browser copy under node against
the same inputs and demands the same answers.

Maidenhead is the part most worth pinning: three levels of precision, characters
carrying different spans at each, and every implementation of it in the world
has an off-by-one somewhere near the poles or the antimeridian.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from hammunition_hill import geo

# Squares chosen to exercise the corners rather than the middle: both poles,
# both sides of the antimeridian, the origin, a field with no sub-square, and a
# handful of real stations.
GRIDS = [
    "AA00",
    "RR99",
    "JJ00aa",
    "DM79",
    "DM79lv",
    "FN31pr",
    "IO91",
    "JO65",
    "PM95",
    "QF56",
    "GF15",
    "BP51",
    "AR09",
    "RA00",
    "KP",
    "AA",
    "RR",
]

# Two points per path, including antipodal-ish and same-point cases.
PAIRS = [
    ("DM79", "FN31pr"),
    ("DM79", "JO65"),
    ("IO91", "QF56"),
    ("AA00", "RR99"),
    ("DM79", "DM79"),
    ("JJ00aa", "PM95"),
    ("BP51", "GF15"),
]


def test_the_browser_geo_matches_this_module():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    points = [geo.grid_to_latlon(grid) for grid in GRIDS]

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{
  bearingDeg, compassPoint, distanceKm, gridToLatLon, latLonToGrid, pathTo,
}} from "{root / "web/lib/callsign.js"}";

const grids = {json.dumps(GRIDS)};
const points = {json.dumps(points)};
const pairs = {json.dumps(PAIRS)};

const out = {{ toLatLon: {{}}, toGrid: {{}}, path: {{}}, compass: {{}} }};

for (const g of grids) out.toLatLon[g] = gridToLatLon(g);
for (let i = 0; i < grids.length; i += 1) {{
  const [lat, lon] = points[i];
  out.toGrid[grids[i]] = {{
    4: latLonToGrid(lat, lon, 4),
    6: latLonToGrid(lat, lon, 6),
  }};
}}
for (const [a, b] of pairs) {{
  const [fromLat, fromLon] = gridToLatLon(a);
  const [toLat, toLon] = gridToLatLon(b);
  out.path[`${{a}}>${{b}}`] = {{
    ...pathTo({{ lat: fromLat, lon: fromLon }}, toLat, toLon),
    raw_bearing: bearingDeg(fromLat, fromLon, toLat, toLon),
    raw_km: distanceKm(fromLat, fromLon, toLat, toLon),
  }};
}}
for (let b = 0; b < 360; b += 3) out.compass[b] = compassPoint(b);
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )

        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        js = json.loads(result.stdout)

    # --- grid -> lat/lon
    for grid, (lat, lon) in zip(GRIDS, points, strict=True):
        got = js["toLatLon"][grid]
        assert got is not None, f"the browser rejected {grid!r}, which geo.py accepts"
        assert got[0] == pytest.approx(lat, abs=1e-9), f"{grid} latitude"
        assert got[1] == pytest.approx(lon, abs=1e-9), f"{grid} longitude"

    # --- lat/lon -> grid, at both precisions the UI uses
    for grid, (lat, lon) in zip(GRIDS, points, strict=True):
        for precision in (4, 6):
            want = geo.latlon_to_grid(lat, lon, precision)
            got = js["toGrid"][grid][str(precision)]
            assert got == want, f"latLonToGrid({lat}, {lon}, {precision}) from {grid}"

    # --- whole paths, and the unrounded numbers behind them
    for a, b in PAIRS:
        from_lat, from_lon = geo.grid_to_latlon(a)
        to_lat, to_lon = geo.grid_to_latlon(b)
        want = geo.path(from_lat, from_lon, to_lat, to_lon)
        got = js["path"][f"{a}>{b}"]
        for field in ("bearing", "bearing_long", "km", "miles"):
            assert got[field] == pytest.approx(want[field], abs=0.05), f"{a}>{b} {field}"
        assert got["compass"] == want["compass"], f"{a}>{b} compass"
        assert got["raw_bearing"] == pytest.approx(
            geo.bearing_deg(from_lat, from_lon, to_lat, to_lon), abs=1e-9
        )
        assert got["raw_km"] == pytest.approx(
            geo.distance_km(from_lat, from_lon, to_lat, to_lon), abs=1e-9
        )

    # --- the compass rose, all the way round
    for bearing in range(0, 360, 3):
        assert js["compass"][str(bearing)] == geo.compass_point(float(bearing)), bearing


def test_a_round_trip_through_the_grid_lands_back_in_the_same_square():
    """Not a drift check -- a check that the shared idea is sound at all."""
    for grid in GRIDS:
        lat, lon = geo.grid_to_latlon(grid)
        assert geo.latlon_to_grid(lat, lon, len(grid)).upper() == grid.upper()

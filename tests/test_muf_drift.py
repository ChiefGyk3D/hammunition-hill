# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""minimuf.py and web/lib/muf.js are the same model written twice.

The browser copy is the one operators actually see -- the path panel calls it
for every hour of the chart -- so the two drifting apart would mean the tests
prove one model while the screen shows another. Same discipline as
test_geo_drift.py: run the JavaScript under node on the same inputs, demand
the same numbers.

The tolerance is a milli-MHz. The model's honest error is 3.8 MHz RMS, but
that is the model against the ionosphere; the two copies of the model against
each other have no excuse.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from itertools import product
from pathlib import Path

import pytest

from hammunition_hill.minimuf import path_muf, sunspots_from_flux

# Paths chosen to hit both loop shapes (one and two control points), both
# hemispheres, a meridian path, the date line, and both envelope refusals.
PATHS = [
    (39.7, -105.0, 42.4, -71.1),  # Denver-Boston, single control point
    (39.7, -105.0, 35.7, 139.7),  # Denver-Tokyo, two, over the date line
    (42.4, -71.1, -34.6, -58.4),  # Boston-Buenos Aires, transequatorial
    (51.5, 0.0, 40.4, -3.7),  # London-Madrid, short
    (10.0, -100.0, -10.0, -100.0),  # same meridian, equator crossing
    (39.7, -105.0, 39.8, -105.1),  # too short: both must refuse
    (39.7, -105.0, -31.9, 115.9),  # too long: both must refuse
    (60.2, 24.9, 21.3, -157.9),  # Helsinki-Honolulu, high-latitude start
]

HOURS = [0.0, 5.5, 12.0, 18.25, 23.0]
FLUXES = [70.0, 110.0, 150.0, 213.0, 280.0]
DATES = [(3, 20), (6, 21), (12, 21)]


def test_the_browser_muf_matches_this_module():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    cases = [
        {
            "sfi": sfi,
            "month": month,
            "day": day,
            "utcHour": hour,
            "lat1": p[0],
            "lon1": p[1],
            "lat2": p[2],
            "lon2": p[3],
        }
        for p, hour, sfi, (month, day) in product(PATHS, HOURS, FLUXES[:3], DATES[:2])
    ]

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{ pathMuf, sunspotsFromFlux }} from "{root / "web/lib/muf.js"}";
const cases = {json.dumps(cases)};
const fluxes = {json.dumps(FLUXES)};
const out = {{
  muf: cases.map((c) => pathMuf(c)),
  ssn: fluxes.map((f) => sunspotsFromFlux(f)),
}};
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        js = json.loads(result.stdout)

    for case, got in zip(cases, js["muf"], strict=True):
        want = path_muf(
            sfi=case["sfi"],
            month=case["month"],
            day=case["day"],
            utc_hour=case["utcHour"],
            lat1=case["lat1"],
            lon1=case["lon1"],
            lat2=case["lat2"],
            lon2=case["lon2"],
        )
        if want is None:
            assert got is None, f"{case}: python refuses this path, the browser answered {got}"
        else:
            assert got == pytest.approx(want, abs=1e-3), case

    for flux, got in zip(FLUXES, js["ssn"], strict=True):
        assert got == pytest.approx(sunspots_from_flux(flux), abs=1e-9), flux

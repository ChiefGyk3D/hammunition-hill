# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The map projections, checked against what they claim to be.

A projection is the one piece of the frontend where "it rendered without
throwing" proves almost nothing. A wrong sign, a swapped numerator, a radius
scaled by pi instead of 2 pi -- all of them draw a plausible-looking blob of
coastline, and the render check in CI passes on every one of them. What catches
them is asserting the property the projection exists for.

So each mode is tested on its own promise:

* **Azimuthal equidistant** promises that the screen angle from the centre *is*
  the true bearing, and that the distance from the centre is linear in the
  great-circle distance all the way to the antipode on the rim. That is the
  entire reason to have it on a ham radio map -- point the beam at the angle
  you see -- so it is the thing worth pinning. ``geo.py`` supplies the
  bearings and distances it is checked against, which makes this a cross-check
  between two independent implementations rather than a restatement.
* **Orthographic** promises the far side of the sphere is hidden.
* **Equirectangular** promises longitude maps linearly to x.

All three promise that unprojecting a projected point lands back where it
started, which is what makes clicking the map to plot a path work.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from hammunition_hill import geo

# Half the Earth's circumference on the same sphere geo.py uses: the distance
# at which the azimuthal rim sits, by definition.
ANTIPODAL_KM = geo.distance_km(0.0, 0.0, 0.0, 180.0)

CENTRE = (39.74, -104.98)  # Denver

# Targets spread over every quadrant and out to the far side, because a
# projection that is right in one octant and wrong in another is the usual
# shape of an atan2 mistake.
TARGETS = [
    (51.4779, 0.0),
    (35.68, 139.69),
    (-33.87, 151.21),
    (-77.85, 166.67),
    (90.0, 0.0),
    (-90.0, 0.0),
    (0.0, -104.98),
    (0.0, 75.02),
    (39.74, 75.02),
    (-39.74, 75.02),  # the antipode of the centre
    (1.0, -179.0),
    (1.0, 179.0),
]

VIEW = {"lat0": CENTRE[0], "lon0": CENTRE[1], "radius": 200.0, "cx": 250.0, "cy": 250.0}


def _run(script: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "projection.mjs"
        driver.write_text(
            f'import {{ project, unproject }} from "{root / "web/lib/globe.js"}";\n{script}',
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


def _projected(view_extra: str) -> dict:
    return _run(
        f"""
const view = {{ ...{json.dumps(VIEW)}, {view_extra} }};
const targets = {json.dumps(TARGETS)};
const out = [];
for (const [lat, lon] of targets) {{
  const p = project(lat, lon, view);
  out.push({{ ...p, back: unproject(p.x, p.y, view) }});
}}
console.log(JSON.stringify({{ view, points: out }}));
"""
    )


def test_azimuthal_screen_angle_is_the_true_bearing():
    """The promise the projection is for: point the beam at the screen angle."""
    result = _projected("azimuthal: true")
    for (lat, lon), point in zip(TARGETS, result["points"], strict=True):
        if (lat, lon) == (-39.74, 75.02):
            continue  # the antipode: every bearing lands on the rim, so none is wrong
        screen = math.degrees(math.atan2(point["x"] - VIEW["cx"], VIEW["cy"] - point["y"])) % 360
        want = geo.bearing_deg(*CENTRE, lat, lon)
        # The short way round, so 359.9 and 0.1 do not read as 359.8 apart.
        apart = abs(((screen - want + 180) % 360) - 180)
        assert apart < 0.01, f"{lat},{lon}: screen bearing {screen}, true bearing {want}"


def test_azimuthal_radius_is_linear_in_great_circle_distance():
    """Equidistant is the other half of the name, and the half easiest to lose.

    Scaling the radius by anything but distance/half-circumference still draws
    a recognisable map -- it just quietly stops being a scale you can measure
    against, which is the only reason the rings are worth drawing.
    """
    result = _projected("azimuthal: true")
    for (lat, lon), point in zip(TARGETS, result["points"], strict=True):
        radius = math.hypot(point["x"] - VIEW["cx"], point["y"] - VIEW["cy"])
        want = geo.distance_km(*CENTRE, lat, lon) / ANTIPODAL_KM * VIEW["radius"]
        assert radius == pytest.approx(want, abs=0.02), f"{lat},{lon}"


def test_azimuthal_puts_the_antipode_on_the_rim_and_nothing_beyond_it():
    result = _projected("azimuthal: true")
    for point in result["points"]:
        radius = math.hypot(point["x"] - VIEW["cx"], point["y"] - VIEW["cy"])
        assert radius <= VIEW["radius"] + 1e-6, "a point projected outside the disc"
        assert point["visible"] is True, "azimuthal hides nothing; the whole world is on it"

    antipode = result["points"][TARGETS.index((-39.74, 75.02))]
    radius = math.hypot(antipode["x"] - VIEW["cx"], antipode["y"] - VIEW["cy"])
    assert radius == pytest.approx(VIEW["radius"], abs=1e-6)


def test_azimuthal_puts_north_straight_up_from_the_centre():
    """A whole class of sign errors shows up here and nowhere else."""
    result = _projected("azimuthal: true")
    pole = result["points"][TARGETS.index((90.0, 0.0))]
    assert pole["x"] == pytest.approx(VIEW["cx"], abs=1e-6)
    assert pole["y"] < VIEW["cy"], "the north pole must be above a northern-hemisphere centre"


@pytest.mark.parametrize("mode", ["azimuthal: true", "flat: true, halfW: 200, halfH: 100", ""])
def test_every_projection_round_trips(mode):
    """Clicking the map to plot a path is exactly this, so it has to hold."""
    result = _projected(mode)
    for (lat, lon), point in zip(TARGETS, result["points"], strict=True):
        if not point["visible"] or point["back"] is None:
            continue
        back = point["back"]
        # Longitude is meaningless at the poles, so only latitude is demanded
        # there -- and demanding it anyway is how you get a test that fails on
        # a correct implementation.
        assert back["lat"] == pytest.approx(lat, abs=1e-6), f"{lat},{lon} latitude"
        if abs(lat) < 89.9:
            apart = abs(((back["lon"] - lon + 180) % 360) - 180)
            assert apart < 1e-6, f"{lat},{lon} longitude came back as {back['lon']}"


def test_the_globe_hides_the_far_side():
    """Orthographic's promise, and what the limb test in strokePath relies on."""
    result = _projected("")
    antipode = result["points"][TARGETS.index((-39.74, 75.02))]
    assert antipode["visible"] is False
    near = result["points"][TARGETS.index((51.4779, 0.0))]
    assert near["visible"] is True


def test_the_flat_map_is_linear_in_longitude():
    result = _projected("flat: true, halfW: 200, halfH: 100")
    view = {**VIEW, "halfW": 200.0}
    for (lat, lon), point in zip(TARGETS, result["points"], strict=True):
        wrapped = ((lon - CENTRE[1] + 540) % 360) - 180
        assert point["x"] == pytest.approx(view["cx"] + wrapped / 180 * view["halfW"], abs=1e-6), (
            f"{lat},{lon}"
        )

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The flat map's terminator, checked against what the shading is supposed to mean.

The greyline had no test of its own until this file, which is the gap worth
closing: nothing anywhere asserted that the shaded half of the flat map is the
half where the sun is down. A wrong sign draws a plausible curve and the render
check passes on it.

These tests were written alongside replacing the old implementation, which
projected the terminator ring and sorted the points by screen x. Near an
equinox that ordering is not well defined -- the terminator runs through both
poles, so at the March 2026 equinox 361 ring points land on 18 distinct
columns against 344 at the solstice. Worth saying plainly: that was a
fragility, not a visible defect. The sorted points all still lay on the
terminator, so the old path mis-shaded 0.00% of a 65,000-point grid, and the
two render within a pixel of each other. What it lacked was any reason to
believe that beyond having looked.

So the properties pinned here are the meaning, not the shape:

* every point on the drawn curve is a point where the sun is on the horizon,
  cross-checked against ``solarElevation`` rather than against a snapshot;
* the shaded side of that curve is the side where the sun is *below* the
  horizon, checked over a grid;
* the curve is single-valued in longitude, which is what the closed form buys
  and what the sort could not promise.

Equinoxes are in the sample deliberately, and so is the exact-zero declination
that makes the closed form divide by zero.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Two equinoxes, two solstices, and times of day that put the subsolar point in
# different quadrants -- an atan2 or sign mistake is usually right in one and
# wrong in another.
MOMENTS = [
    "2026-03-20T18:30:00Z",  # what the render harness freezes at
    "2026-03-20T06:00:00Z",
    "2026-09-23T06:00:00Z",
    "2026-06-21T12:00:00Z",
    "2026-12-21T00:00:00Z",
    "2026-06-21T23:00:00Z",
]

VIEW = {
    "flat": True,
    "lat0": 0.0,
    "lon0": 0.0,
    "halfW": 360.0,
    "halfH": 180.0,
    "cx": 400.0,
    "cy": 200.0,
}

# A view panned off the prime meridian, because the curve is walked from the
# map's own left edge and a centre that is not zero is where that goes wrong.
VIEW_PANNED = {**VIEW, "lon0": -104.98}

GRID_TOLERANCE_DEG = 0.75
"""How close to the terminator a grid point may be and still be skipped.

Right at the line the sun is on the horizon and "night" is a coin flip, so
disagreement there means nothing. The grid steps three degrees, so this
excludes only the cells the line actually passes through.
"""


def _run(script: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "terminator.mjs"
        driver.write_text(
            f'import {{ flatTerminator, mapRect }} from "{root / "web/lib/globe.js"}";\n'
            f'import {{ subsolarPoint, solarElevation }} from "{root / "web/lib/solar.js"}";\n'
            f"{script}",
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


def _curves(view: dict) -> dict:
    return _run(
        f"""
const view = {json.dumps(view)};
const out = {{}};
for (const iso of {json.dumps(MOMENTS)}) {{
  const sun = subsolarPoint(new Date(iso));
  const {{ points, nightPole }} = flatTerminator(sun, view);
  out[iso] = {{
    sun,
    nightPole,
    rect: mapRect(view),
    points: points.map((p) => ({{
      ...p,
      elevation: solarElevation(p.lat, p.lon, sun),
    }})),
  }};
}}
console.log(JSON.stringify(out));
"""
    )


@pytest.fixture(scope="module")
def curves() -> dict:
    return _curves(VIEW)


def test_every_drawn_point_is_on_the_horizon(curves):
    """The curve is the greyline, so the sun is at zero elevation along it."""
    for iso, curve in curves.items():
        worst = max(abs(p["elevation"]) for p in curve["points"])
        assert worst < 1e-6, f"{iso}: drawn point {worst} degrees off the horizon"


def test_the_curve_is_single_valued_in_longitude(curves):
    """What the equinox broke: one latitude per column, left edge to right."""
    for iso, curve in curves.items():
        xs = [p["x"] for p in curve["points"]]
        assert xs == sorted(xs), f"{iso}: the curve doubles back"
        assert len(set(xs)) == len(xs), f"{iso}: two latitudes share a column"
        rect = curve["rect"]
        assert xs[0] == pytest.approx(rect["x"])
        assert xs[-1] == pytest.approx(rect["x"] + rect["w"])


def test_the_shaded_side_is_the_dark_side(curves):
    """The property the rectangle violated, and the one the shading means.

    A point is shaded when it lies between the curve and the pole in darkness.
    That has to agree with the sun actually being below the horizon there.
    """
    for iso, curve in curves.items():
        sun = curve["sun"]
        night_pole = curve["nightPole"]
        by_lon = {round(p["lon"], 6): p["lat"] for p in curve["points"]}

        checked = 0
        for lon_key, terminator_lat in by_lon.items():
            for step in range(-29, 30):
                lat = step * 3.0
                # Shaded iff on the night pole's side of the terminator.
                shaded = lat < terminator_lat if night_pole < 0 else lat > terminator_lat
                elevation = _elevation(lat, lon_key, sun)
                if abs(elevation) < GRID_TOLERANCE_DEG:
                    continue
                checked += 1
                assert shaded == (elevation < 0), (
                    f"{iso}: ({lat}, {lon_key}) shaded={shaded} but solar elevation is {elevation}"
                )
        assert checked > 10_000, f"{iso}: only {checked} grid points carried the test"


def test_night_wraps_the_pole_away_from_the_sun(curves):
    for iso, curve in curves.items():
        sun = curve["sun"]
        if abs(sun["lat"]) < 0.01:
            continue  # at a true equinox neither pole is lit; either answer draws the same band
        want = -90 if sun["lat"] > 0 else 90
        assert curve["nightPole"] == want, iso


def test_the_equinox_curve_spans_pole_to_pole(curves):
    """Not a rectangle, and not a flat line either.

    At an equinox the terminator is two near-vertical meridians, so the curve
    has to reach both poles. The rectangle the old code drew spanned barely any
    latitude at all, which is what this would have caught.
    """
    curve = curves["2026-03-20T18:30:00Z"]
    lats = [p["lat"] for p in curve["points"]]
    assert min(lats) < -89.0, f"curve stops at {min(lats)} in the south"
    assert max(lats) > 89.0, f"curve stops at {max(lats)} in the north"


def test_a_solstice_curve_is_a_gentle_wave():
    """The other end of the range: it must not have become vertical everywhere."""
    curve = _curves(VIEW)["2026-06-21T12:00:00Z"]
    lats = [p["lat"] for p in curve["points"]]
    # The terminator at the solstice reaches the Antarctic/Arctic circles, not the poles.
    assert 60.0 < max(lats) < 75.0, max(lats)
    assert -75.0 < min(lats) < -60.0, min(lats)


def test_exact_zero_declination_draws_the_vertical_band():
    """The closed form divides by tan(dec); at a true equinox that is zero.

    The shape it should degenerate to is two vertical meridians a quarter turn
    from the sun. Every column is pinned to one pole or the other, except the
    two meridians themselves -- and there the terminator is the whole column,
    so whatever latitude the sample lands on is on it. Those two samples are
    the segment that draws the band's vertical edge.
    """
    sun_lon = 17.0
    result = _run(
        """
const view = """
        + json.dumps(VIEW)
        + f"""
const {{ points }} = flatTerminator({{ lat: 0, lon: {sun_lon} }}, view);
console.log(JSON.stringify({{
  nan: points.filter((p) => !Number.isFinite(p.lat) || !Number.isFinite(p.y)).length,
  points: points.map((p) => ({{ lon: p.lon, lat: p.lat }})),
}}));
"""
    )
    assert result["nan"] == 0

    at_pole = [p for p in result["points"] if abs(abs(p["lat"]) - 90.0) < 1e-6]
    between = [p for p in result["points"] if abs(abs(p["lat"]) - 90.0) >= 1e-6]

    assert len(between) == 2, [p["lon"] for p in between]
    quarter_turns = sorted(((sun_lon + turn + 180) % 360) - 180 for turn in (90, -90))
    assert sorted(round(p["lon"], 6) for p in between) == pytest.approx(quarter_turns)
    assert len(at_pole) == len(result["points"]) - 2


def test_a_panned_view_still_spans_its_own_map():
    """Longitude is walked from the map's left edge, not the prime meridian."""
    for iso, curve in _curves(VIEW_PANNED).items():
        rect = curve["rect"]
        xs = [p["x"] for p in curve["points"]]
        assert xs[0] == pytest.approx(rect["x"]), iso
        assert xs[-1] == pytest.approx(rect["x"] + rect["w"]), iso
        lons = [p["lon"] for p in curve["points"]]
        assert lons[0] == pytest.approx(VIEW_PANNED["lon0"] - 180)
        assert lons[-1] == pytest.approx(VIEW_PANNED["lon0"] + 180)
        worst = max(abs(p["elevation"]) for p in curve["points"])
        assert worst < 1e-6, iso


def _elevation(lat: float, lon: float, sun: dict) -> float:
    """Solar elevation, in Python, so the JS value is checked against something else."""
    import math

    a = math.radians(lat)
    b = math.radians(sun["lat"])
    dl = math.radians(lon - sun["lon"])
    cos_zenith = math.sin(a) * math.sin(b) + math.cos(a) * math.cos(b) * math.cos(dl)
    return math.degrees(math.asin(max(-1.0, min(1.0, cos_zenith))))

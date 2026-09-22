# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ephemeris.py and web/lib/ephemeris.js are the same maths written twice.

`tests/test_ephemeris.py` proves the Python is right against published values.
Nothing there looks at the browser copy, and the browser copy is the one an
operator actually reads: the Sun & Moon panel computes every number on screen
itself, because that is what makes it tier 0.

So a moonrise that is right in a test and ten minutes out on the wall is a bug
nothing else here would catch. This runs the browser file under node against
the same instants and demands the same answers.

The instants are chosen to break things rather than to pass: both solstices,
both equinoxes, a syzygy, a date inside the polar night, one on each side of
the antimeridian, and a southern-hemisphere station -- the places where a sign
error, a modulo that wraps the wrong way, or a hemisphere assumption shows up.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hammunition_hill import ephemeris

MOMENTS = [
    "1992-04-12T00:00:00Z",  # Meeus's worked example
    "2000-01-06T18:14:00Z",  # a new moon
    "2000-01-21T04:40:00Z",  # a full moon
    "2026-03-20T09:46:00Z",  # March equinox
    "2026-06-21T08:24:00Z",  # June solstice
    "2026-09-23T00:05:00Z",  # September equinox
    "2026-12-21T20:50:00Z",  # December solstice
    "2026-12-21T23:59:59Z",  # a day boundary, in the polar night
    "2027-07-04T12:00:00Z",
]

# lat, lon. Both hemispheres, both sides of the antimeridian, inside both polar
# circles, and the equator -- where the azimuth formula's denominator is at its
# least forgiving.
PLACES = [
    (39.74, -104.98),  # Denver
    (51.4779, 0.0),  # Greenwich
    (-33.87, 151.21),  # Sydney
    (35.68, 139.69),  # Tokyo
    (69.65, 18.96),  # Tromso
    (-77.85, 166.67),  # Ross Island
    (0.0, -179.5),  # equator, just west of the antimeridian
    (0.0, 179.5),  # equator, just east of it
]


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _seconds_apart(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.0
    left = datetime.fromisoformat(a.replace("Z", "+00:00"))
    right = datetime.fromisoformat(b.replace("Z", "+00:00"))
    return abs((left - right).total_seconds())


def test_the_browser_ephemeris_matches_this_module():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{
  moonPosition, lookAngles, moonLookAngles, sunEvents, moonEvents,
  greylineWindow, phaseName, sublunarPoint, celestialSubpoint,
}} from "{root / "web/lib/ephemeris.js"}";

const moments = {json.dumps(MOMENTS)};
const places = {json.dumps(PLACES)};

const out = {{ moon: {{}}, look: {{}}, sun: {{}}, moonEvents: {{}}, twilight: {{}}, phase: {{}} }};
const iso = (d) => (d === null || d === undefined ? null : new Date(d).toISOString());

for (const stamp of moments) {{
  const at = new Date(stamp);
  const m = moonPosition(at);
  out.moon[stamp] = {{
    lat: m.lat, lon: m.lon, distanceKm: m.distanceKm, parallaxDeg: m.parallaxDeg,
    eclipticLon: m.eclipticLon, illumination: m.illumination, ageDays: m.ageDays,
    elongation: m.elongation, phaseName: m.phaseName, waxing: m.waxing,
  }};
  out.look[stamp] = {{}};
  for (let i = 0; i < places.length; i += 1) {{
    const [lat, lon] = places[i];
    out.look[stamp][i] = {{
      geocentric: lookAngles(lat, lon, m.lat, m.lon),
      topocentric: moonLookAngles(lat, lon, m),
      sub: sublunarPoint(at),
      // A fixed celestial coordinate -- the Perseid radiant, which is what
      // the meteor panel turns into a look angle.
      radiant: celestialSubpoint(48.0, 58.0, at),
    }};
  }}
}}

for (const stamp of moments) {{
  const at = new Date(stamp);
  out.sun[stamp] = {{}};
  out.moonEvents[stamp] = {{}};
  out.twilight[stamp] = {{}};
  for (let i = 0; i < places.length; i += 1) {{
    const [lat, lon] = places[i];
    const pack = (e) => ({{
      rise: iso(e.rise), set: iso(e.set), transit: iso(e.transit),
      transitElevation: e.transitElevation, alwaysUp: e.alwaysUp, alwaysDown: e.alwaysDown,
    }});
    out.sun[stamp][i] = pack(sunEvents(lat, lon, at));
    out.moonEvents[stamp][i] = pack(moonEvents(lat, lon, at));
    out.twilight[stamp][i] = pack(greylineWindow(lat, lon, at));
  }}
}}

for (let e = 0; e < 360; e += 3) {{
  const p = phaseName(e);
  out.phase[e] = [p.name, p.waxing];
}}

console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )

        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, result.stderr
        js = json.loads(result.stdout)

    for stamp in MOMENTS:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))

        # --- lunar position and phase
        moon = ephemeris.moon_position(at)
        got = js["moon"][stamp]
        for field, want in (
            ("lat", moon.lat),
            ("lon", moon.lon),
            ("distanceKm", moon.distance_km),
            ("parallaxDeg", moon.parallax_deg),
            ("eclipticLon", moon.ecliptic_lon),
            ("illumination", moon.illumination),
            ("ageDays", moon.age_days),
            ("elongation", moon.elongation),
        ):
            assert got[field] == pytest.approx(want, rel=1e-9, abs=1e-9), f"{stamp} moon {field}"
        assert got["phaseName"] == moon.phase_name, f"{stamp} phase name"
        assert got["waxing"] == moon.waxing, f"{stamp} waxing"

        # --- look angles, geocentric and topocentric
        for index, (lat, lon) in enumerate(PLACES):
            key = f"{lat},{lon}"
            here = js["look"][stamp][str(index)]
            geocentric = ephemeris.look_angles(lat, lon, moon.lat, moon.lon)
            topocentric = ephemeris.moon_look_angles(lat, lon, moon)
            assert here["geocentric"]["elevation"] == pytest.approx(
                geocentric.elevation, abs=1e-9
            ), f"{stamp} {key} geocentric elevation"
            assert here["geocentric"]["azimuth"] == pytest.approx(geocentric.azimuth, abs=1e-9), (
                f"{stamp} {key} azimuth"
            )
            assert here["topocentric"]["elevation"] == pytest.approx(
                topocentric.elevation, abs=1e-9
            ), f"{stamp} {key} topocentric elevation"

            sub = ephemeris.sublunar_point(at)
            assert here["sub"]["lat"] == pytest.approx(sub.lat, abs=1e-9)
            assert here["sub"]["lon"] == pytest.approx(sub.lon, abs=1e-9)

            radiant = ephemeris.celestial_subpoint(48.0, 58.0, at)
            assert here["radiant"]["lat"] == pytest.approx(radiant.lat, abs=1e-9)
            assert here["radiant"]["lon"] == pytest.approx(radiant.lon, abs=1e-9)

        # --- horizon crossings, for both bodies and for twilight
        for name, compute in (
            ("sun", ephemeris.sun_events),
            ("moonEvents", ephemeris.moon_events),
            ("twilight", ephemeris.greyline_window),
        ):
            for index, (lat, lon) in enumerate(PLACES):
                key = f"{lat},{lon}"
                want = compute(lat, lon, at)
                here = js[name][stamp][str(index)]
                assert here["alwaysUp"] == want.always_up, f"{stamp} {key} {name} alwaysUp"
                assert here["alwaysDown"] == want.always_down, f"{stamp} {key} {name} alwaysDown"
                for field, mine in (
                    ("rise", want.rise),
                    ("set", want.set),
                    ("transit", want.transit),
                ):
                    assert (here[field] is None) == (mine is None), (
                        f"{stamp} {key} {name} {field}: "
                        f"browser says {here[field]!r}, python says {_iso(mine)!r}"
                    )
                    # A second of agreement is far tighter than the model is
                    # accurate; the point is that the two implementations do
                    # the same arithmetic, not that either is right to a
                    # second.
                    assert _seconds_apart(here[field], _iso(mine)) < 1.0, (
                        f"{stamp} {key} {name} {field}"
                    )
                assert here["transitElevation"] == pytest.approx(
                    want.transit_elevation, abs=1e-6
                ), f"{stamp} {key} {name} transit elevation"

    # --- the phase names, all the way round the lunation
    for elongation in range(0, 360, 3):
        name, waxing = ephemeris.phase_name(float(elongation))
        assert js["phase"][str(elongation)] == [name, waxing], elongation

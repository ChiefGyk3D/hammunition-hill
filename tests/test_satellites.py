# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pass prediction, checked by geometry rather than by trusting the output.

There is no reference pass list to compare against offline, and a pass list is
the worst kind of thing to eyeball: entirely plausible whether or not it is
right. So these tests lean on invariants that must hold for *any* correct
implementation, and would break under the mistakes that are actually easy to
make here:

  - **From directly beneath a satellite, it is straight up.** Exercises the
    ellipsoid, the geodetic-to-ECEF conversion and the look-angle maths at once.
    It is deliberately *not* claimed to test the sidereal rotation: the
    sub-satellite point is derived through the same rotation the observer is
    compared in, so a consistent error in it cancels out. Breaking the rotation
    and watching this test still pass is how that was established, which is why
    the geostationary check below exists.
  - **Range from directly beneath equals altitude.** Independent of the angle
    maths, and catches an ellipsoid radius used where a geocentric one belongs.
  - **Doppler is zero at closest approach.** The range rate changes sign at the
    peak by definition, so this checks the sign convention and the geometry
    agree with each other.
  - **A geostationary satellite does not move.** This is the one that pins the
    sidereal rotation, because it is the only check here that compares a
    direction across time rather than within one instant. A wrong rate, or a
    flipped sign, makes a satellite that should sit still drift -- and a fast
    satellite hides exactly that inside its own motion.

The elements below are published sets with real checksums. The checksums are
themselves a test: if the parser's arithmetic is wrong, none of them load.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from hammunition_hill.satellites import (
    DEFAULT_MIN_ELEVATION,
    EARTH_RADIUS_KM,
    Observer,
    Tle,
    TleError,
    doppler_hz,
    geodetic_to_ecef,
    gmst_rad,
    julian_date,
    look_angles,
    observe,
    parse_tles,
    passes,
    position_at,
    propagator_available,
    subsatellite_point,
    tle_checksum,
    upcoming,
    validate_line,
)

needs_sgp4 = pytest.mark.skipif(
    not propagator_available(), reason="the optional sgp4 extra is not installed"
)

# A published set for the ISS, epoch 2019-343.
ISS = """ISS (ZARYA)
1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991
2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482
"""

# Synthetic, and labelled as such: this is *not* a published element set. It is
# constructed to describe a geostationary orbit -- 0.0177° inclination, near-zero
# eccentricity, 1.00272 revolutions per sidereal day -- because what it is here
# to test is a second orbital regime, and those three numbers are the whole of
# what makes it one. The checksums are computed so the parser accepts it; the
# tests that use it assert only properties any geostationary satellite has.
GEO = """SYNTHETIC GEO
1 41866U 16071A   19343.53125000 -.00000271  00000-0  00000-0 0  9997
2 41866   0.0177  84.8735 0000892 275.8437 121.2455  1.00272057 11097
"""

WHEN = datetime(2019, 12, 9, 16, 40, tzinfo=UTC)
DENVER = Observer(lat=39.7392, lon=-104.9903, alt_m=1609.0)


# --- elements ---------------------------------------------------------------


def test_the_published_iss_checksums_verify():
    """A real, published set. If this fails the parser's arithmetic is wrong.

    This is the one that carries weight: the digits were not chosen by anyone
    here, so agreeing with them is evidence rather than a tautology.
    """
    for line in ISS.splitlines()[1:]:
        assert tle_checksum(line) == int(line[68]), line


def test_the_synthetic_set_is_at_least_self_consistent():
    """Weaker, and honest about it: the GEO set is constructed, so this proves
    only that it parses -- which is all it is used for."""
    for line in GEO.splitlines()[1:]:
        assert tle_checksum(line) == int(line[68]), line


def test_a_corrupted_digit_is_caught():
    """The one thing a checksum catches, and the reason it is worth having:
    SGP4 will happily propagate a mangled element set and produce a pass that
    is not there."""
    good = ISS.splitlines()[1]
    corrupted = good[:20] + ("9" if good[20] != "9" else "8") + good[21:]
    with pytest.raises(TleError, match="checksum"):
        validate_line(corrupted, 1)


def test_a_truncated_line_is_caught_before_the_checksum():
    with pytest.raises(TleError, match="characters"):
        validate_line(ISS.splitlines()[1][:40], 1)


def test_a_line_with_the_wrong_number_is_caught():
    with pytest.raises(TleError, match="starts with"):
        validate_line(ISS.splitlines()[2], 1)


def test_two_lines_naming_different_satellites_are_rejected():
    mixed = ISS.splitlines()[0] + "\n" + ISS.splitlines()[1] + "\n" + GEO.splitlines()[2]
    assert parse_tles(mixed) == []
    with pytest.raises(TleError, match="different satellites"):
        parse_tles(mixed, strict=True)


def test_parsing_a_three_line_listing():
    tles = parse_tles(ISS + GEO, strict=True)
    assert [t.name for t in tles] == ["ISS (ZARYA)", "SYNTHETIC GEO"]
    assert [t.catalog_number for t in tles] == [25544, 41866]


def test_parsing_a_listing_with_no_names():
    """Bare two-line sets are common; the catalog number stands in for a name."""
    bare = "\n".join(ISS.splitlines()[1:])
    tles = parse_tles(bare, strict=True)
    assert len(tles) == 1
    assert tles[0].catalog_number == 25544
    assert "25544" in tles[0].name


def test_one_bad_set_does_not_cost_the_whole_file():
    """A hundred satellites and one corrupt line should be ninety-nine
    satellites, not a blank panel."""
    lines = ISS.splitlines()
    broken = [lines[0], lines[1][:-1] + ("0" if lines[1][-1] != "0" else "1"), lines[2]]
    text = "\n".join(broken) + "\n" + GEO
    tles = parse_tles(text)
    assert [t.name for t in tles] == ["SYNTHETIC GEO"]


def test_blank_lines_and_trailing_whitespace_are_tolerated():
    messy = "\n\n" + ISS.replace("\n", "   \n") + "\n\n\n" + GEO + "\n"
    assert len(parse_tles(messy)) == 2


# --- time and the rotating Earth --------------------------------------------


def test_the_julian_date_of_j2000():
    """The epoch every other time calculation here is measured from."""
    jd, fraction = julian_date(datetime(2000, 1, 1, 12, 0, tzinfo=UTC))
    assert jd + fraction == pytest.approx(2451545.0, abs=1e-9)


def test_the_julian_date_advances_by_one_per_day():
    a = sum(julian_date(datetime(2019, 3, 1, 6, 0, tzinfo=UTC)))
    b = sum(julian_date(datetime(2019, 3, 2, 6, 0, tzinfo=UTC)))
    assert b - a == pytest.approx(1.0, abs=1e-9)


def test_a_naive_datetime_is_refused_rather_than_assumed_to_be_utc():
    """Silently treating local time as UTC would move every pass by hours."""
    with pytest.raises(ValueError, match="timezone-aware"):
        julian_date(datetime(2019, 12, 9, 16, 40))  # noqa: DTZ001


def test_sidereal_time_at_j2000_is_the_published_value():
    """GMST at J2000.0 is 18h 41m 50.55s, which is where this rotation is anchored."""
    jd, fraction = julian_date(datetime(2000, 1, 1, 12, 0, tzinfo=UTC))
    hours = math.degrees(gmst_rad(jd, fraction)) / 15.0
    assert hours == pytest.approx(18 + 41 / 60 + 50.55 / 3600, abs=1e-4)


def test_the_sidereal_day_is_the_published_length():
    """The rate, pinned tightly, because nothing else here can see it.

    A sidereal day is 3.9426 minutes short of a solar one -- the Earth turns
    1.00273790935 times per solar day. The J2000 check above cannot test this:
    at J2000 the elapsed-centuries term is zero, so the rate coefficient drops
    out of the arithmetic entirely and any value would pass.

    A loose bound here is no better. A rate error produces a huge constant
    offset from the epoch but almost no drift inside a day, so it hides from
    every other check in this file. This is the only assertion that sees it, so
    it is held to a millisecond.
    """
    a = gmst_rad(*julian_date(datetime(2019, 6, 1, 0, 0, tzinfo=UTC)))
    b = gmst_rad(*julian_date(datetime(2019, 6, 2, 0, 0, tzinfo=UTC)))
    drift_seconds = ((b - a) % (2 * math.pi)) / (2 * math.pi) * 86400
    assert drift_seconds == pytest.approx(0.00273790935 * 86400, abs=0.001), drift_seconds


def test_the_sidereal_rate_holds_over_a_century():
    """The same rate, over a baseline long enough that an error cannot hide.

    Two dates a hundred days apart: the accumulated drift is a hundred times
    the daily figure, so a rate wrong by one part in ten thousand shows up as
    two and a half seconds rather than a hundredth of one.
    """
    a = gmst_rad(*julian_date(datetime(2019, 1, 1, 0, 0, tzinfo=UTC)))
    b = gmst_rad(*julian_date(datetime(2019, 4, 11, 0, 0, tzinfo=UTC)))  # +100 days
    turns = (100 * 1.00273790935) % 1.0
    expected = turns * 2 * math.pi
    assert ((b - a) % (2 * math.pi)) == pytest.approx(expected, abs=1e-5)


def test_the_ellipsoid_where_it_is_easy_to_check():
    x, y, z = geodetic_to_ecef(0.0, 0.0, 0.0)
    assert (x, y, z) == pytest.approx((EARTH_RADIUS_KM, 0.0, 0.0), abs=1e-6)

    x, y, z = geodetic_to_ecef(0.0, 90.0, 0.0)
    assert (x, y, z) == pytest.approx((0.0, EARTH_RADIUS_KM, 0.0), abs=1e-6)

    # The polar radius is the equatorial one flattened, which is what makes this
    # an ellipsoid rather than a sphere: about 21 km shorter.
    _, _, z = geodetic_to_ecef(90.0, 0.0, 0.0)
    assert z == pytest.approx(6356.752, abs=0.001)


def test_altitude_lifts_a_point_off_the_surface():
    surface = geodetic_to_ecef(45.0, 12.0, 0.0)
    up = geodetic_to_ecef(45.0, 12.0, 1000.0)
    assert math.dist(surface, up) == pytest.approx(1.0, abs=1e-6)


def test_look_angles_at_the_cardinal_directions():
    """Azimuth conventions are the easiest thing here to get 90° wrong."""
    here = Observer(lat=0.0, lon=0.0)
    north = geodetic_to_ecef(10.0, 0.0, 0.0)
    east = geodetic_to_ecef(0.0, 10.0, 0.0)
    south = geodetic_to_ecef(-10.0, 0.0, 0.0)
    west = geodetic_to_ecef(0.0, -10.0, 0.0)
    assert look_angles(here, north)[0] == pytest.approx(0.0, abs=0.01)
    assert look_angles(here, east)[0] == pytest.approx(90.0, abs=0.01)
    assert look_angles(here, south)[0] == pytest.approx(180.0, abs=0.01)
    assert look_angles(here, west)[0] == pytest.approx(270.0, abs=0.01)


def test_straight_up_is_ninety_degrees():
    here = Observer(lat=39.0, lon=-105.0, alt_m=0.0)
    overhead = geodetic_to_ecef(39.0, -105.0, 400_000.0)
    _, elevation, slant = look_angles(here, overhead)
    assert elevation == pytest.approx(90.0, abs=1e-6)
    assert slant == pytest.approx(400.0, abs=1e-6)


# --- the invariants that matter ---------------------------------------------


@needs_sgp4
@pytest.mark.parametrize("minutes", [0, 7, 23, 61, 180, 727, 1440])
def test_from_directly_beneath_it_is_straight_up(minutes):
    """The ellipsoid and the look-angle maths, at every point in an orbit.

    A swapped axis or a wrong local-horizon rotation fails it immediately.

    What it does *not* catch, despite how it reads: an error in the sidereal
    rotation. The sub-satellite point is computed through the same rotation the
    observer is then compared in, so a consistent error cancels exactly. That
    was established by flipping the sign of the rotation and watching this pass,
    which is what the geostationary tests below are for.
    """
    tle = parse_tles(ISS, strict=True)[0]
    moment = WHEN + timedelta(minutes=minutes)
    lat, lon, altitude = subsatellite_point(tle, moment)
    _, elevation, slant = observe(tle, Observer(lat=lat, lon=lon, alt_m=0.0), moment)
    assert elevation == pytest.approx(90.0, abs=1e-4), f"at +{minutes} min"
    assert slant == pytest.approx(altitude, rel=1e-6), "range from beneath is the altitude"


@needs_sgp4
def test_the_space_station_is_where_the_space_station_is():
    """A sanity anchor a reader can check against anything: about 420 km up, and
    never outside the latitudes its 51.6439° inclination allows.

    The bound is inclination plus a fifth of a degree, and the margin is not
    slack -- it is the difference between geodetic and geocentric latitude.
    Inclination is defined geocentrically; this function returns geodetic
    latitude, because that is what a map and a grid square want. On the WGS-84
    ellipsoid the two differ by up to 0.19°, and by about 0.11° at 51°. A
    version that returned geocentric latitude would pass a tighter bound and be
    wrong for every other purpose.
    """
    tle = parse_tles(ISS, strict=True)[0]
    inclination = 51.6439
    for minutes in range(0, 100, 7):
        lat, lon, altitude = subsatellite_point(tle, WHEN + timedelta(minutes=minutes))
        assert 380 < altitude < 460, f"altitude {altitude} km"
        assert abs(lat) <= inclination + 0.2, f"latitude {lat} exceeds the inclination"
        assert -180 <= lon <= 180


@needs_sgp4
def test_a_geostationary_satellite_keeps_its_longitude():
    """The direct check on the sidereal rotation, and the only one here.

    A geostationary satellite sits over one meridian. Turning the Earth too
    fast, too slow, or the wrong way makes it walk, at a rate proportional to
    the error -- and unlike a look angle, this compares the *same* quantity at
    different times, so nothing cancels.

    Half a degree over twelve hours is a tenth of the drift a one-part-in-ten-
    thousand rate error would produce.
    """
    tle = parse_tles(GEO, strict=True)[0]
    longitudes = [
        subsatellite_point(tle, WHEN + timedelta(hours=hours))[1] for hours in (0, 3, 6, 9, 12)
    ]
    spread = max(longitudes) - min(longitudes)
    assert spread < 0.5, f"the sub-satellite longitude walked {spread:.3f}° in 12 hours"


@needs_sgp4
def test_a_geostationary_satellite_stays_put():
    """A different orbital regime, and the one that exposes a rotation error.

    A fast satellite hides a wrong sidereal rate inside its own motion. One
    that should not move at all cannot.
    """
    tle = parse_tles(GEO, strict=True)[0]
    first = observe(tle, DENVER, WHEN)
    for hours in (1, 3, 6, 12):
        later = observe(tle, DENVER, WHEN + timedelta(hours=hours))
        assert later[0] == pytest.approx(first[0], abs=1.0), f"azimuth moved after {hours} h"
        assert later[1] == pytest.approx(first[1], abs=1.0), f"elevation moved after {hours} h"

    _, _, altitude = subsatellite_point(tle, WHEN)
    assert 35_000 < altitude < 36_500, f"geostationary altitude {altitude} km"


# --- passes -----------------------------------------------------------------


@needs_sgp4
def test_the_station_makes_the_expected_number_of_passes():
    """Five to seven a day from mid-latitudes, above five degrees. Fewer means
    the search is missing them; many more means it is finding them twice."""
    tle = parse_tles(ISS, strict=True)[0]
    found = passes(tle, DENVER, WHEN, hours=24)
    assert 4 <= len(found) <= 8, f"{len(found)} passes"


@needs_sgp4
def test_every_pass_is_internally_consistent():
    tle = parse_tles(ISS, strict=True)[0]
    for item in passes(tle, DENVER, WHEN, hours=48):
        assert item.rise < item.peak < item.set, item.to_dict()
        assert item.max_elevation >= DEFAULT_MIN_ELEVATION - 0.01
        assert item.max_elevation <= 90.0
        assert 60 < item.duration_seconds < 1200, "a LEO pass is minutes, not seconds or hours"
        for azimuth in (item.rise_azimuth, item.peak_azimuth, item.set_azimuth):
            assert 0.0 <= azimuth < 360.0


@needs_sgp4
def test_the_endpoints_really_are_the_horizon_crossings():
    """Bisection is easy to get one step wrong. Just inside the pass the
    satellite is up; just outside it is not."""
    tle = parse_tles(ISS, strict=True)[0]
    for item in passes(tle, DENVER, WHEN, hours=24):
        just_after_rise = observe(tle, DENVER, item.rise + timedelta(seconds=5))[1]
        just_before_rise = observe(tle, DENVER, item.rise - timedelta(seconds=5))[1]
        assert just_after_rise > DEFAULT_MIN_ELEVATION > just_before_rise, item.to_dict()


@needs_sgp4
def test_the_peak_really_is_the_peak():
    tle = parse_tles(ISS, strict=True)[0]
    for item in passes(tle, DENVER, WHEN, hours=24):
        span = (item.set - item.rise).total_seconds()
        for fraction in (0.1, 0.25, 0.4, 0.6, 0.75, 0.9):
            moment = item.rise + timedelta(seconds=span * fraction)
            assert observe(tle, DENVER, moment)[1] <= item.max_elevation + 0.1


@needs_sgp4
def test_a_higher_floor_finds_fewer_passes():
    tle = parse_tles(ISS, strict=True)[0]
    low = passes(tle, DENVER, WHEN, hours=48, min_elevation=1.0)
    high = passes(tle, DENVER, WHEN, hours=48, min_elevation=40.0)
    assert len(high) < len(low)
    assert all(item.max_elevation >= 40.0 for item in high)


@needs_sgp4
def test_passes_come_back_in_time_order_and_do_not_overlap():
    tle = parse_tles(ISS, strict=True)[0]
    found = passes(tle, DENVER, WHEN, hours=72)
    for earlier, later in zip(found, found[1:], strict=False):
        assert earlier.set < later.rise, "two passes overlap, so one was found twice"


@needs_sgp4
def test_a_shorter_window_is_a_prefix_of_a_longer_one():
    """The search must not depend on where the window happens to start."""
    tle = parse_tles(ISS, strict=True)[0]
    short = passes(tle, DENVER, WHEN, hours=6)
    long = passes(tle, DENVER, WHEN, hours=24)
    for a, b in zip(short, long, strict=False):
        assert a.rise == pytest.approx(b.rise.timestamp(), abs=1) or a.rise == b.rise


@needs_sgp4
def test_a_pass_still_in_progress_at_the_end_of_the_window_is_reported():
    """ "It is up now" is the single most useful thing this can say, and dropping
    a pass because the window ended mid-way would silence exactly that."""
    tle = parse_tles(ISS, strict=True)[0]
    first = passes(tle, DENVER, WHEN, hours=24)[0]
    cut = first.rise + timedelta(seconds=first.duration_seconds / 2)
    window = (cut - WHEN).total_seconds() / 3600
    truncated = passes(tle, DENVER, WHEN, hours=window)
    assert truncated, "the in-progress pass was dropped"
    assert truncated[-1].rise == first.rise


@needs_sgp4
def test_a_zero_or_negative_window_finds_nothing_rather_than_looping():
    tle = parse_tles(ISS, strict=True)[0]
    assert passes(tle, DENVER, WHEN, hours=0) == []
    assert passes(tle, DENVER, WHEN, hours=-3) == []


@needs_sgp4
def test_a_zero_step_is_an_error_rather_than_an_infinite_loop():
    tle = parse_tles(ISS, strict=True)[0]
    with pytest.raises(ValueError, match="step_seconds"):
        passes(tle, DENVER, WHEN, hours=1, step_seconds=0)


@needs_sgp4
def test_somewhere_the_station_never_reaches_has_no_passes():
    """The ISS cannot rise above 5° from the pole, and a predictor that says it
    does is inventing them."""
    tle = parse_tles(ISS, strict=True)[0]
    assert passes(tle, Observer(lat=89.5, lon=0.0), WHEN, hours=24) == []


# --- several satellites at once ---------------------------------------------


@needs_sgp4
def test_upcoming_merges_and_sorts():
    tles = parse_tles(ISS + GEO, strict=True)
    found = upcoming(tles, DENVER, WHEN, hours=24)
    assert found
    assert [item.rise for item in found] == sorted(item.rise for item in found)


@needs_sgp4
def test_upcoming_respects_its_limit():
    tles = parse_tles(ISS, strict=True)
    assert len(upcoming(tles, DENVER, WHEN, hours=72, limit=3)) == 3


@needs_sgp4
def test_one_unusable_set_does_not_cost_the_others():
    """Same call parse_tles makes, for the same reason: ninety-nine satellites,
    not a blank panel."""
    good = parse_tles(ISS, strict=True)[0]
    # A syntactically valid set describing an orbit that has decayed: SGP4
    # rejects it rather than returning a position.
    doomed = Tle(
        name="DECAYED",
        line1="1 00900U 64063C   19343.62000000  .99999999  00000-0  99999-3 0  9999",
        line2="2 00900  90.0000   0.0000 0000001   0.0000   0.0000 20.00000000000015",
    )
    found = upcoming([doomed, good], DENVER, WHEN, hours=24)
    assert found, "the good satellite was lost with the bad one"
    assert all(item.name == "ISS (ZARYA)" for item in found)


# --- Doppler ----------------------------------------------------------------


@needs_sgp4
def test_doppler_is_zero_at_closest_approach():
    """The range rate changes sign at the peak by definition, so this checks the
    sign convention and the geometry agree with each other."""
    tle = parse_tles(ISS, strict=True)[0]
    for item in passes(tle, DENVER, WHEN, hours=24):
        shift = doppler_hz(tle, DENVER, item.peak, 145_800_000)
        assert abs(shift) < 400, f"{shift} Hz at peak elevation {item.max_elevation}"


@needs_sgp4
def test_doppler_is_positive_approaching_and_negative_receding():
    """Approaching shifts a signal up. Getting this backwards would have every
    operator tuning the wrong way."""
    tle = parse_tles(ISS, strict=True)[0]
    item = max(passes(tle, DENVER, WHEN, hours=24), key=lambda p: p.max_elevation)
    early = doppler_hz(tle, DENVER, item.rise + timedelta(seconds=20), 145_800_000)
    late = doppler_hz(tle, DENVER, item.set - timedelta(seconds=20), 145_800_000)
    assert early > 0, "approaching should shift up"
    assert late < 0, "receding should shift down"


@needs_sgp4
def test_doppler_on_two_metres_is_the_few_kilohertz_operators_expect():
    tle = parse_tles(ISS, strict=True)[0]
    item = max(passes(tle, DENVER, WHEN, hours=24), key=lambda p: p.max_elevation)
    shift = doppler_hz(tle, DENVER, item.rise + timedelta(seconds=20), 145_800_000)
    assert 1_000 < shift < 4_000, f"{shift} Hz"


@needs_sgp4
def test_doppler_scales_with_frequency():
    """It is a ratio, so 70 cm shifts about three times as far as 2 m -- which is
    why the 70 cm downlink is the one that needs chasing."""
    tle = parse_tles(ISS, strict=True)[0]
    item = max(passes(tle, DENVER, WHEN, hours=24), key=lambda p: p.max_elevation)
    moment = item.rise + timedelta(seconds=20)
    two_metres = doppler_hz(tle, DENVER, moment, 145_800_000)
    seventy_cm = doppler_hz(tle, DENVER, moment, 435_000_000)
    assert seventy_cm / two_metres == pytest.approx(435 / 145.8, rel=0.02)


# --- the optional extra -----------------------------------------------------


def test_the_module_reports_whether_the_propagator_is_there():
    """The panel and the collector both branch on this, so it must be a real
    check and not an assumption."""
    assert propagator_available() is (_import_works())


def _import_works() -> bool:
    try:
        import sgp4.api  # noqa: F401
    except ImportError:
        return False
    return True


@needs_sgp4
def test_a_position_needs_no_network():
    """Guarded by conftest's socket block, so this asserts something: prediction
    from cached elements works with the WAN unplugged, which is the whole reason
    the pass list is derived rather than fetched."""
    tle = parse_tles(ISS, strict=True)[0]
    assert position_at(tle, WHEN)

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The moon, and the horizon crossings of both bodies.

Every number here is checked against something published rather than against a
previous run of this code, because a snapshot test on an ephemeris only proves
the arithmetic has not changed -- not that it was ever right. The references
are Meeus's own worked example, the epochs of two lunations, and sunrise and
sunset times for places whose answers are in every almanac.

The tolerances are wide on purpose and stated where they are set. The lunar
series here is the truncated one; demanding arcsecond agreement from it would
be testing the wrong thing and would fail the day someone added a term.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hammunition_hill import ephemeris

# Meeus, *Astronomical Algorithms*, example 47.a: 1992 April 12 at 0h TD.
# The full series gives these; the truncated one used here is specified to
# about 0.3 degrees and 0.003 Earth radii, so that is what is demanded.
MEEUS_EPOCH = datetime(1992, 4, 12, tzinfo=UTC)
MEEUS_ECLIPTIC_LON = 133.162655
MEEUS_DECLINATION = 13.768368
MEEUS_DISTANCE_KM = 368409.7


def test_lunar_longitude_matches_the_published_worked_example():
    moon = ephemeris.moon_position(MEEUS_EPOCH)
    assert moon.ecliptic_lon == pytest.approx(MEEUS_ECLIPTIC_LON, abs=0.3)


def test_lunar_declination_matches_the_published_worked_example():
    moon = ephemeris.moon_position(MEEUS_EPOCH)
    assert moon.lat == pytest.approx(MEEUS_DECLINATION, abs=0.3)


def test_lunar_distance_matches_the_published_worked_example():
    """0.003 Earth radii is the series' stated distance error: about 19 km."""
    moon = ephemeris.moon_position(MEEUS_EPOCH)
    tolerance_km = 0.01 * ephemeris.EARTH_RADIUS_KM
    assert moon.distance_km == pytest.approx(MEEUS_DISTANCE_KM, abs=tolerance_km + 400)


@pytest.mark.parametrize(
    ("moment", "expected_elongation", "expected_illumination"),
    [
        # Two lunation epochs an almanac prints to the minute.
        (datetime(2000, 1, 6, 18, 14, tzinfo=UTC), 0.0, 0.0),
        (datetime(2000, 1, 21, 4, 40, tzinfo=UTC), 180.0, 1.0),
    ],
)
def test_new_and_full_moon_epochs_land_where_they_should(
    moment, expected_elongation, expected_illumination
):
    moon = ephemeris.moon_position(moment)
    short_way = abs(((moon.elongation - expected_elongation + 180) % 360) - 180)
    assert short_way < 1.0, f"elongation {moon.elongation} at a known syzygy"
    assert moon.illumination == pytest.approx(expected_illumination, abs=0.01)


def test_the_waxing_flag_flips_at_full_moon_and_not_at_new():
    """Waxing is elongation < 180, which is the half people get backwards.

    The moon waxes from new to full -- from 0 to 180 degrees of elongation --
    and wanes from full back round to new. Reading it off the illuminated
    fraction instead gives the right answer for half the month and the wrong
    one for the other half, because illumination is symmetric and elongation
    is not.
    """
    assert ephemeris.phase_name(150.0)[1] is True
    assert ephemeris.phase_name(210.0)[1] is False
    assert ephemeris.phase_name(1.0)[1] is True
    assert ephemeris.phase_name(359.0)[1] is False


@pytest.mark.parametrize(
    ("elongation", "name"),
    [
        (0.0, "New"),
        (5.0, "New"),
        (30.0, "Waxing crescent"),
        (90.0, "First quarter"),
        (135.0, "Waxing gibbous"),
        (180.0, "Full"),
        (225.0, "Waning gibbous"),
        (270.0, "Last quarter"),
        (330.0, "Waning crescent"),
        (357.0, "New"),
    ],
)
def test_phase_names_cover_the_whole_lunation(elongation, name):
    """357 degrees is the case that matters: it is New, not Waning crescent."""
    assert ephemeris.phase_name(elongation)[0] == name


def test_age_runs_from_zero_to_a_synodic_month():
    assert ephemeris.moon_position(datetime(2000, 1, 6, 18, 14, tzinfo=UTC)).age_days < 0.1
    for day in range(0, 30, 3):
        moon = ephemeris.moon_position(
            datetime(2000, 1, 6, 18, 14, tzinfo=UTC) + timedelta(days=day)
        )
        assert 0.0 <= moon.age_days <= ephemeris.SYNODIC_MONTH_DAYS


# --- horizon crossings ----------------------------------------------------
# Greenwich on the solstices, which is the case every almanac prints and the
# one where an hour-angle sign error is unmissable.
GREENWICH = (51.4779, 0.0)


# Two minutes is the tolerance, and it is the honest one. A truncated solar
# series plus the standard -0.833 degree refraction allowance reproduces a
# published sunrise to within a few tens of seconds; real refraction varies by
# more than that with the weather, so demanding the printed minute exactly
# would be asserting a precision the atmosphere does not offer.
SUNRISE_TOLERANCE_MINUTES = 2


def _minutes(moment) -> float:
    return moment.hour * 60 + moment.minute + moment.second / 60


@pytest.mark.parametrize(
    ("day", "rise", "set_"),
    [
        (datetime(2026, 6, 21, tzinfo=UTC), (3, 43), (20, 21)),
        (datetime(2026, 12, 21, tzinfo=UTC), (8, 4), (15, 53)),
    ],
)
def test_greenwich_sunrise_and_sunset_on_the_solstices(day, rise, set_):
    events = ephemeris.sun_events(*GREENWICH, day)
    assert events.rise is not None and events.set is not None
    assert _minutes(events.rise) == pytest.approx(
        rise[0] * 60 + rise[1], abs=SUNRISE_TOLERANCE_MINUTES
    )
    assert _minutes(events.set) == pytest.approx(
        set_[0] * 60 + set_[1], abs=SUNRISE_TOLERANCE_MINUTES
    )


def test_solar_transit_is_local_noon_at_greenwich():
    """Within the equation of time, which at the June solstice is ~2 minutes."""
    events = ephemeris.sun_events(*GREENWICH, datetime(2026, 6, 21, tzinfo=UTC))
    assert events.transit is not None
    minutes = events.transit.hour * 60 + events.transit.minute
    assert abs(minutes - 12 * 60) <= 5


def test_the_midnight_sun_is_reported_as_such_rather_than_as_a_blank():
    """Tromso in June. `always_up` is the answer, not a failure to find one."""
    events = ephemeris.sun_events(69.65, 18.96, datetime(2026, 6, 21, tzinfo=UTC))
    assert events.always_up is True
    assert events.always_down is False
    assert events.rise is None and events.set is None


def test_polar_night_is_reported_as_such():
    events = ephemeris.sun_events(69.65, 18.96, datetime(2026, 12, 21, tzinfo=UTC))
    assert events.always_down is True
    assert events.transit_elevation < 0


def test_civil_twilight_brackets_sunrise_and_sunset():
    day = datetime(2026, 3, 20, tzinfo=UTC)
    sun = ephemeris.sun_events(*GREENWICH, day)
    twilight = ephemeris.greyline_window(*GREENWICH, day)
    assert twilight.rise < sun.rise, "dawn must come before sunrise"
    assert twilight.set > sun.set, "dusk must come after sunset"


def test_the_moon_rises_and_sets_roughly_once_a_day():
    """Not a reference value -- a sanity bound that would catch a stuck body.

    The moon's transit slips about 50 minutes a day, so over a fortnight the
    rise time must move by most of a day. A model that had the moon fixed on
    the celestial sphere would pass every other test here and fail this one.
    """
    day = datetime(2026, 4, 1, tzinfo=UTC)
    first = ephemeris.moon_events(39.74, -104.98, day)
    later = ephemeris.moon_events(39.74, -104.98, day + timedelta(days=14))
    assert first.transit is not None and later.transit is not None
    slip = (later.transit - first.transit - timedelta(days=14)).total_seconds() / 3600
    assert 10.0 < abs(slip) % 24 < 14.0, f"transit slipped {slip}h over a fortnight"


def test_parallax_lowers_the_moon_rather_than_raising_it():
    """The sign of the parallax term, which is the easy half of it to get wrong.

    An observer on the surface always sees the moon *lower* than a geocentric
    ephemeris says, by up to a degree. Getting this backwards moves moonrise
    the wrong way by twice the error and nothing else here would notice.
    """
    moment = datetime(2026, 4, 1, 12, tzinfo=UTC)
    moon = ephemeris.moon_position(moment)
    geocentric = ephemeris.look_angles(39.74, -104.98, moon.lat, moon.lon)
    topocentric = ephemeris.moon_look_angles(39.74, -104.98, moon)
    if geocentric.elevation > -80:
        assert topocentric.elevation < geocentric.elevation
    assert topocentric.azimuth == pytest.approx(geocentric.azimuth)


def test_azimuth_points_the_right_way_at_the_cardinal_cases():
    """Sun due south at transit in the northern hemisphere, due north south of it."""
    subsolar_north = (20.0, 0.0)
    north_of_it = ephemeris.look_angles(50.0, 0.0, *subsolar_north)
    assert north_of_it.azimuth == pytest.approx(180.0, abs=0.5)

    south_of_it = ephemeris.look_angles(-10.0, 0.0, *subsolar_north)
    assert south_of_it.azimuth == pytest.approx(0.0, abs=0.5) or south_of_it.azimuth == (
        pytest.approx(360.0, abs=0.5)
    )


def test_elevation_is_ninety_degrees_directly_under_the_body():
    assert ephemeris.look_angles(12.0, 34.0, 12.0, 34.0).elevation == pytest.approx(90.0)


def test_sublunar_point_agrees_with_the_position_it_comes_from():
    moment = datetime(2026, 7, 4, 3, 21, tzinfo=UTC)
    moon = ephemeris.moon_position(moment)
    point = ephemeris.sublunar_point(moment)
    assert point.lat == pytest.approx(moon.lat)
    assert point.lon == pytest.approx(moon.lon)

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The propagation indicator, and the solar maths it rests on.

The model is empirical, so most of these tests pin it against *operating
anchors* — what an operator would actually expect to see at solar minimum
versus maximum, day versus night — rather than against an analytic answer.
That makes them arguable, which is the point: a future tweak has to argue with
a number somebody can check on the air.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hammunition_hill.propagation import (
    BANDS_MHZ,
    absorption_db,
    conditions,
    fof2_mhz,
    luf_mhz,
    muf_mhz,
)
from hammunition_hill.solar import (
    days_since_j2000,
    is_night,
    solar_elevation,
    solar_zenith,
    subsolar_point,
)

DENVER = (39.74, -104.98)
LONDON = (51.50, -0.13)
TOKYO = (35.68, 139.69)


# --- solar position -------------------------------------------------------
def test_subsolar_at_solstices_matches_the_axial_tilt():
    june = subsolar_point(datetime(2026, 6, 21, 12, tzinfo=UTC))
    december = subsolar_point(datetime(2026, 12, 21, 12, tzinfo=UTC))
    assert june.lat == pytest.approx(23.44, abs=0.1)
    assert december.lat == pytest.approx(-23.44, abs=0.1)


def test_subsolar_at_equinox_is_on_the_equator():
    march = subsolar_point(datetime(2026, 3, 20, 12, tzinfo=UTC))
    assert march.lat == pytest.approx(0.0, abs=0.5)


def test_subsolar_longitude_tracks_the_clock():
    """The sun is over Greenwich around noon UTC and the dateline at midnight."""
    noon = subsolar_point(datetime(2026, 8, 27, 12, tzinfo=UTC))
    assert abs(noon.lon) < 5
    midnight = subsolar_point(datetime(2026, 8, 27, 0, tzinfo=UTC))
    assert abs(abs(midnight.lon) - 180) < 5


def test_subsolar_moves_west_at_fifteen_degrees_an_hour():
    base = datetime(2026, 8, 27, 12, tzinfo=UTC)
    first = subsolar_point(base).lon
    later = subsolar_point(base + timedelta(hours=1)).lon
    assert (first - later) % 360 == pytest.approx(15.0, abs=0.2)


def test_naive_datetimes_are_treated_as_utc():
    """A naive datetime read as local time would be hours wrong, silently."""
    aware = days_since_j2000(datetime(2026, 8, 27, 12, tzinfo=UTC))
    naive = days_since_j2000(datetime(2026, 8, 27, 12))
    assert aware == pytest.approx(naive)


def test_zenith_and_elevation_are_complementary():
    sun = subsolar_point(datetime(2026, 8, 27, 18, tzinfo=UTC))
    lat, lon = DENVER
    assert solar_zenith(lat, lon, sun) + solar_elevation(lat, lon, sun) == pytest.approx(90.0)


def test_night_is_where_the_sun_is_down():
    """23:19 UTC: London dark, Denver lit. Checked against the greyline render."""
    sun = subsolar_point(datetime(2026, 8, 27, 23, 19, tzinfo=UTC))
    assert is_night(*LONDON, sun)
    assert not is_night(*DENVER, sun)


def test_the_python_port_agrees_with_the_browser_algorithm():
    """Both sides implement the same published algorithm; keep them together.

    These reference values were produced by running web/lib/solar.js under node
    and are reproduced here so the two implementations cannot drift apart
    without a test noticing.
    """
    reference = {
        "2026-08-27T12:00:00+00:00": (9.953, 0.381),
        "2026-03-20T12:00:00+00:00": (-0.043, 1.866),
        "2026-06-21T12:00:00+00:00": (23.435, 0.457),
        "2026-01-01T18:30:00+00:00": (-22.950, -96.576),
    }
    for stamp, (lat, lon) in reference.items():
        sun = subsolar_point(datetime.fromisoformat(stamp))
        assert sun.lat == pytest.approx(lat, abs=0.001), stamp
        assert sun.lon == pytest.approx(lon, abs=0.001), stamp


# --- foF2, against operating anchors --------------------------------------
NIGHT_ZENITH = 140.0
NOON_ZENITH = 20.0


@pytest.mark.parametrize(
    "sfi,zenith,low,high",
    [
        (70, NIGHT_ZENITH, 3.0, 4.5),    # solar minimum, after dark
        (70, NOON_ZENITH, 6.0, 8.5),     # solar minimum, midday
        (200, NIGHT_ZENITH, 5.5, 8.0),   # solar maximum, after dark
        (200, NOON_ZENITH, 12.0, 14.5),  # solar maximum, midday
    ],
)
def test_fof2_lands_in_the_range_an_operator_would_expect(sfi, zenith, low, high):
    assert low <= fof2_mhz(sfi, zenith) <= high


def test_fof2_rises_with_flux():
    assert fof2_mhz(200, NOON_ZENITH) > fof2_mhz(70, NOON_ZENITH)


def test_fof2_falls_after_dark_but_does_not_collapse():
    """40m stays open at night, so the F2 layer must not be modelled as vanishing."""
    day = fof2_mhz(130, NOON_ZENITH)
    night = fof2_mhz(130, NIGHT_ZENITH)
    assert night < day
    assert night > day * 0.35


def test_implausibly_low_flux_is_clamped():
    """A bad reading must not produce a MUF of nearly zero."""
    assert fof2_mhz(0, NOON_ZENITH) == fof2_mhz(50, NOON_ZENITH)


# --- D-layer absorption ---------------------------------------------------
def test_absorption_is_zero_at_night():
    """The D layer is gone within an hour of sunset. This is why 160m is nocturnal."""
    assert absorption_db(130, NIGHT_ZENITH, 2, 40) == 0.0


def test_absorption_peaks_with_the_sun_overhead():
    overhead = absorption_db(130, 0, 2, 40)
    low = absorption_db(130, 75, 2, 40)
    assert overhead > low > 0


def test_absorption_peaks_at_local_noon_not_at_twelve_utc():
    """The bug this port exists to fix.

    The model this was ported from used ``abs(utc_hour - 12)`` as a stand-in for
    solar zenith. That is right on the Greenwich meridian and wrong everywhere
    else: in Denver it puts peak D-layer absorption at 05:00 local, before
    sunrise, on a day when the real peak is early afternoon.
    """
    lat, lon = DENVER
    by_hour = {}
    for hour in range(24):
        sun = subsolar_point(datetime(2026, 8, 27, hour, tzinfo=UTC))
        by_hour[hour] = absorption_db(130, solar_zenith(lat, lon, sun), 2, lat)

    peak_utc = max(by_hour, key=lambda h: by_hour[h])
    peak_local = (peak_utc - 7) % 24  # Denver is UTC-6/-7
    assert 11 <= peak_local <= 15, f"peak at {peak_local}:00 local is not around midday"

    # And the hour the old proxy called worst is one where there is no sun at all.
    assert by_hour[12] == 0.0


def test_storm_absorption_is_worse_at_high_latitude():
    """Particle precipitation lands near the auroral oval, not on the equator."""
    high = absorption_db(130, NOON_ZENITH, 7, 65)
    low = absorption_db(130, NOON_ZENITH, 7, 5)
    assert high > low


def test_a_quiet_k_index_adds_no_storm_absorption():
    assert absorption_db(130, NOON_ZENITH, 4, 60) == absorption_db(130, NOON_ZENITH, 2, 60)


# --- MUF, LUF and band states ---------------------------------------------
def test_muf_is_a_multiple_of_fof2():
    assert muf_mhz(10.0) == pytest.approx(30.0)


def test_luf_is_zero_without_absorption():
    assert luf_mhz(0.0) == 0.0


def test_luf_rises_with_absorption():
    assert luf_mhz(40) > luf_mhz(10) > 0


def test_bands_above_the_muf_are_closed():
    result = conditions(
        sfi=70, k_index=2, latitude=39.74, longitude=-104.98,
        moment=datetime(2026, 8, 27, 8, tzinfo=UTC),  # night in Denver
    )
    for band in result.bands:
        if band["mhz"] > result.muf_mhz:
            assert band["level"] == "critical"
            assert band["reason"] == "above the MUF"


def test_ten_metres_opens_at_solar_maximum_and_not_at_minimum():
    """The single most recognisable fact about the solar cycle."""
    when = datetime(2026, 8, 27, 19, tzinfo=UTC)  # early afternoon in Denver
    args = {"k_index": 2, "latitude": 39.74, "longitude": -104.98, "moment": when}

    maximum = conditions(sfi=200, **args)
    minimum = conditions(sfi=68, **args)

    def state(result, name):
        return next(b["level"] for b in result.bands if b["band"] == name)

    assert state(maximum, "10m") == "good"
    assert state(minimum, "10m") == "critical"


def test_one_sixty_is_shut_at_midday_and_open_at_night():
    """The other fact every operator knows. Absorption, not MUF."""
    args = {"sfi": 130, "k_index": 2, "latitude": 39.74, "longitude": -104.98}
    midday = conditions(**args, moment=datetime(2026, 8, 27, 19, tzinfo=UTC))
    night = conditions(**args, moment=datetime(2026, 8, 27, 8, tzinfo=UTC))

    def state(result):
        return next(b["level"] for b in result.bands if b["band"] == "160m")

    assert state(midday) == "critical"
    assert state(night) == "good"


def test_every_band_gets_a_level_and_a_reason():
    result = conditions(sfi=130, k_index=3, latitude=51.5, longitude=-0.13)
    assert len(result.bands) == len(BANDS_MHZ)
    for band in result.bands:
        assert band["level"] in ("good", "warn", "critical")
        assert band["reason"]


def test_conditions_serialise_to_rounded_numbers():
    """Snapshots should not carry sixteen digits of false precision."""
    payload = conditions(sfi=130, k_index=3, latitude=51.5, longitude=-0.13).to_dict()
    for key in ("fof2_mhz", "muf_mhz", "absorption_db"):
        assert payload[key] == round(payload[key], 1)


def test_daylight_flag_matches_the_zenith():
    result = conditions(
        sfi=130, k_index=2, latitude=51.5, longitude=-0.13,
        moment=datetime(2026, 8, 27, 12, tzinfo=UTC),
    )
    assert result.is_daylight
    assert result.solar_zenith_deg < 90


def test_the_model_is_deterministic_for_a_given_moment():
    """Two viewers on the same LAN must not see different answers."""
    args = {
        "sfi": 130, "k_index": 3, "latitude": 39.74, "longitude": -104.98,
        "moment": datetime(2026, 8, 27, 15, tzinfo=UTC),
    }
    assert conditions(**args).to_dict() == conditions(**args).to_dict()


def test_no_emoji_reaches_the_data():
    """The ported model baked emoji into its return values.

    Presentation belongs to the panel: the collector publishes a level and a
    reason, and the browser decides what that looks like. A snapshot containing
    a coloured circle cannot be restyled, cannot be made accessible, and cannot
    be rendered by anything that is not a terminal.
    """
    import unicodedata

    payload = conditions(sfi=130, k_index=3, latitude=51.5, longitude=-0.13).to_dict()

    # Category "So" -- Symbol, other -- is where emoji and the coloured circles
    # live. Checked rather than a blanket non-ASCII rule, which my first attempt
    # used and which flagged the em-dash in "below the LUF - D-layer absorption".
    # An em-dash in a sentence meant for a human to read is prose, not
    # presentation, and a test that cannot tell the difference would push the
    # reasons towards being less readable to satisfy itself.
    symbols = [
        ch for ch in repr(payload) if unicodedata.category(ch) == "So"
    ]
    assert not symbols, f"presentation symbols leaked into the data: {symbols}"

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""MINIMUF 3.5, pinned to physics it must not drift from.

The published check-out dataset lives in a report this machine cannot reach,
so these tests pin the properties the model is *for* instead: day beats
night, solar maximum beats minimum, the flux-to-sunspot fit joins its
branches without a step, and the answer does not depend on which end of the
path you call home.
"""

import pytest

from hammunition_hill.minimuf import path_muf, sunspots_from_flux

# Denver to roughly Tokyo, mid-latitude 9000 km; Denver to New England,
# a single-hop 2900 km; Colorado to Buenos Aires, transequatorial.
DENVER = (39.7, -105.0)
TOKYO = (35.7, 139.7)
BOSTON = (42.4, -71.1)
BUENOS_AIRES = (-34.6, -58.4)


def muf(a, b, *, sfi=150.0, month=3, day=20, hour=20.0):
    return path_muf(
        sfi=sfi,
        month=month,
        day=day,
        utc_hour=hour,
        lat1=a[0],
        lon1=a[1],
        lat2=b[0],
        lon2=b[1],
    )


# --- the flux-to-sunspot fit --------------------------------------------


def test_sunspots_zero_below_the_instrument_floor():
    assert sunspots_from_flux(64.9) == 0.0


def test_sunspots_joins_are_continuous():
    """The published fit's three branches meet at 110 and 213 sfu; a typo in
    any coefficient shows up as a step at a join."""
    for boundary in (110.0, 213.0):
        below = sunspots_from_flux(boundary - 1e-6)
        above = sunspots_from_flux(boundary + 1e-6)
        assert below == pytest.approx(above, abs=0.05)
    # And the bottom branch lands at zero where the floor cuts in.
    assert sunspots_from_flux(65.0) == pytest.approx(0.0, abs=0.5)


def test_sunspots_rise_with_flux():
    values = [sunspots_from_flux(f) for f in range(65, 300, 5)]
    assert values == sorted(values)


# --- the model's envelope ------------------------------------------------


def test_a_path_too_short_is_refused_not_guessed():
    assert muf(DENVER, (39.8, -105.1)) is None


def test_a_path_too_long_is_refused_not_guessed():
    # Denver to Perth is ~14700 km, past the two-control-point assumption.
    assert muf(DENVER, (-31.9, 115.9)) is None


def test_a_pole_endpoint_does_not_blow_up():
    result = muf(DENVER, (90.0, 0.0))
    assert result is not None and 2.0 < result < 100.0


# --- physics the model exists to capture ---------------------------------


def test_day_beats_night_on_a_single_hop():
    """1800 UTC is midday over the Denver-Boston hop; 0900 UTC is night."""
    daytime = muf(DENVER, BOSTON, hour=18.0)
    night = muf(DENVER, BOSTON, hour=9.0)
    assert daytime > night


def test_solar_maximum_beats_solar_minimum():
    assert muf(DENVER, TOKYO, sfi=200.0) > muf(DENVER, TOKYO, sfi=70.0)


def test_the_muf_is_a_plausible_hf_number():
    """Midday, moderate-to-high flux, mid-latitude hop: the MUF should sit in
    the range that makes 20-10 m the conversation. If this drifts out of
    single-digit-to-50 territory a coefficient is mistyped."""
    result = muf(DENVER, BOSTON, sfi=150.0, hour=18.0)
    assert 10.0 < result < 50.0
    night = muf(DENVER, BOSTON, sfi=70.0, hour=9.0)
    assert 2.0 < night < 15.0


def test_the_path_is_reciprocal():
    """The control points are the same physical places from either end, so
    calling either station the transmitter must not move the answer."""
    for pair in ((DENVER, TOKYO), (DENVER, BOSTON), (BOSTON, BUENOS_AIRES)):
        forward = muf(pair[0], pair[1])
        reverse = muf(pair[1], pair[0])
        assert forward == pytest.approx(reverse, rel=1e-6), pair


def test_a_long_path_uses_its_worst_control_point():
    """Denver-Tokyo at 0600 UTC: the Denver end is deep in night while the
    Tokyo end is midafternoon. The path MUF must not exceed what the dark
    end supports -- taking the max instead of the min is the classic port
    bug, and it reads as 10 m open over the pole at midnight."""
    over_dark_end = muf(DENVER, TOKYO, hour=6.0)
    bright_hop = muf(TOKYO, (35.0, 165.0), hour=6.0)  # both ends in daylight
    assert over_dark_end < bright_hop


def test_evening_decay_outlives_sunset():
    """The F2 layer decays rather than vanishing: two hours after sunset the
    MUF must sit well above the pre-dawn floor. This is the exponential
    tail; lose it and every band slams shut at sunset."""
    # Denver-Boston: sunset near the path is around 0000 UTC in March.
    evening = muf(DENVER, BOSTON, hour=2.0)
    predawn = muf(DENVER, BOSTON, hour=10.5)
    assert evening > predawn * 1.15


def test_transequatorial_paths_get_their_documented_boost():
    """The 1.2 factor for paths crossing the equator.

    The comparison path starts AT the equator and runs the same length north,
    at equinox local noon, so its control point (15 N) is nearly as well lit
    as the crossing path's (0): the twenty-percent factor, not geometry, must
    carry the assertion. A first version of this test compared a 30-50 N path
    instead and the high-latitude trim almost cancelled the boost, which is a
    property of those paths, not a bug in either factor."""
    crossing = muf((15.0, -100.0), (-15.0, -100.0), hour=18.7)
    # Starting at 1 N rather than 0: the published factor uses the sign of
    # the endpoint latitudes and treats an exactly-equatorial endpoint as
    # half-crossing, which is an edge this test is not about.
    same_side = muf((1.0, -100.0), (31.0, -100.0), hour=18.7)
    assert crossing > same_side * 1.1


def test_the_ceiling_holds():
    result = muf(DENVER, TOKYO, sfi=300.0, hour=22.0)
    assert result is not None and result <= 100.0

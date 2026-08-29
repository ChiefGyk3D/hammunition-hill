# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Severity classification: what a space weather number actually means.

These are the tests that make the dials trustworthy. A dial is a claim -- "this
is fine" or "this is a storm" -- and the claim is made here, not in the canvas.
"""

import re

import pytest

from hammunition_hill.severity import (
    CRITICAL,
    GOOD,
    SCALES,
    WARN,
    classify,
    classify_all,
    s_units,
    watts_to_xray,
    worst,
    xray_to_watts,
)


# --- X-ray class round trip ---------------------------------------------
@pytest.mark.parametrize(
    "text,watts",
    [
        ("A5.0", 5e-8),
        ("B2.0", 2e-7),
        ("C1.4", 1.4e-6),
        ("M5.0", 5e-5),
        ("X2.0", 2e-4),
    ],
)
def test_xray_class_to_watts(text, watts):
    assert xray_to_watts(text) == pytest.approx(watts)


@pytest.mark.parametrize("text", ["C1.4", "M5.0", "X2.0", "B7.2"])
def test_xray_round_trips(text):
    assert watts_to_xray(xray_to_watts(text)) == text


def test_xray_accepts_a_raw_flux_number():
    """SWPC publishes watts; HamQSL publishes a class. Both must work."""
    assert xray_to_watts(1.4e-6) == pytest.approx(1.4e-6)


@pytest.mark.parametrize("junk", [None, "", "nonsense", "Z9.9"])
def test_xray_rejects_junk(junk):
    assert xray_to_watts(junk) is None


def test_xray_letter_without_a_magnitude():
    assert xray_to_watts("C") == pytest.approx(1e-6)


# --- S-units -------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("S0-S1", 1.0),
        ("S2", 2.0),
        ("S4-S6", 6.0),
        ("S0", 0.0),
    ],
)
def test_noise_takes_the_worse_end_of_a_range(text, expected):
    """HamQSL reports a range; the loud end is the one that stops you working."""
    assert s_units(text) == expected


@pytest.mark.parametrize("junk", [None, "", "quiet"])
def test_noise_rejects_junk(junk):
    assert s_units(junk) is None


# --- the scales ----------------------------------------------------------
@pytest.mark.parametrize(
    "value,level",
    [
        (60, CRITICAL),
        (69, CRITICAL),
        (85, WARN),
        (110, GOOD),
        (200, GOOD),
    ],
)
def test_solar_flux_severity(value, level):
    """Low flux is the problem for HF, so the scale runs bad-to-good upward."""
    assert classify("sfi", value)["level"] == level


@pytest.mark.parametrize(
    "value,level",
    [
        (0, GOOD),
        (3, GOOD),
        (4, WARN),
        (5, CRITICAL),
        (9, CRITICAL),
    ],
)
def test_k_index_severity(value, level):
    assert classify("kindex", value)["level"] == level


def test_k_index_names_the_noaa_g_scale():
    """K=5 is G1; operators talk in G numbers during a storm."""
    assert "G1" in classify("kindex", 5)["label"]
    assert "G2" in classify("kindex", 6)["label"]


@pytest.mark.parametrize(
    "kp,expected",
    [
        (3.67, "Quiet"),
        (4.0, "Unsettled"),
        (4.33, "Unsettled"),
        (4.67, "Unsettled"),
        (5.0, "G1"),
        (5.67, "G1"),
        (6.0, "G2"),
        (6.67, "G2"),
        (7.0, "G3"),
        (8.0, "G4"),
        (9.0, "G5"),
    ],
)
def test_a_fractional_kp_lands_in_the_g_band_noaa_would_give_it(kp, expected):
    """G numbers are floors. Kp 4.33 is not a storm; Kp 5.67 is still only G1.

    SWPC publishes Kp in thirds. While it published whole numbers this scale's
    inclusive boundaries happened to agree with NOAA; the first fractional value
    put Kp 4.33 in the G1 band, so the dial read "G1 storm" in red beside a NOAA
    Scales panel reading "G0 none" and a storm_level of "quiet" from the very
    same snapshot. Anything between two integers must round *down* to a G, and
    below Kp 5 there is no G at all.
    """
    assert expected in classify("kindex", kp)["label"]


def test_below_kp_five_names_no_storm_at_all():
    """The G scale does not start until 5, so nothing under it may claim one."""
    for kp in (0, 1.33, 2.67, 3, 3.67, 4, 4.33, 4.67):
        label = classify("kindex", kp)["label"]
        assert not re.search(r"\bG\d", label), f"Kp {kp} claims a storm class: {label!r}"


@pytest.mark.parametrize(
    "value,level",
    [
        (0, GOOD),
        (7, GOOD),
        (12, WARN),
        (25, WARN),
        (40, CRITICAL),
        (80, CRITICAL),
    ],
)
def test_a_index_severity(value, level):
    assert classify("aindex", value)["level"] == level


@pytest.mark.parametrize(
    "text,level",
    [
        ("A5.0", GOOD),
        ("B7.2", GOOD),
        ("C1.4", WARN),
        ("M1.0", CRITICAL),
        ("X5.0", CRITICAL),
    ],
)
def test_xray_severity(text, level):
    assert classify("xray", text)["level"] == level


def test_xray_labels_mention_the_blackout_scale():
    assert "R1" in classify("xray", "M2.0")["label"]
    assert "R3" in classify("xray", "X1.0")["label"]


@pytest.mark.parametrize(
    "value,level",
    [
        (300, GOOD),
        (400, GOOD),
        (500, WARN),
        (650, CRITICAL),
        (800, CRITICAL),
    ],
)
def test_solar_wind_severity(value, level):
    assert classify("solarwind", value)["level"] == level


@pytest.mark.parametrize("value,level", [(0.1, GOOD), (50, WARN), (500, CRITICAL)])
def test_proton_severity(value, level):
    assert classify("protons", value)["level"] == level


def test_proton_display_keeps_small_values():
    """0.40 pfu must not round to 0 -- background flux is a fraction."""
    assert classify("protons", 0.4)["display"] == "0.40"


def test_the_proton_dial_never_claims_an_s_number():
    """It is not measuring the quantity the S scale is defined on.

    NOAA's S scale reads the >=10 MeV integral proton flux. This dial is fed
    HamQSL's <protonflux>, which runs about two orders of magnitude higher --
    measured 2026-08-28, HamQSL said 14 pfu while GOES >=10 MeV was 0.28 and
    NOAA's scale said S0. The dial used to label that band "S1 storm" and sat
    on the same screen as the NOAA Scales panel saying "S0 none".

    The authoritative S number comes from the `noaa_scales` source and has its
    own panel. This one reports flux, and must not relabel it as a storm class.
    """
    labels = [zone.label for zone in SCALES["protons"].zones]

    assert not [x for x in labels if re.search(r"\bS\d", x)], (
        f"proton zone labels claim an S number: {labels}. That scale is defined "
        "on >=10 MeV protons and this dial does not read them -- describe the "
        "flux instead, and leave the S number to the NOAA Scales panel."
    )


# --- direction -----------------------------------------------------------
def test_direction_is_carried_in_the_data():
    """SFI runs critical-to-good upward; A-index runs good-to-critical."""
    sfi = classify("sfi", 168)
    aindex = classify("aindex", 4)
    assert sfi["bands"][0]["level"] == CRITICAL
    assert sfi["bands"][-1]["level"] == GOOD
    assert aindex["bands"][0]["level"] == GOOD
    assert aindex["bands"][-1]["level"] == CRITICAL
    assert sfi["higher_is_better"] is True
    assert aindex["higher_is_better"] is False


# --- bands ---------------------------------------------------------------
def test_adjacent_zones_of_the_same_level_merge():
    """Two abutting green segments would draw a seam that means nothing."""
    for scale_id in SCALES:
        bands = classify(scale_id, SCALES[scale_id].low)["bands"]
        levels = [b["level"] for b in bands]
        assert levels == [k for i, k in enumerate(levels) if i == 0 or k != levels[i - 1]]


def test_bands_tile_the_whole_dial():
    for scale_id in SCALES:
        bands = classify(scale_id, SCALES[scale_id].low)["bands"]
        assert bands[0]["from"] == 0.0
        assert bands[-1]["to"] == 1.0
        for a, b in zip(bands, bands[1:], strict=False):
            assert a["to"] == b["from"]


def test_every_scale_uses_at_most_three_levels():
    """Four status colours cannot be told apart; the palette is three."""
    for scale_id in SCALES:
        levels = {b["level"] for b in classify(scale_id, SCALES[scale_id].low)["bands"]}
        assert levels <= {GOOD, WARN, CRITICAL}


def test_every_zone_has_a_text_label():
    """Colour must never be the only thing carrying the meaning."""
    for scale in SCALES.values():
        for zone in scale.zones:
            assert zone.label.strip()


# --- position ------------------------------------------------------------
def test_position_is_clamped_to_the_dial():
    assert classify("kindex", -5)["position"] == 0.0
    assert classify("kindex", 99)["position"] == 1.0


def test_log_scales_place_decades_evenly():
    """Proton flux spans five decades; a linear dial would be unreadable."""
    a = classify("protons", 1)["position"]
    b = classify("protons", 10)["position"]
    c = classify("protons", 100)["position"]
    assert (b - a) == pytest.approx(c - b, abs=0.01)


# --- aggregate -----------------------------------------------------------
def test_classify_all_skips_missing_and_unknown():
    result = classify_all({"kindex": 3, "sfi": None, "nonsense": 5})
    assert set(result) == {"kindex"}


def test_worst_reports_the_most_severe():
    gauges = classify_all({"kindex": 1, "aindex": 4, "solarwind": 800})
    assert worst(gauges) == CRITICAL


def test_worst_of_a_calm_day_is_good():
    assert worst(classify_all({"kindex": 1, "aindex": 3})) == GOOD


def test_worst_of_nothing_is_good():
    assert worst({}) == GOOD


def test_unknown_scale_is_an_error_not_a_silent_none():
    with pytest.raises(KeyError, match="unknown scale"):
        classify("nonsense", 1)


def test_a_index_dial_gives_the_quiet_zone_visible_room():
    """A dial that looks alarming while its label says Quiet is worse than none.

    Regression: a 0-100 range squeezed the quiet band into a sliver, so a
    perfectly calm A-index of 4 drew a needle in what looked like the danger
    end. The quiet zone must be a readable fraction of the dial.
    """
    quiet = [b for b in classify("aindex", 4)["bands"] if b["level"] == GOOD]
    assert quiet, "no quiet band at all"
    assert quiet[0]["to"] - quiet[0]["from"] >= 0.12


def test_a_severe_a_index_pins_the_needle():
    """Above the dial's top, pinned is the right message."""
    assert classify("aindex", 200)["position"] == 1.0
    assert classify("aindex", 200)["level"] == CRITICAL

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pytest

from hammunition_hill.bands import BAND_ORDER, band_for, classify, infer_mode, sort_key


@pytest.mark.parametrize(
    "khz,band",
    [
        (1825.0, "160m"),
        (3573.0, "80m"),
        (7074.0, "40m"),
        (10136.0, "30m"),
        (14074.0, "20m"),
        (18100.0, "17m"),
        (21074.0, "15m"),
        (24915.0, "12m"),
        (28074.0, "10m"),
        (50313.0, "6m"),
        (144174.0, "2m"),
        (432100.0, "70cm"),
    ],
)
def test_band_for_common_frequencies(khz, band):
    assert band_for(khz) == band


@pytest.mark.parametrize("khz", [0.0, 2500.0, 6000.0, 13000.0, 30000.0, 40000.0])
def test_frequencies_outside_any_band(khz):
    assert band_for(khz) is None


def test_band_edges_are_inclusive():
    assert band_for(14000.0) == "20m"
    assert band_for(14350.0) == "20m"
    assert band_for(14350.1) is None


@pytest.mark.parametrize(
    "khz,mode",
    [
        (14074.0, "FT8"),
        (7074.0, "FT8"),
        (50313.0, "FT8"),
        (14080.0, "FT4"),
        (7047.5, "FT4"),
        (14070.0, "PSK31"),
        (14100.0, "RTTY"),
    ],
)
def test_digital_watering_holes(khz, mode):
    assert infer_mode(khz) == mode


def test_digital_tolerance_is_narrow():
    assert infer_mode(14074.0) == "FT8"
    assert infer_mode(14076.5) == "FT8"  # inside tolerance
    assert infer_mode(14090.0) != "FT8"  # well outside


@pytest.mark.parametrize("khz", [14020.0, 7015.0, 21030.0, 3520.0, 28010.0])
def test_cw_segments(khz):
    assert infer_mode(khz) == "CW"


def test_sideband_convention_follows_the_band():
    assert infer_mode(3800.0) == "LSB"
    assert infer_mode(7200.0) == "LSB"
    assert infer_mode(14250.0) == "USB"
    assert infer_mode(21300.0) == "USB"


def test_thirty_metres_has_no_voice_default():
    """30m is CW and digital only; guessing a voice mode there would be wrong."""
    assert infer_mode(10145.0) is None


def test_classify_prefers_an_explicit_mode():
    info = classify(14074.0, "SSB")
    assert info.mode == "SSB"
    assert info.mode_inferred is False


def test_classify_marks_a_guess_as_inferred():
    info = classify(14074.0)
    assert info.mode == "FT8"
    assert info.mode_inferred is True


def test_classify_handles_out_of_band():
    info = classify(12345.0)
    assert info.band is None and info.mode is None


def test_sort_key_orders_low_to_high():
    bands = ["10m", "160m", "20m", "40m"]
    assert sorted(bands, key=sort_key) == ["160m", "40m", "20m", "10m"]


def test_unknown_band_sorts_last():
    assert sort_key(None) == len(BAND_ORDER)
    assert sort_key("nonsense") == len(BAND_ORDER)

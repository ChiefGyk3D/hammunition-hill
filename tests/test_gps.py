# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""GPS parsing, and the precision decision that keeps it publishable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hammunition_hill.gps import (
    ALLOWED_PRECISION,
    DEFAULT_PRECISION,
    Fix,
    checksum,
    clock_offset_seconds,
    parse_gpsd_tpv,
    parse_sentence,
)
from hammunition_hill.streams.position import publish


def nmea(body: str) -> str:
    """A well-formed sentence, checksum computed rather than hand-written."""
    return f"${body}*{checksum(body)}"


DENVER_GGA = "GPGGA,123519.00,3944.5000,N,10458.8000,W,1,08,0.9,1609.0,M,-17.0,M,,"
DENVER_RMC = "GNRMC,123519.00,A,3944.5000,N,10458.8000,W,0.02,31.66,270826,,,A"


class FakeCfg:
    def __init__(self, **options):
        self.id = "gps"
        self.options = options


# --- NMEA -----------------------------------------------------------------
def test_gga_parses_to_a_grid():
    fix = parse_sentence(nmea(DENVER_GGA))
    assert fix is not None
    assert fix.grid.startswith("DM79")
    assert fix.lat == pytest.approx(39.7417, abs=0.001)
    assert fix.lon == pytest.approx(-104.98, abs=0.001)
    assert fix.satellites == 8


def test_rmc_parses_to_the_same_place():
    gga = parse_sentence(nmea(DENVER_GGA))
    rmc = parse_sentence(nmea(DENVER_RMC))
    assert rmc is not None
    assert rmc.grid[:6] == gga.grid[:6]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("GPGGA,120000.00,5130.0000,N,00007.8000,W,2,10,0.8,25.0,M,45.0,M,,", "IO91"),
        ("GPGGA,120000.00,3352.2000,S,15112.6000,E,1,09,1.1,58.0,M,22.0,M,,", "QF56"),
        ("GPGGA,120000.00,3540.0000,N,13945.0000,E,1,09,1.1,40.0,M,39.0,M,,", "PM95"),
    ],
)
def test_both_hemispheres(body, expected):
    """S and W are negative. Getting a sign wrong puts you on the far side."""
    fix = parse_sentence(nmea(body))
    assert fix is not None
    assert fix.grid.startswith(expected)


def test_minutes_are_not_decimal_degrees():
    """ddmm.mmmm, not dd.dddd. The classic NMEA mistake is hundreds of miles.

    3944.5000 is 39 degrees 44.5 minutes = 39.7417, not 39.445.
    """
    fix = parse_sentence(nmea(DENVER_GGA))
    assert fix.lat == pytest.approx(39.7417, abs=0.0005)
    assert fix.lat != pytest.approx(39.445, abs=0.01)


def test_a_bad_checksum_is_rejected():
    """Serial lines drop bytes. A corrupted fix is worse than no fix."""
    good = nmea(DENVER_GGA)
    assert parse_sentence(good) is not None
    assert parse_sentence(good[:-2] + "00") is None


def test_no_fix_is_not_a_position():
    body = "GPGGA,123519.00,3944.5000,N,10458.8000,W,0,00,,,M,,M,,"
    assert parse_sentence(nmea(body)) is None


def test_void_rmc_is_not_a_position():
    """'V' means the receiver has not got a lock. It still reports coordinates."""
    body = "GPRMC,123519.00,V,3944.5000,N,10458.8000,W,0.02,31.66,270826,,,N"
    assert parse_sentence(nmea(body)) is None


@pytest.mark.parametrize(
    "line",
    [
        "",
        "garbage",
        "$GPGGA,1235",  # truncated mid-sentence
        "$GPGSV,3,1,11,01,05,040,42*7A",  # a sentence type we do not use
        "$GPGGA,123519.00,,,,,1,08,0.9,,M,,M,,*4A",  # fix flag set, no position
        "$" + "A" * 5000,
    ],
)
def test_garbage_never_raises(line):
    """A receiver produces junk at startup and after a dropped byte."""
    assert parse_sentence(line) is None


def test_talker_id_is_not_hardcoded_to_gps():
    """Modern receivers say GN for multi-constellation, GL, GA, GB for others."""
    for talker in ("GP", "GN", "GL", "GA", "GB"):
        body = DENVER_GGA.replace("GPGGA", f"{talker}GGA", 1)
        assert parse_sentence(nmea(body)) is not None, talker


def test_rmc_carries_a_date_and_gga_does_not():
    rmc = parse_sentence(nmea(DENVER_RMC))
    assert rmc.utc is not None
    assert (rmc.utc.year, rmc.utc.month, rmc.utc.day) == (2026, 8, 27)


# --- gpsd -----------------------------------------------------------------
def test_gpsd_tpv_parses():
    fix = parse_gpsd_tpv(
        {"class": "TPV", "mode": 3, "lat": 39.742, "lon": -104.98, "time": "2026-08-27T12:35:19Z"}
    )
    assert fix is not None
    assert fix.grid.startswith("DM79")
    assert fix.quality == "3D"


@pytest.mark.parametrize("mode", [0, 1])
def test_gpsd_without_a_fix_is_ignored(mode):
    """Modes 0 and 1 mean unknown and no-fix. gpsd still sends a report."""
    assert parse_gpsd_tpv({"class": "TPV", "mode": mode, "lat": 1.0, "lon": 2.0}) is None


def test_gpsd_other_report_classes_are_ignored():
    assert parse_gpsd_tpv({"class": "SKY", "satellites": []}) is None
    assert parse_gpsd_tpv({"class": "VERSION", "release": "3.25"}) is None


def test_gpsd_missing_coordinates_are_ignored():
    assert parse_gpsd_tpv({"class": "TPV", "mode": 3}) is None
    assert parse_gpsd_tpv({"class": "TPV", "mode": 3, "lat": "x", "lon": 2.0}) is None


# --- the privacy decision -------------------------------------------------
def test_coordinates_are_not_published_by_default():
    """A snapshot is readable by everyone on the LAN. A raw fix is your house."""
    fix = parse_sentence(nmea(DENVER_GGA))
    payload = fix.published(precision=DEFAULT_PRECISION, coordinates=False)
    assert "lat" not in payload
    assert "lon" not in payload
    assert payload["grid"] == fix.grid[:6]


def test_grid_is_truncated_to_the_configured_precision():
    fix = parse_sentence(nmea(DENVER_GGA))
    assert len(fix.published(precision=4, coordinates=False)["grid"]) == 4
    assert len(fix.published(precision=6, coordinates=False)["grid"]) == 6
    assert len(fix.published(precision=8, coordinates=False)["grid"]) == 8


def test_published_coordinates_are_rounded_to_match_the_grid():
    """Publishing a 4-char grid beside a 6-decimal latitude gives it away."""
    fix = parse_sentence(nmea(DENVER_GGA))
    coarse = fix.published(precision=4, coordinates=True)
    fine = fix.published(precision=8, coordinates=True)
    assert len(str(coarse["lat"]).split(".")[-1]) <= 1
    assert len(str(fine["lat"]).split(".")[-1]) <= 3


def test_an_invalid_precision_falls_back_to_the_default():
    """A typo must not silently publish a more precise location than intended."""
    fix = parse_sentence(nmea(DENVER_GGA))
    payload = publish(fix, FakeCfg(precision=12), source="nmea")
    assert payload["precision"] == DEFAULT_PRECISION
    assert len(payload["grid"]) == DEFAULT_PRECISION
    assert DEFAULT_PRECISION in ALLOWED_PRECISION


def test_default_publish_hides_coordinates():
    fix = parse_sentence(nmea(DENVER_GGA))
    payload = publish(fix, FakeCfg(), source="nmea")
    assert "lat" not in payload


def test_publish_says_so_when_there_is_no_fix():
    """ "Searching" and "not plugged in" are different problems under trees."""
    payload = publish(None, FakeCfg(), source="gpsd")
    assert payload["has_fix"] is False
    assert "no fix" in payload["reason"]


# --- the clock ------------------------------------------------------------
def test_clock_offset_is_reported():
    when = datetime.now(UTC) - timedelta(seconds=5)
    assert clock_offset_seconds(when) == pytest.approx(5.0, abs=1.0)


def test_clock_offset_is_none_without_a_timestamp():
    assert clock_offset_seconds(None) is None


def test_clock_ok_flags_the_threshold_ft8_cares_about():
    now = datetime.now(UTC)
    good = Fix(lat=39.7, lon=-105.0, grid="DM79", quality="3D", utc=now)
    bad = Fix(lat=39.7, lon=-105.0, grid="DM79", quality="3D", utc=now - timedelta(seconds=30))

    assert publish(good, FakeCfg(), source="gpsd")["clock_ok"] is True
    assert publish(bad, FakeCfg(), source="gpsd")["clock_ok"] is False


def test_a_stale_fix_is_flagged():
    old = Fix(
        lat=39.7,
        lon=-105.0,
        grid="DM79",
        quality="3D",
        utc=datetime.now(UTC) - timedelta(hours=1),
    )
    assert publish(old, FakeCfg(), source="gpsd")["stale"] is True

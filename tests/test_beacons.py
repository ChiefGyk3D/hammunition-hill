# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The NCDXF/IARU beacon schedule.

Worth testing carefully: the whole value of the panel is that it tells you which
beacon *should* be on the air, so you can listen and learn something from
whether it is. A schedule that is off by one slot is worse than no schedule.
"""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from hammunition_hill.beacons import (
    BANDS,
    BEACONS,
    CYCLE_SECONDS,
    SLOT_SECONDS,
    beacon_on,
    export,
    next_slot_for,
    schedule,
    seconds_into_slot,
    slot_at,
)

MIDNIGHT = datetime(2026, 8, 26, 0, 0, 0, tzinfo=UTC)


def at(hour=0, minute=0, second=0):
    """A moment, taking seconds as an offset so cycle arithmetic reads naturally."""
    return MIDNIGHT + timedelta(hours=hour, minutes=minute, seconds=second)


# --- the published schedule ---------------------------------------------
def test_the_cycle_starts_with_the_published_lineup():
    """At 00:00:00 UTC the official table reads 4U1UN, YV5B, OA4B, LU4AA, CS3B."""
    assert [e["beacon"] for e in schedule(at(0, 0, 0))] == [
        "4U1UN",
        "YV5B",
        "OA4B",
        "LU4AA",
        "CS3B",
    ]


def test_the_lineup_advances_every_ten_seconds():
    assert [e["beacon"] for e in schedule(at(0, 0, 10))] == [
        "VE8AT",
        "4U1UN",
        "YV5B",
        "OA4B",
        "LU4AA",
    ]


def test_the_lineup_holds_for_the_whole_slot():
    for second in range(10):
        assert beacon_on(0, at(0, 0, second)).callsign == "4U1UN"
    assert beacon_on(0, at(0, 0, 10)).callsign == "VE8AT"


def test_the_cycle_repeats_every_three_minutes():
    for band in BANDS:
        assert beacon_on(band, at(0, 0, 0)) == beacon_on(band, at(0, 3, 0))
        assert beacon_on(band, at(12, 34, 50)) == beacon_on(band, at(12, 37, 50))


def test_every_beacon_appears_once_per_band_per_cycle():
    for band in BANDS:
        slots = range(0, CYCLE_SECONDS, SLOT_SECONDS)
        seen = [beacon_on(band, at(second=s)).callsign for s in slots]
        assert sorted(seen) == sorted(b.callsign for b in BEACONS)


def test_five_different_beacons_are_on_at_once():
    """One per band, never the same station twice."""
    for second in range(0, CYCLE_SECONDS, SLOT_SECONDS):
        callsigns = [e["beacon"] for e in schedule(at(0, 0, second))]
        assert len(set(callsigns)) == 5


def test_a_beacon_climbs_one_band_every_slot():
    """Beacon i is on 20m at slot i, 17m at slot i+1, and so on."""
    beacon = BEACONS[3]  # KH6RS
    for band in BANDS:
        moment = at(0, 0, (beacon.index + band.index) * SLOT_SECONDS)
        assert beacon_on(band, moment) == beacon


# --- slot arithmetic -----------------------------------------------------
@pytest.mark.parametrize("second,expected", [(0, 0), (9, 0), (10, 1), (179, 17), (180, 0)])
def test_slot_numbering(second, expected):
    assert slot_at(at(second=second)) == expected


def test_seconds_into_slot():
    assert seconds_into_slot(at(0, 0, 0)) == 0
    assert seconds_into_slot(at(0, 0, 7)) == 7
    assert seconds_into_slot(at(0, 0, 10)) == 0


def test_slot_is_relative_to_utc_not_local_time():
    """The cycle is synchronised to UTC; a local timezone must not shift it."""
    utc_noon = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)
    same_moment_elsewhere = utc_noon.astimezone(timezone(timedelta(hours=9)))
    assert slot_at(same_moment_elsewhere) == slot_at(utc_noon)
    assert beacon_on(0, same_moment_elsewhere) == beacon_on(0, utc_noon)


def test_next_slot_counts_down_to_the_beacon_returning():
    beacon = BEACONS[5]
    seconds = next_slot_for(beacon, 0, at(0, 0, 0))
    assert seconds == beacon.index * SLOT_SECONDS
    assert beacon_on(0, at(0, 0, seconds)) == beacon


def test_a_beacon_on_air_now_has_no_wait():
    assert next_slot_for(BEACONS[0], 0, at(0, 0, 0)) == 0


# --- the data ------------------------------------------------------------
def test_eighteen_beacons_and_five_bands():
    assert len(BEACONS) == 18
    assert len(BANDS) == 5


def test_beacon_indices_are_sequential():
    assert [b.index for b in BEACONS] == list(range(18))


def test_callsigns_are_unique():
    assert len({b.callsign for b in BEACONS}) == 18


def test_coordinates_are_plausible():
    for beacon in BEACONS:
        assert -90 <= beacon.lat <= 90, beacon.callsign
        assert -180 <= beacon.lon <= 180, beacon.callsign
        assert beacon.grid, beacon.callsign


def test_grids_agree_with_coordinates():
    """A grid that disagrees with its lat/lon would send a beam the wrong way."""
    from hammunition_hill.geo import grid_to_latlon

    for beacon in BEACONS:
        lat, lon = grid_to_latlon(beacon.grid)
        assert abs(lat - beacon.lat) < 1.5, f"{beacon.callsign} latitude"
        assert abs(lon - beacon.lon) < 2.5, f"{beacon.callsign} longitude"


def test_frequencies_are_the_published_ones():
    assert [b.khz for b in BANDS] == [14100.0, 18110.0, 21150.0, 24930.0, 28200.0]


def test_beacon_frequencies_fall_in_their_bands():
    from hammunition_hill.bands import band_for

    for band in BANDS:
        assert band_for(band.khz) == band.name


# --- the published file --------------------------------------------------
def test_bundled_json_matches_the_module():
    """web/beacons.json is generated; it must not drift from the source."""
    published = json.loads(
        (Path(__file__).resolve().parent.parent / "web" / "beacons.json").read_text()
    )
    assert published == json.loads(json.dumps(export()))


def test_export_carries_the_caveat():
    """A beacon that should be transmitting may simply be off the air."""
    assert "may be off the air" in str(export()["note"])

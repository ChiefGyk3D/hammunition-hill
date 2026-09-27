# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""KC2G's ionosonde roster, and the stale readings hiding in it.

The records below are taken verbatim from a real response fetched on
2026-09-27, trimmed to the fields that matter. That matters more than usual
here, because every awkward thing this parser handles is something the live
feed actually does and no summary of the API would have told us:

* **Latitude and longitude arrive as strings**, in 0..360 east, and not always
  with a decimal point -- Athens is ``"38"``. ``md`` is quoted while ``mufd``
  right beside it is a bare float.
* **The feed is a roster, not a snapshot.** Every station KC2G knows about is
  in every response, carrying whatever reading it last managed. Austin's entry
  is six months old; Beijing's is from 2021.
* **The confidence score does not encode staleness.** Austin's six-month-old
  sounding scores ``cs: 100.0`` -- as high as anything live. Only the timestamp
  separates them, and the timestamps carry no timezone.

So the property under test is not "it parsed". It is that a stale sounding
never reaches the panel, because a precise, confident, six-month-old foF2
printed next to a live one is worse than showing nothing -- the same reasoning
that made the proton dial read GOES directly instead of trusting a convenient
upstream field.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from hammunition_hill.config import SourceConfig
from hammunition_hill.sources.base import FetchError
from hammunition_hill.sources.ionosonde import (
    MAX_AGE_MINUTES,
    IonosondeSource,
    _reduce,
)

NOW = datetime(2026, 9, 27, 15, 15, 0, tzinfo=UTC)

# Verbatim from the live feed, including the nulls.
LIVE_SPAIN = {
    "time": "2026-09-27T15:10:01",
    "mufd": 25.023,
    "station": {
        "code": "EA036",
        "longitude": "353.3",
        "name": "El Arenosillo, Spain",
        "latitude": "37.1",
        "id": 2,
    },
    "hmf2": 238.234,
    "cs": 70.0,
    "md": "3.292",
    "fof2": 7.6,
    "tec": 15.566,
    "source": "giro",
}
# Six months old, and scored 100. This is the one that matters.
STALE_AUSTIN = {
    "time": "2026-03-19T22:10:05",
    "mufd": 28.827,
    "station": {
        "code": "AU930",
        "longitude": "262.3",
        "name": "Austin, TX, USA",
        "latitude": "30.4",
        "id": 1,
    },
    "hmf2": 241.8,
    "cs": 100.0,
    "md": "3.352",
    "fof2": 8.6,
    "tec": 15.837,
    "source": "giro",
}
# From 2021, and never scaled.
NEVER_SCALED_BEIJING = {
    "time": "2021-08-22T23:00:01",
    "mufd": None,
    "station": {
        "code": "BP440",
        "longitude": "116.2",
        "name": "Beijing, China",
        "latitude": "40.3",
        "id": 5,
    },
    "hmf2": None,
    "cs": -1.0,
    "md": None,
    "fof2": 5.0,
    "tec": None,
    "source": "noaa",
}
# Latitude with no decimal point, and a null TEC.
LIVE_ATHENS = {
    "time": "2026-09-27T15:10:00",
    "mufd": 27.715,
    "station": {
        "code": "AT138",
        "longitude": "23.5",
        "name": "Athens, Greece",
        "latitude": "38",
        "id": 4,
    },
    "hmf2": 234.254,
    "cs": 65.0,
    "md": "3.551",
    "fof2": 7.805,
    "tec": None,
    "source": "giro",
}
# East of Greenwich by half a degree: the one that catches a bad wrap.
LIVE_ROQUETES = {
    "time": "2026-09-27T15:10:01",
    "mufd": 24.09,
    "station": {
        "code": "EB040",
        "longitude": "0.5",
        "name": "Roquetes, Spain",
        "latitude": "40.8",
        "id": 3,
    },
    "hmf2": 223.282,
    "cs": 75.0,
    "md": "3.543",
    "fof2": 6.8,
    "tec": None,
    "source": "giro",
}

ROSTER = [STALE_AUSTIN, LIVE_SPAIN, LIVE_ROQUETES, LIVE_ATHENS, NEVER_SCALED_BEIJING]


def reduced(records=None, now=NOW):
    return _reduce(records if records is not None else ROSTER, now)


def by_code(data):
    return {s["code"]: s for s in data["stations"]}


# --- the thing this source exists to get right ---------------------------
def test_a_six_month_old_sounding_does_not_reach_the_panel():
    """Austin: fof2 8.6, cs 100, timestamped March. It must not be published."""
    assert "AU930" not in by_code(reduced())


def test_confidence_alone_would_not_have_caught_it():
    """Guards the reasoning, not just the outcome.

    If someone later replaces the age check with a confidence threshold, this
    says why that does not work: the stale record outscores the live ones.
    """
    assert STALE_AUSTIN["cs"] > LIVE_SPAIN["cs"]
    assert STALE_AUSTIN["cs"] > LIVE_ATHENS["cs"]


def test_a_reading_just_inside_the_window_is_kept_and_just_outside_is_not():
    fresh = {
        **LIVE_SPAIN,
        "time": (NOW - timedelta(minutes=MAX_AGE_MINUTES - 1)).replace(tzinfo=None).isoformat(),
    }
    stale = {
        **LIVE_SPAIN,
        "time": (NOW - timedelta(minutes=MAX_AGE_MINUTES + 1)).replace(tzinfo=None).isoformat(),
    }
    assert reduced([fresh])["station_count"] == 1
    assert reduced([stale])["station_count"] == 0


def test_the_never_scaled_station_is_dropped():
    assert "BP440" not in by_code(reduced())


def test_a_fresh_but_unscaled_sounding_is_dropped_too():
    """Isolates the confidence guard from the age guard.

    Beijing in the live sample is both unscaled *and* years old, so asserting
    it is absent proves nothing about `cs` -- the age check already removed it,
    and deleting the confidence check entirely left every other test in this
    file green. A reading has to be fresh and unscaled to pin that guard, which
    the roster does not happen to contain, so it is constructed here.
    """
    fresh_unscaled = {**LIVE_SPAIN, "cs": -1.0}
    assert reduced([fresh_unscaled])["station_count"] == 0
    assert reduced([fresh_unscaled])["dropped"] == 1


def test_what_was_dropped_is_said_out_loud():
    """A panel has to tell "quiet ionosphere" from "we discarded the feed"."""
    data = reduced()
    assert data["roster_size"] == 5
    assert data["station_count"] == 3
    assert data["dropped"] == 2


# --- the shapes the live feed actually sends ------------------------------
def test_longitude_comes_back_in_the_projections_range():
    stations = by_code(reduced())
    assert stations["EA036"]["lon"] == pytest.approx(-6.7)  # "353.3" east
    assert stations["EB040"]["lon"] == pytest.approx(0.5)  # just east of Greenwich
    assert all(-180 <= s["lon"] <= 180 for s in reduced()["stations"])


def test_quoted_and_decimal_less_coordinates_parse():
    assert by_code(reduced())["AT138"]["lat"] == pytest.approx(38.0)  # "38"


def test_quoted_md_becomes_a_number_beside_unquoted_mufd():
    athens = by_code(reduced())["AT138"]
    assert athens["md"] == pytest.approx(3.551)
    assert athens["mufd"] == pytest.approx(27.715)


def test_a_null_field_stays_null_rather_than_becoming_zero():
    """TEC is often absent. Zero TEC is a measurement; absent is not."""
    assert by_code(reduced())["AT138"]["tec"] is None


def test_timestamps_without_a_zone_are_read_as_utc(monkeypatch):
    """The feed sends no offset. Read as local, every age shifts by the machine.

    The local zone is forced away from UTC first, because otherwise this test
    is vacuous: CI runners and this project's containers are UTC, so reading
    the naive string as local would give the identical answer and the check
    would pass on the one configuration it is meant to rule out. That is the
    ElementTree lesson from `lookup/session_xml.py` -- a real bug that passed
    on the dev venv and failed on the rest of the matrix.

    Athens is 5 minutes old at NOW. Read as US Eastern it would come out four
    hours adrift, and land outside the staleness window entirely.
    """
    if not hasattr(time, "tzset"):
        pytest.skip("needs POSIX tzset")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        athens = by_code(reduced())["AT138"]
        assert athens["age_minutes"] == pytest.approx(5.0, abs=0.1)
        assert athens["observed_at"] == "2026-09-27T15:10:00Z"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_a_station_with_neither_fof2_nor_muf_is_not_plotted():
    blank = {**LIVE_SPAIN, "fof2": None, "mufd": None}
    assert reduced([blank])["station_count"] == 0


def test_an_upstream_clock_a_little_ahead_is_not_discarded():
    """Clock skew of seconds is normal and not a reason to drop a sounding."""
    ahead = {**LIVE_SPAIN, "time": (NOW + timedelta(seconds=30)).replace(tzinfo=None).isoformat()}
    assert reduced([ahead])["station_count"] == 1


# --- the fetch path -------------------------------------------------------
async def run(body, content_type="application/json"):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": content_type})
    )
    cfg = SourceConfig(id="t", kind="ionosonde", url="https://prop.example/api/stations.json")
    async with httpx.AsyncClient(transport=transport) as client:
        return await IonosondeSource().fetch(client, cfg)


async def test_fetch_parses_a_roster():
    data = await run(json.dumps(ROSTER))
    # Everything in ROSTER is stale relative to a real "now", except nothing --
    # so assert the envelope rather than the contents, which the clock governs.
    assert data["roster_size"] == 5
    assert set(data) >= {"stations", "station_count", "dropped", "max_age_minutes"}


async def test_a_non_list_payload_is_a_fetch_error():
    with pytest.raises(FetchError, match="expected a list"):
        await run(json.dumps({"stations": []}))


async def test_a_non_json_payload_is_a_fetch_error():
    with pytest.raises(FetchError, match="not JSON"):
        await run("<html>maintenance</html>", content_type="text/html")


async def test_junk_entries_do_not_take_the_whole_fetch_down():
    """One malformed row should cost that row, not the cycle."""
    data = await run(json.dumps([LIVE_SPAIN, "nonsense", 42, {"station": None}, None]))
    assert data["roster_size"] == 5
    assert data["dropped"] >= 4

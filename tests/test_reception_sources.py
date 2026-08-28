# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""PSK Reporter and WSPR: the sources that report who is hearing you."""

import httpx
import pytest

from hammunition_hill.config import SourceConfig
from hammunition_hill.sources.base import FetchError
from hammunition_hill.sources.pskreporter import PskReporterSource
from hammunition_hill.sources.wspr import MAX_REPORTS as WSPR_MAX
from hammunition_hill.sources.wspr import WsprSource, build_query


async def run(source, body, *, options=None, capture=None, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request.url)
        return httpx.Response(status, text=body)

    cfg = SourceConfig(
        id="t",
        kind=source.kind,
        url="https://api.example/query",
        options=options if options is not None else {"callsign": "N0CALL"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await source.fetch(client, cfg)


# --- PSK Reporter --------------------------------------------------------

PSK_BODY = """<?xml version="1.0"?>
<receptionReports currentSeconds="1787925600">
 <receptionReport receiverCallsign="ja1abc" receiverLocator="PM95vp"
   senderCallsign="N0CALL" senderLocator="FN04ga" frequency="14074123"
   mode="FT8" sNR="-12" flowStartSeconds="1787925500" isSender="1"/>
 <receptionReport receiverCallsign="G4XYZ" receiverLocator="IO91"
   senderCallsign="N0CALL" frequency="7074000" mode="FT8" sNR="3"
   flowStartSeconds="1787925540"/>
 <receptionReport receiverCallsign="VK2DEF" senderCallsign="SOMEONEELSE"
   frequency="14074000" mode="FT8" sNR="-5" flowStartSeconds="1787925560"/>
 <receptionReport receiverCallsign="" senderCallsign="N0CALL"
   frequency="14074000" flowStartSeconds="1787925570"/>
</receptionReports>"""


async def test_pskreporter_parses_reports():
    data = await run(PskReporterSource(), PSK_BODY)
    assert data["program"] == "PSK Reporter"
    assert data["call"] == "N0CALL"
    assert data["count"] == 2


async def test_pskreporter_reports_are_newest_first():
    calls = [s["call"] for s in (await run(PskReporterSource(), PSK_BODY))["spots"]]
    assert calls == ["G4XYZ", "JA1ABC"]


async def test_pskreporter_maps_the_fields_the_globes_need():
    """band + grid is what lights a sphere; khz/mode/snr is what the list shows."""
    spot = (await run(PskReporterSource(), PSK_BODY))["spots"][1]
    assert spot == {
        "call": "JA1ABC",
        "grid": "PM95vp",
        "khz": pytest.approx(14074.123),
        "band": "20m",
        "mode": "FT8",
        "snr": -12,
        "at": "2026-08-28T13:58:20Z",
    }


async def test_pskreporter_drops_reports_for_other_senders():
    """rronly filters server-side, but the parser must not trust the flag."""
    calls = [s["call"] for s in (await run(PskReporterSource(), PSK_BODY))["spots"]]
    assert "VK2DEF" not in calls


async def test_pskreporter_query_carries_only_the_declared_callsign():
    seen: list[httpx.URL] = []
    await run(PskReporterSource(), PSK_BODY, capture=seen)
    params = dict(seen[0].params)
    assert params["senderCallsign"] == "N0CALL"
    assert params["rronly"] == "1"
    assert params["flowStartSeconds"] == "-900"


async def test_pskreporter_window_option_reaches_the_query():
    seen: list[httpx.URL] = []
    await run(
        PskReporterSource(),
        PSK_BODY,
        options={"callsign": "N0CALL", "window_minutes": 30},
        capture=seen,
    )
    assert dict(seen[0].params)["flowStartSeconds"] == "-1800"


async def test_pskreporter_window_is_clamped():
    seen: list[httpx.URL] = []
    await run(
        PskReporterSource(),
        PSK_BODY,
        options={"callsign": "N0CALL", "window_minutes": 9999},
        capture=seen,
    )
    assert dict(seen[0].params)["flowStartSeconds"] == "-3600"


async def test_pskreporter_requires_a_callsign_and_says_why():
    with pytest.raises(FetchError, match="options.callsign"):
        await run(PskReporterSource(), PSK_BODY, options={})


async def test_pskreporter_never_queries_without_a_callsign():
    """The refusal must come before the request: nothing is sent upstream."""
    seen: list[httpx.URL] = []
    with pytest.raises(FetchError):
        await run(PskReporterSource(), PSK_BODY, options={}, capture=seen)
    assert seen == []


async def test_pskreporter_rejects_a_junk_callsign():
    with pytest.raises(FetchError, match="does not look like a callsign"):
        await run(PskReporterSource(), PSK_BODY, options={"callsign": "N0CALL&rronly=0"})


async def test_pskreporter_accepts_a_portable_suffix():
    data = await run(PskReporterSource(), PSK_BODY, options={"callsign": "n0call/p"})
    assert data["call"] == "N0CALL/P"


async def test_pskreporter_rejects_non_xml():
    with pytest.raises(FetchError, match="not XML"):
        await run(PskReporterSource(), "{}")


# --- WSPR ----------------------------------------------------------------

# ClickHouse FORMAT JSON, with 64-bit integers quoted as it emits by default.
WSPR_BODY = """{
 "meta": [{"name": "time", "type": "DateTime"}],
 "data": [
  {"time": "2026-08-28 13:58:00", "rx_sign": "oe9ghv", "rx_lat": 47.3,
   "rx_lon": 9.6, "rx_loc": "JN47tm", "distance": "6423", "snr": -21,
   "power": 37, "frequency": "14097093"},
  {"time": "2026-08-28 13:56:00", "rx_sign": "K1JT", "rx_lat": 40.4,
   "rx_lon": -74.2, "rx_loc": "FN20qi", "distance": 512.5, "snr": "-8",
   "power": "23", "frequency": 7040112},
  {"time": "2026-08-28 13:54:00", "rx_sign": "", "frequency": 7040100}
 ],
 "rows": 3
}"""


async def test_wspr_parses_reports():
    data = await run(WsprSource(), WSPR_BODY)
    assert data["program"] == "WSPR"
    assert data["count"] == 2


async def test_wspr_maps_the_fields_the_globes_need():
    spot = (await run(WsprSource(), WSPR_BODY))["spots"][0]
    assert spot == {
        "call": "OE9GHV",
        "grid": "JN47tm",
        "lat": 47.3,
        "lon": 9.6,
        "khz": pytest.approx(14097.093),
        "band": "20m",
        "mode": "WSPR",
        "snr": -21,
        "power_dbm": 37,
        "distance_km": 6423.0,
        "at": "2026-08-28T13:58:00Z",
    }


async def test_wspr_coerces_clickhouse_quoted_numbers():
    """FORMAT JSON quotes 64-bit ints; every numeric field must survive that."""
    spot = (await run(WsprSource(), WSPR_BODY))["spots"][1]
    assert spot["snr"] == -8
    assert spot["power_dbm"] == 23
    assert spot["band"] == "40m"


async def test_wspr_query_is_the_documented_select():
    seen: list[httpx.URL] = []
    await run(WsprSource(), WSPR_BODY, capture=seen)
    sql = dict(seen[0].params)["query"]
    assert sql == build_query("N0CALL", 30)
    assert f"LIMIT {WSPR_MAX}" in sql
    assert "tx_sign = 'N0CALL'" in sql


async def test_wspr_a_callsign_cannot_escape_the_sql_literal():
    """The validation pattern admits no quote and no backslash, so an
    injection attempt dies as "not a callsign" before any query is built."""
    seen: list[httpx.URL] = []
    with pytest.raises(FetchError, match="does not look like a callsign"):
        await run(WsprSource(), WSPR_BODY, options={"callsign": "X'; DROP TABLE--"}, capture=seen)
    assert seen == []


async def test_wspr_rejects_non_json():
    with pytest.raises(FetchError, match="not JSON"):
        await run(WsprSource(), "<html>rate limited</html>")


async def test_wspr_rejects_json_without_a_data_array():
    with pytest.raises(FetchError, match="data array"):
        await run(WsprSource(), '{"rows": 0}')


def test_both_kinds_are_registered():
    from hammunition_hill.sources import REGISTRY

    assert REGISTRY["pskreporter"].kind == "pskreporter"
    assert REGISTRY["wspr"].kind == "wspr"

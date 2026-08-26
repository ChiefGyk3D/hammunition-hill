"""POTA, SOTA, iCalendar, and the local ADIF source."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from hammunition_hill.config import SourceConfig
from hammunition_hill.enrich import Enricher, Station
from hammunition_hill.prefix import PrefixTable
from hammunition_hill.sources.base import FetchError
from hammunition_hill.sources.ics import IcsSource, parse_ics, unescape, unfold
from hammunition_hill.sources.local import AdifLogSource
from hammunition_hill.sources.pota import PotaSource
from hammunition_hill.sources.sota import SotaSource


async def run(
    source,
    body,
    *,
    url="https://api.example/x",
    options=None,
    content_type="application/json",
):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": content_type})
    )
    cfg = SourceConfig(id="t", kind=source.kind, url=url, options=options or {})
    async with httpx.AsyncClient(transport=transport) as client:
        return await source.fetch(client, cfg)


# --- POTA ---------------------------------------------------------------
POTA_BODY = """[
 {"activator":"K1ABC","frequency":"14285.0","mode":"SSB","reference":"US-0001",
  "name":"Acadia NP","locationDesc":"US-ME","grid6":"FN54ir","latitude":44.35,
  "longitude":-68.21,"spotter":"W1XYZ","comments":"QRP","spotTime":"2026-08-26T12:00:00"},
 {"activator":"KB2DEF","frequency":"7032.0","mode":"CW","reference":"US-0002",
  "name":"Somewhere SP","latitude":42.0,"longitude":-71.0,"spotTime":"2026-08-26T12:05:00"},
 {"activator":"KC3GHI","frequency":"14074.0","mode":"FT8","invalid":true}
]"""


async def test_pota_parses_spots():
    data = await run(PotaSource(), POTA_BODY)
    assert data["program"] == "POTA"
    assert data["count"] == 2


async def test_pota_drops_superseded_spots():
    """POTA marks stale spots invalid rather than removing them."""
    calls = [s["call"] for s in (await run(PotaSource(), POTA_BODY))["spots"]]
    assert "KC3GHI" not in calls


async def test_pota_keeps_park_coordinates():
    first = (await run(PotaSource(), POTA_BODY))["spots"][0]
    assert (first["lat"], first["lon"]) == (44.35, -68.21)
    assert first["reference"] == "US-0001"


async def test_pota_frequency_stays_in_khz():
    assert (await run(PotaSource(), POTA_BODY))["spots"][0]["khz"] == 14285.0


async def test_pota_rejects_a_non_list():
    with pytest.raises(FetchError, match="expected a list"):
        await run(PotaSource(), '{"spots": []}')


async def test_pota_survives_junk_rows():
    data = await run(PotaSource(), '[null, 42, {"activator":""}, {"activator":"K1ABC"}]')
    assert data["count"] == 1


# --- SOTA ---------------------------------------------------------------
SOTA_BODY = """[
 {"activatorCallsign":"G4ABC","frequency":"14.285","mode":"ssb",
  "associationCode":"G","summitCode":"LD-001","summitDetails":"Scafell Pike",
  "callsign":"M0XYZ","comments":"windy","timeStamp":"2026-08-26T12:00:00"},
 {"activatorCallsign":"DL1ABC","frequency":"7.032","mode":"cw",
  "associationCode":"DM","summitCode":"BW-001","timeStamp":"2026-08-26T12:05:00"}
]"""


async def test_sota_parses_spots():
    data = await run(SotaSource(), SOTA_BODY)
    assert data["program"] == "SOTA"
    assert data["count"] == 2


async def test_sota_converts_mhz_to_khz():
    """SOTA publishes MHz; every other spot in the system is kHz."""
    assert (await run(SotaSource(), SOTA_BODY))["spots"][0]["khz"] == 14285.0


async def test_sota_builds_the_summit_reference():
    assert (await run(SotaSource(), SOTA_BODY))["spots"][0]["reference"] == "G/LD-001"


async def test_sota_normalizes_mode_case():
    assert (await run(SotaSource(), SOTA_BODY))["spots"][0]["mode"] == "SSB"


async def test_sota_handles_a_missing_frequency():
    data = await run(SotaSource(), '[{"activatorCallsign":"G4ABC"}]')
    assert data["spots"][0]["khz"] is None


# --- iCalendar ----------------------------------------------------------
def _ics(events):
    return "BEGIN:VCALENDAR\r\n" + "".join(events) + "END:VCALENDAR\r\n"


def _event(name, start, end=None, url=None):
    lines = ["BEGIN:VEVENT\r\n", f"SUMMARY:{name}\r\n", f"DTSTART:{start}\r\n"]
    if end:
        lines.append(f"DTEND:{end}\r\n")
    if url:
        lines.append(f"URL:{url}\r\n")
    lines.append("END:VEVENT\r\n")
    return "".join(lines)


def _stamp(offset_days, hour=0):
    when = datetime.now(UTC) + timedelta(days=offset_days)
    return when.replace(hour=hour, minute=0, second=0).strftime("%Y%m%dT%H%M%SZ")


def test_unfold_joins_continuation_lines():
    """Publishers wrap at 75 octets, so almost every long SUMMARY is folded.

    RFC 5545 folding inserts CRLF plus one space, and unfolding removes both --
    so any space that belongs to the content sits before the fold, not after.
    """
    assert unfold("SUMMARY:CQ World \r\n Wide DX Contest") == ["SUMMARY:CQ World Wide DX Contest"]


def test_unfold_does_not_invent_whitespace():
    """A word split across a fold rejoins with no space, which is the whole point."""
    assert unfold("SUMMARY:Contest\r\n Calendar") == ["SUMMARY:ContestCalendar"]


def test_unfold_accepts_tabs_as_continuation():
    assert unfold("SUMMARY:a\r\n\tb") == ["SUMMARY:ab"]


def test_unescape_handles_ics_escapes():
    assert unescape(r"CQ WW\, SSB\; phone") == "CQ WW, SSB; phone"


def test_upcoming_events_are_returned_soonest_first():
    text = _ics([_event("Later", _stamp(5)), _event("Sooner", _stamp(2))])
    assert [e["name"] for e in parse_ics(text)] == ["Sooner", "Later"]


def test_past_events_are_dropped():
    text = _ics([_event("Old", _stamp(-30), _stamp(-29)), _event("Next", _stamp(3))])
    assert [e["name"] for e in parse_ics(text)] == ["Next"]


def test_a_contest_running_right_now_is_kept_and_flagged():
    """It started yesterday and ends tomorrow -- that is exactly what you want to see."""
    text = _ics([_event("Running", _stamp(-1), _stamp(1))])
    events = parse_ics(text)
    assert events[0]["active"] is True


def test_events_beyond_the_horizon_are_dropped():
    text = _ics([_event("Far off", _stamp(90))])
    assert parse_ics(text, horizon_days=21) == []


def test_all_day_events_parse():
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y%m%d")
    text = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Field Day\r\n"
    text += f"DTSTART;VALUE=DATE:{tomorrow}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    assert parse_ics(text)[0]["name"] == "Field Day"


def test_only_http_urls_survive():
    text = _ics([_event("Bad", _stamp(2), url="javascript:alert(1)")])
    assert parse_ics(text)[0]["url"] is None


async def test_ics_source_rejects_non_calendar_bodies():
    with pytest.raises(FetchError, match="does not look like an iCalendar feed"):
        await run(IcsSource(), "<html>404</html>", content_type="text/html")


async def test_ics_source_labels_its_output():
    text = _ics([_event("CQ WW", _stamp(2))])
    data = await run(IcsSource(), text, options={"label": "Contests"}, content_type="text/calendar")
    assert data["label"] == "Contests"
    assert data["count"] == 1


# --- local ADIF source ---------------------------------------------------
@pytest.fixture
def enricher():
    return Enricher(PrefixTable(None), Station.from_config({"grid": "FN31pr"}))


def test_adif_source_indexes_a_log(tmp_path, enricher):
    log = tmp_path / "log.adi"
    log.write_text("<CALL:4>W1AW<BAND:3>20M<MODE:3>SSB<EOR><CALL:6>JA1ABC<BAND:3>40M<EOR>")
    data = AdifLogSource().load(SourceConfig(id="log", kind="adif", path=str(log)), enricher)

    assert data["found"] is True
    assert data["qso_count"] == 2
    assert data["entities"] == 2
    assert enricher.log_index is not None


def test_adif_source_reports_a_missing_log(tmp_path, enricher):
    cfg = SourceConfig(id="log", kind="adif", path=str(tmp_path / "nope.adi"))
    data = AdifLogSource().load(cfg, enricher)
    assert data["found"] is False
    assert enricher.log_index is None


def test_adif_source_reports_which_prefix_table_was_used(tmp_path, enricher):
    log = tmp_path / "log.adi"
    log.write_text("<CALL:4>W1AW<EOR>")
    data = AdifLogSource().load(SourceConfig(id="log", kind="adif", path=str(log)), enricher)
    assert data["prefix_source"] == "built-in"

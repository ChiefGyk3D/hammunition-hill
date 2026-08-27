# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""NWS alerts, and the tier 2 imagery declaration."""

import dataclasses

import httpx
import pytest

from hammunition_hill.config import ConfigError, ImageryTile, parse_config
from hammunition_hill.server import build_csp
from hammunition_hill.sources import get_source
from hammunition_hill.sources.base import FetchError
from hammunition_hill.sources.weather import MAX_ALERTS, NwsAlertsSource


async def run(body, *, url="https://api.weather.gov/alerts/active?area=CO", status=200):
    from hammunition_hill.config import SourceConfig

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status, text=body, headers={"content-type": "application/geo+json"}
        )
    )
    source = NwsAlertsSource()
    config = SourceConfig(id="wxalerts", kind=source.kind, url=url)
    async with httpx.AsyncClient(transport=transport) as client:
        return await source.fetch(client, config)


def base_cfg(**overrides):
    base = {
        "server": {"host": "127.0.0.1", "port": 8073},
        "sources": [
            {"id": "hamqsl", "kind": "hamqsl", "url": "https://www.hamqsl.com/solarxml.php"}
        ],
    }
    base.update(overrides)
    return base


def feature(event, severity, urgency="Immediate", **extra):
    properties = {
        "event": event,
        "severity": severity,
        "urgency": urgency,
        "certainty": "Observed",
        "headline": f"{event} issued",
        "areaDesc": "Denver, CO",
        "senderName": "NWS Boulder",
        **extra,
    }
    return {"type": "Feature", "properties": properties}


def body(*features, updated="2026-08-27T18:00:00+00:00"):
    import json

    return json.dumps({"type": "FeatureCollection", "updated": updated, "features": list(features)})


# --- parsing --------------------------------------------------------------
@pytest.mark.asyncio
async def test_parses_alerts():
    data = await run(body(feature("Tornado Warning", "Extreme")))
    assert data["count"] == 1
    alert = data["alerts"][0]
    assert alert["event"] == "Tornado Warning"
    assert alert["level"] == "critical"
    assert alert["area"] == "Denver, CO"
    assert alert["sender"] == "NWS Boulder"


@pytest.mark.asyncio
async def test_quiet_is_a_result_not_an_absence():
    """No alerts must produce a payload, not a failure.

    The panel says "No active alerts" from this, which is a different statement
    from a blank panel. Returning None here would collapse the two.
    """
    data = await run(body())
    assert data["count"] == 0
    assert data["alerts"] == []
    assert data["worst"] == "good"


@pytest.mark.asyncio
async def test_severity_maps_onto_the_status_ramp():
    data = await run(
        body(
            feature("Tornado Warning", "Extreme"),
            feature("Winter Storm Warning", "Severe"),
            feature("Wind Advisory", "Moderate"),
            feature("Small Craft Advisory", "Minor"),
            feature("Special Statement", "Unknown"),
        )
    )
    levels = {a["event"]: a["level"] for a in data["alerts"]}
    assert levels["Tornado Warning"] == "critical"
    assert levels["Winter Storm Warning"] == "critical"
    assert levels["Wind Advisory"] == "warn"
    # Minor and Unknown sit on `good` on purpose: the ramp is about how much
    # attention is needed now, and colouring a small craft advisory like a
    # tornado warning would make the ramp meaningless on the day it matters.
    assert levels["Small Craft Advisory"] == "good"
    assert levels["Special Statement"] == "good"
    assert data["worst"] == "critical"


@pytest.mark.asyncio
async def test_an_unknown_severity_word_is_not_silently_calm():
    """A severity NWS adds later must not read as quiet.

    Defaulting an unrecognised value to `good` would make a new alert class
    invisible. Unrecognised means "we do not know", which is at least `warn`.
    """
    data = await run(body(feature("Novel Hazard", "Catastrophic")))
    assert data["alerts"][0]["level"] == "warn"


@pytest.mark.asyncio
async def test_sorted_worst_and_soonest_first():
    data = await run(
        body(
            feature("Wind Advisory", "Moderate", urgency="Expected"),
            feature("Flood Warning", "Severe", urgency="Future"),
            feature("Tornado Warning", "Severe", urgency="Immediate"),
        )
    )
    assert [a["event"] for a in data["alerts"]] == [
        "Tornado Warning",  # severe + immediate
        "Flood Warning",  # severe + future
        "Wind Advisory",  # moderate
    ]


@pytest.mark.asyncio
async def test_a_tornado_warning_outranks_a_thunderstorm_warning():
    """Colour collapses Extreme and Severe together. Order must not.

    Found by looking at a rendered panel, not by a test: both mapped to
    `critical`, both were Immediate, so the tie fell through to alphabetical and
    put "Severe Thunderstorm Warning" above "Tornado Warning". On a panel that
    shows the first six of many during an outbreak, that is the tornado warning
    below the fold.
    """
    data = await run(
        body(
            feature("Severe Thunderstorm Warning", "Severe"),
            feature("Tornado Warning", "Extreme"),
        )
    )
    assert [a["event"] for a in data["alerts"]] == [
        "Tornado Warning",
        "Severe Thunderstorm Warning",
    ]
    # Still the same colour -- the ramp only has three, and both mean red.
    assert {a["level"] for a in data["alerts"]} == {"critical"}


@pytest.mark.asyncio
async def test_an_unknown_severity_sorts_near_the_top_not_the_bottom():
    """A category NWS adds later must land where somebody notices it."""
    data = await run(
        body(
            feature("Wind Advisory", "Moderate"),
            feature("Novel Hazard", "Catastrophic"),
            feature("Small Craft Advisory", "Minor"),
        )
    )
    assert data["alerts"][0]["event"] == "Novel Hazard"


@pytest.mark.asyncio
async def test_ordering_is_stable_across_viewers():
    """Two dashboards on the same LAN must not disagree about the order."""
    same = body(
        feature("Beta Warning", "Severe"),
        feature("Alpha Warning", "Severe"),
    )
    first = await run(same)
    second = await run(same)
    assert [a["event"] for a in first["alerts"]] == [a["event"] for a in second["alerts"]]
    assert first["alerts"][0]["event"] == "Alpha Warning"  # tie broken by name


@pytest.mark.asyncio
async def test_counts_before_truncating():
    """"12 of 60" has to be honest about what was dropped."""
    many = body(*[feature(f"Event {i:03d}", "Moderate") for i in range(MAX_ALERTS + 15)])
    data = await run(many)
    assert data["count"] == MAX_ALERTS + 15
    assert len(data["alerts"]) == MAX_ALERTS
    assert data["truncated"] is True
    # The rollup counts everything in force, not just what survived the cut.
    assert sum(e["count"] for e in data["by_event"]) == MAX_ALERTS + 15


@pytest.mark.asyncio
async def test_by_event_rolls_up_duplicates():
    data = await run(
        body(
            feature("Flood Warning", "Severe"),
            feature("Flood Warning", "Severe"),
            feature("Wind Advisory", "Moderate"),
        )
    )
    assert data["by_event"][0] == {"event": "Flood Warning", "count": 2}


@pytest.mark.asyncio
async def test_long_text_is_capped():
    data = await run(body(feature("Flood Warning", "Severe", description="x" * 5000)))
    assert len(data["alerts"][0]["description"]) <= 500


@pytest.mark.asyncio
async def test_whitespace_collapsed():
    alert = feature("Flood Warning", "Severe", instruction="Move  to\n\nhigh ground")
    data = await run(body(alert))
    assert data["alerts"][0]["instruction"] == "Move to high ground"


@pytest.mark.asyncio
async def test_missing_fields_do_not_crash():
    import json

    data = await run(json.dumps({"features": [{"properties": {}}, {}, "nonsense", None]}))
    assert data["count"] == 1  # only the one real properties object
    assert data["alerts"][0]["event"] == "Alert"


@pytest.mark.asyncio
async def test_not_json_is_a_fetch_error():
    with pytest.raises(FetchError):
        await run("<html>maintenance</html>")


@pytest.mark.asyncio
async def test_no_features_array_is_a_fetch_error():
    with pytest.raises(FetchError):
        await run('{"type": "FeatureCollection"}')


def test_registered_by_kind():
    assert get_source("nws_alerts").kind == "nws_alerts"


# --- imagery config -------------------------------------------------------
def tile(**overrides):
    entry = {
        "id": "radar",
        "name": "Local radar",
        "url": "https://radar.weather.gov/ridge/standard/KFTG_loop.gif",
        "group": "radar",
        "refresh": 300,
    }
    entry.update(overrides)
    return entry


def test_imagery_parses(tmp_path):
    config = parse_config(base_cfg(imagery=[tile()]), base_dir=tmp_path)
    assert config.imagery[0].host == "radar.weather.gov"
    assert config.imagery[0].cache_bust is True


def test_imagery_requires_https(tmp_path):
    with pytest.raises(ConfigError, match="must be https"):
        parse_config(
            base_cfg(imagery=[tile(url="http://radar.weather.gov/x.gif")]), base_dir=tmp_path
        )


def test_imagery_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config(base_cfg(imagery=[tile(), tile()]), base_dir=tmp_path)


def test_imagery_enforces_a_refresh_floor(tmp_path):
    """Every open dashboard re-requests these; 5s would be abuse."""
    with pytest.raises(ConfigError, match="below the"):
        parse_config(base_cfg(imagery=[tile(refresh=5)]), base_dir=tmp_path)


def test_imagery_rejects_a_javascript_link(tmp_path):
    with pytest.raises(ConfigError, match="link must be"):
        parse_config(base_cfg(imagery=[tile(link="javascript:alert(1)")]), base_dir=tmp_path)


def test_imagery_id_must_be_filename_safe(tmp_path):
    with pytest.raises(ConfigError, match="alphanumeric"):
        parse_config(base_cfg(imagery=[tile(id="../../etc/passwd")]), base_dir=tmp_path)


# --- the policy the imagery config drives ---------------------------------
def test_csp_hosts_derived_from_tiles(tmp_path):
    """Adding a tile must open the CSP without a second edit.

    This is the footgun the derivation exists to remove: a tile plus a
    forgotten [embeds] entry used to give a blank square and a console message.
    """
    config = parse_config(base_cfg(imagery=[tile()]), base_dir=tmp_path)
    assert "radar.weather.gov" in config.csp_hosts()
    assert "https://radar.weather.gov" in build_csp(config.embed_hosts, config.csp_hosts())


def test_imagery_host_reaches_img_src_only(tmp_path):
    """An <img> cannot run script. A frame from the same host can.

    Granting frame-src because the operator wanted a picture would hand out a
    capability nobody asked for, so imagery hosts must not appear there.
    """
    config = parse_config(base_cfg(imagery=[tile()]), base_dir=tmp_path)
    policy = build_csp(config.embed_hosts, config.csp_hosts())
    directives = dict(
        (part.split(" ", 1) + [""])[:2] for part in (d.strip() for d in policy.split(";"))
    )
    assert "https://radar.weather.gov" in directives["img-src"]
    assert directives["frame-src"] == "'none'"


def test_an_embed_host_still_reaches_both(tmp_path):
    config = parse_config(
        base_cfg(embeds={"allow_hosts": ["www.hamqsl.com"]}, imagery=[tile()]), base_dir=tmp_path
    )
    policy = build_csp(config.embed_hosts, config.csp_hosts())
    assert "https://www.hamqsl.com" in policy.split("frame-src")[1]
    assert "https://radar.weather.gov" not in policy.split("frame-src")[1]


def test_imagery_does_not_widen_the_collector_allowlist(tmp_path):
    """The browser fetches these. This process must not gain reach to them.

    Two lists that are almost the same is not an oversight -- the collector's is
    smaller on purpose, and a refactor that "tidies" them together is a
    regression.
    """
    config = parse_config(base_cfg(imagery=[tile()]), base_dir=tmp_path)
    allowed, _ = config.allowlist()
    assert "radar.weather.gov" not in allowed
    assert "radar.weather.gov" in config.csp_hosts()


def test_imagery_tile_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ImageryTile(id="a", name="a", url="https://x.example/y.gif").url = "https://z.example"

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The Prometheus endpoint: the format, the bounds, and the off switch.

Three things need proving, and only the first is obvious.

**The format.** Prometheus rejects a malformed exposition with an error that
does not say what was malformed, so the escaping, the HELP/TYPE grouping and the
number formatting are checked here rather than found in a scrape log.

**The bounds.** A label whose values are unbounded is the classic way to ruin a
time-series database: one series per callsign heard, kept forever, growing after
the operator goes to bed. Nothing here may be labelled by callsign, and there is
a hard series cap because a bound that is only argued for is one a future source
quietly breaks.

**The off switch.** The endpoint is off by default and must 404 rather than 403
when it is off -- an endpoint that is switched off should not announce that it
exists.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from hammunition_hill.config import Config, MetricsConfig, ServerConfig
from hammunition_hill.metrics import (
    CONTENT_TYPE,
    MAX_SERIES,
    Registry,
    _escape_label,
    _format_value,
    collect,
    render,
)
from hammunition_hill.server import build_server

NOW = datetime(2026, 3, 20, 18, 30, tzinfo=UTC)


def write(data_dir, source_id, data, *, fetched_at=None, stale=300, error=None):
    stamp = (fetched_at or NOW).isoformat().replace("+00:00", "Z")
    (data_dir / f"{source_id}.json").write_text(
        json.dumps(
            {
                "source": source_id,
                "fetched_at": stamp,
                "stale_after_seconds": stale,
                "error": error,
                "data": data,
            }
        )
    )


# --- the exposition format --------------------------------------------------


def test_a_family_carries_help_and_type_before_its_samples():
    """The format requires it and a scraper may reject a file where they are
    interleaved, which is why samples are grouped rather than appended."""
    registry = Registry()
    registry.gauge("hamhill_test", "A help string.", 1, {"a": "x"})
    registry.gauge("hamhill_test", "A help string.", 2, {"a": "y"})
    lines = registry.render().splitlines()
    assert lines[0] == "# HELP hamhill_test A help string."
    assert lines[1] == "# TYPE hamhill_test gauge"
    assert lines[2].startswith("hamhill_test{a=")
    assert lines[3].startswith("hamhill_test{a=")


def test_families_are_not_interleaved():
    """Samples of one family must not appear after another family has started.

    Structural rather than incidental: samples accumulate in a dict keyed by
    family, so the grouping holds however they arrive. Asserted anyway, because
    a future change to a flat list of samples would break the format in a way
    Prometheus reports as an unhelpfully generic parse error.
    """
    registry = Registry()
    registry.gauge("hamhill_a", "A.", 1)
    registry.gauge("hamhill_b", "B.", 1)
    registry.gauge("hamhill_a", "A.", 2, {"x": "1"})
    text = registry.render()
    first_b = text.index("# TYPE hamhill_b")
    assert text.rindex("hamhill_a") < first_b, "a sample of hamhill_a appears after hamhill_b"


def test_families_come_out_in_a_stable_order():
    """Not required by the format, and worth having: a scrape you can diff.

    This is what sorting the families buys, which the grouping test above does
    not measure -- the dict would group them just as well in insertion order.
    """
    registry = Registry()
    for name in ("hamhill_zulu", "hamhill_alpha", "hamhill_mike"):
        registry.gauge(name, "H.", 1)
    families = [
        line.split()[2] for line in registry.render().splitlines() if line.startswith("# TYPE")
    ]
    assert families == sorted(families), families


def test_labels_are_sorted_so_the_output_is_stable():
    """Not required by the format, but a diffable scrape is worth having and an
    unstable order makes every comparison noise."""
    registry = Registry()
    registry.gauge("hamhill_test", "H.", 1, {"z": "1", "a": "2", "m": "3"})
    assert 'hamhill_test{a="2",m="3",z="1"} 1' in registry.render()


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("plain", "plain"),
        ('has "quotes"', 'has \\"quotes\\"'),
        ("back\\slash", "back\\\\slash"),
        ("two\nlines", "two\\nlines"),
        ('\\"', '\\\\\\"'),
    ],
)
def test_label_values_are_escaped(raw, escaped):
    """Backslash first. Escaping the quote first would then have its own
    backslash escaped by the next pass, doubling it."""
    assert _escape_label(raw) == escaped


def test_an_escaped_label_survives_a_round_trip_through_the_format():
    registry = Registry()
    registry.gauge("hamhill_test", "H.", 1, {"source": 'a "weird" \\ name'})
    line = registry.render().splitlines()[2]
    assert line.count('"') % 2 == 0, "unbalanced quotes would break the parser"
    assert re.match(r'^hamhill_test\{source="(?:[^"\\]|\\.)*"\} 1$', line), line


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1, "1"),
        (1.0, "1"),
        (0, "0"),
        (-3, "-3"),
        (1.5, "1.5"),
        (float("nan"), "NaN"),
        (float("inf"), "+Inf"),
        (float("-inf"), "-Inf"),
    ],
)
def test_values_are_formatted_the_way_prometheus_reads_them(value, text):
    assert _format_value(value) == text


def test_a_whole_number_is_not_rendered_in_scientific_notation():
    """A K index of 3.0 printed as 3e+00 parses, and reads like a bug."""
    assert _format_value(3.0) == "3"
    assert "e" not in _format_value(142.0)


def test_the_output_ends_with_a_newline():
    """Prometheus is tolerant of a missing one; nothing else in a pipeline is."""
    assert render_empty().endswith("\n")


def render_empty() -> str:
    return Registry().render()


def test_an_invalid_metric_name_is_refused_rather_than_emitted():
    """An invalid name makes the whole scrape fail, so it fails here instead."""
    registry = Registry()
    for name in ("has-dash", "1leading", "has space", ""):
        with pytest.raises(ValueError, match="invalid metric name"):
            registry.gauge(name, "H.", 1)


def test_a_missing_value_is_omitted_rather_than_zeroed():
    """A source that has never reported is not a source reporting zero, and a
    graph that cannot tell them apart will be read wrongly."""
    registry = Registry()
    registry.gauge("hamhill_test", "H.", None)
    assert "hamhill_test" not in registry.render()


# --- cardinality ------------------------------------------------------------


def test_the_series_cap_truncates_and_says_so():
    """A bound that is only argued for is a bound a future source breaks."""
    registry = Registry(max_series=10)
    for index in range(500):
        registry.gauge("hamhill_test", "H.", 1, {"n": str(index)})
    text = registry.render()
    assert text.count("hamhill_test{") == 10
    assert "series cap" in text
    assert registry.truncated


def test_a_scrape_under_the_cap_says_nothing_about_it():
    registry = Registry(max_series=10)
    registry.gauge("hamhill_test", "H.", 1)
    assert "series cap" not in registry.render()
    assert not registry.truncated


def test_no_metric_is_labelled_by_callsign(tmp_path):
    """The unbounded label. One series per station heard, kept forever, growing
    after the operator has gone to bed."""
    write(
        tmp_path,
        "rbn",
        {
            "activity": [
                {
                    "band": "20m",
                    "mode": "CW",
                    "spots": 40,
                    "calls": 12,
                    "spotters": 9,
                    "best_snr": 23,
                }
            ],
            "heard_me": [{"snr_db": 17, "call": "N0CALL"}],
            "watching": ["N0CALL"],
        },
    )
    text = render(tmp_path, ("rbn",), now=NOW)
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        assert "call=" not in line, line
        assert "callsign=" not in line, line
        assert "station=" not in line, line


def test_a_busy_network_does_not_grow_the_scrape(tmp_path):
    """The same claim the RBN tally makes, checked from the other end."""
    bands = ["160m", "80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"]
    modes = ["CW", "FT8", "FT4", "RTTY"]
    activity = [
        {"band": band, "mode": mode, "spots": 999, "calls": 400, "spotters": 300, "best_snr": 30}
        for band in bands
        for mode in modes
    ]
    write(tmp_path, "rbn", {"activity": activity, "heard_me": [], "watching": []})
    lines = [line for line in render(tmp_path, ("rbn",), now=NOW).splitlines() if line[:1] != "#"]
    assert len(lines) < 200, f"{len(lines)} series from forty band/mode buckets"


def test_the_default_cap_is_high_enough_to_be_a_backstop_not_a_limit():
    """It should never be reached in normal operation, or it is not a backstop."""
    assert MAX_SERIES >= 1000


# --- what it reports --------------------------------------------------------


def test_up_is_always_present(tmp_path):
    """So a scrape failure is distinguishable from a collector with nothing to say."""
    assert "hamhill_up 1" in render(tmp_path, (), now=NOW)


def test_a_source_that_never_wrote_reports_absent_rather_than_vanishing(tmp_path):
    text = render(tmp_path, ("kindex",), now=NOW)
    assert 'hamhill_snapshot_present{source="kindex"} 0' in text
    assert "hamhill_snapshot_age_seconds" not in text


def test_snapshot_age_is_measured_from_the_stamp(tmp_path):
    write(tmp_path, "kindex", {"kp": 3}, fetched_at=NOW - timedelta(seconds=90))
    text = render(tmp_path, ("kindex",), now=NOW)
    assert 'hamhill_snapshot_age_seconds{source="kindex"} 90' in text


def test_a_failed_cycle_is_reported(tmp_path):
    write(tmp_path, "kindex", None, error="HTTP 503")
    text = render(tmp_path, ("kindex",), now=NOW)
    assert 'hamhill_snapshot_failed{source="kindex"} 1' in text


def test_staleness_compares_age_against_the_snapshot_own_window(tmp_path):
    write(tmp_path, "fresh", {"kp": 1}, fetched_at=NOW - timedelta(seconds=10), stale=300)
    write(tmp_path, "old", {"kp": 1}, fetched_at=NOW - timedelta(seconds=900), stale=300)
    text = render(tmp_path, ("fresh", "old"), now=NOW)
    assert 'hamhill_snapshot_stale{source="fresh"} 0' in text
    assert 'hamhill_snapshot_stale{source="old"} 1' in text


def test_a_window_of_zero_means_the_data_does_not_age(tmp_path):
    """The reference tables are written once at startup and never go stale --
    the same rule the panel host follows, and it was a real bug there."""
    write(tmp_path, "morse", {"letters": []}, fetched_at=NOW - timedelta(days=30), stale=0)
    assert 'hamhill_snapshot_stale{source="morse"} 0' in render(tmp_path, ("morse",), now=NOW)


def test_the_numbers_worth_trending_are_exported(tmp_path):
    write(tmp_path, "solarflux", {"flux": 142.3})
    write(tmp_path, "kindex", {"kp": 3})
    write(tmp_path, "propagation", {"muf_mhz": 21.4, "luf_mhz": 4.2, "absorption_db": 1.7})
    text = render(tmp_path, ("solarflux", "kindex", "propagation"), now=NOW)
    assert "hamhill_solar_flux 142.3" in text
    assert "hamhill_k_index 3" in text
    assert "hamhill_muf_mhz 21.4" in text
    assert "hamhill_luf_mhz 4.2" in text
    assert "hamhill_absorption_db 1.7" in text


def test_a_number_that_arrived_as_a_string_is_still_a_number(tmp_path):
    """Upstreams disagree about whether a number is a number."""
    write(tmp_path, "solarflux", {"flux": "142"})
    assert "hamhill_solar_flux 142" in render(tmp_path, ("solarflux",), now=NOW)


@pytest.mark.parametrize("junk", [None, "", "n/a", "None", [], {}, True])
def test_a_field_that_is_not_a_number_is_omitted(tmp_path, junk):
    """True is in this list on purpose: bool is a subclass of int, so a flag
    would otherwise be exported as a solar flux of 1."""
    write(tmp_path, "solarflux", {"flux": junk})
    assert "hamhill_solar_flux" not in render(tmp_path, ("solarflux",), now=NOW)


def test_band_activity_is_labelled_by_band_and_mode(tmp_path):
    write(
        tmp_path,
        "rbn",
        {
            "activity": [
                {
                    "band": "20m",
                    "mode": "CW",
                    "spots": 40,
                    "calls": 12,
                    "spotters": 9,
                    "best_snr": 23,
                }
            ],
            "heard_me": [],
            "watching": [],
        },
    )
    text = render(tmp_path, ("rbn",), now=NOW)
    assert 'hamhill_rbn_spots{band="20m",mode="CW"} 40' in text
    assert 'hamhill_rbn_stations{band="20m",mode="CW"} 12' in text
    assert 'hamhill_rbn_skimmers{band="20m",mode="CW"} 9' in text
    assert 'hamhill_rbn_best_snr_db{band="20m",mode="CW"} 23' in text


def test_the_best_report_of_my_own_signal_is_exported(tmp_path):
    """The number worth alerting on: it fell off a cliff means something."""
    write(
        tmp_path,
        "rbn",
        {
            "activity": [],
            "heard_me": [{"snr_db": 8}, {"snr_db": 27}, {"snr_db": 14}],
            "watching": ["N0CALL"],
        },
    )
    text = render(tmp_path, ("rbn",), now=NOW)
    assert "hamhill_rbn_reports_of_me 3" in text
    assert "hamhill_rbn_best_snr_of_me_db 27" in text


def test_satellite_metrics_report_unavailable_rather_than_nothing(tmp_path):
    write(tmp_path, "satellites", {"available": False, "reason": "no elements yet"})
    text = render(tmp_path, ("satellites",), now=NOW)
    assert "hamhill_satellite_prediction_available 0" in text
    assert "hamhill_satellite_passes" not in text


def test_seconds_to_the_next_pass_is_the_soonest_future_one(tmp_path):
    """Past passes are in the list too, and the minimum over all of them would
    be a negative number that reads as "it already happened"."""
    write(
        tmp_path,
        "satellites",
        {
            "available": True,
            "tracked": 12,
            "passes": [
                {"rise": (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")},
                {"rise": (NOW + timedelta(minutes=40)).isoformat().replace("+00:00", "Z")},
                {"rise": (NOW + timedelta(minutes=12)).isoformat().replace("+00:00", "Z")},
            ],
        },
    )
    text = render(tmp_path, ("satellites",), now=NOW)
    assert "hamhill_satellite_prediction_available 1" in text
    assert "hamhill_satellites_tracked 12" in text
    assert "hamhill_next_satellite_pass_seconds 720" in text


def test_a_corrupt_snapshot_does_not_take_the_scrape_down(tmp_path):
    """One bad file should cost that source, not the endpoint."""
    (tmp_path / "kindex.json").write_text("{ not json")
    write(tmp_path, "solarflux", {"flux": 100})
    text = render(tmp_path, ("kindex", "solarflux"), now=NOW)
    assert "hamhill_solar_flux 100" in text
    assert "hamhill_up 1" in text


def test_an_unparseable_timestamp_omits_the_age_rather_than_guessing(tmp_path):
    (tmp_path / "kindex.json").write_text(
        json.dumps({"fetched_at": "yesterday", "stale_after_seconds": 300, "data": {}})
    )
    text = render(tmp_path, ("kindex",), now=NOW)
    assert 'hamhill_snapshot_present{source="kindex"} 1' in text
    assert "hamhill_snapshot_age_seconds" not in text


def test_collect_returns_a_registry_a_caller_can_inspect(tmp_path):
    assert isinstance(collect(tmp_path, (), now=NOW), Registry)


# --- the endpoint -----------------------------------------------------------


@pytest.fixture
def live(tmp_path, request):
    enabled = getattr(request, "param", True)
    web = tmp_path / "web"
    data = tmp_path / "data"
    web.mkdir()
    data.mkdir()
    (web / "index.html").write_text("<!doctype html><title>hh</title>")
    write(data, "solarflux", {"flux": 142})

    config = Config(
        server=ServerConfig(host="127.0.0.1", port=0),
        sources=(),
        data_dir=data,
        web_dir=web,
        metrics=MetricsConfig(enabled=enabled),
    )
    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()


def test_the_endpoint_serves_the_exposition_format(live):
    with urllib.request.urlopen(f"{live}/metrics", timeout=5) as response:  # noqa: S310
        assert response.status == 200
        assert response.headers["Content-Type"] == CONTENT_TYPE
        body = response.read().decode()
    assert "hamhill_up 1" in body
    assert "hamhill_solar_flux 142" in body


def test_the_endpoint_is_never_cached(live):
    """A pinned scrape would show a dead collector as healthy indefinitely."""
    with urllib.request.urlopen(f"{live}/metrics", timeout=5) as response:  # noqa: S310
        assert response.headers["Cache-Control"] == "no-store"


def test_the_security_headers_still_apply(live):
    with urllib.request.urlopen(f"{live}/metrics", timeout=5) as response:  # noqa: S310
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize("live", [False], indirect=True)
def test_when_disabled_it_is_a_404_and_not_a_403(live):
    """An endpoint that is switched off should not announce that it exists."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{live}/metrics", timeout=5)  # noqa: S310
    assert caught.value.code == 404


@pytest.mark.parametrize("live", [False], indirect=True)
def test_disabled_is_the_default(live):
    """Config with no [metrics] table means off, so shipping the code does not
    ship the endpoint."""
    assert MetricsConfig().enabled is False


def test_the_dashboard_still_works_alongside_it(live):
    with urllib.request.urlopen(f"{live}/", timeout=5) as response:  # noqa: S310
        assert b"<title>hh</title>" in response.read()


def test_a_query_string_does_not_route_around_the_endpoint(live):
    with urllib.request.urlopen(f"{live}/metrics?x=1", timeout=5) as response:  # noqa: S310
        assert "hamhill_up 1" in response.read().decode()


def test_a_file_called_metrics_is_not_reachable_through_the_route(live, tmp_path):
    """The route is checked before the file lookup, so a file of that name in
    web/ cannot be served in its place -- nor the endpoint hidden by one."""
    (tmp_path / "web" / "metrics").write_text("this must never be served")
    with urllib.request.urlopen(f"{live}/metrics", timeout=5) as response:  # noqa: S310
        assert b"must never be served" not in response.read()


def test_the_endpoint_rejects_writes(live):
    request = urllib.request.Request(f"{live}/metrics", method="DELETE")  # noqa: S310
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=5)  # noqa: S310
    assert caught.value.code == 405


def test_a_head_request_matches_the_get(live):
    """Without its own route the parent's file lookup answers, so HEAD would
    404 on a path where GET returns 200 -- the sort of inconsistency a proxy or
    a health check trips over long after anyone remembers why."""
    request = urllib.request.Request(f"{live}/metrics", method="HEAD")  # noqa: S310
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
        assert response.status == 200
        assert response.headers["Content-Type"] == CONTENT_TYPE
        assert int(response.headers["Content-Length"]) > 0
        assert response.read() == b""


def test_no_rbn_source_means_no_rbn_metrics(tmp_path):
    """Zero reports of your callsign would be a claim about the bands. With no
    source configured it is a claim about the config, and the rule everywhere
    else here is that missing is not zero."""
    text = render(tmp_path, (), now=NOW)
    assert "hamhill_rbn" not in text


def test_no_satellite_source_means_no_satellite_metrics(tmp_path):
    text = render(tmp_path, (), now=NOW)
    assert "hamhill_satellite" not in text

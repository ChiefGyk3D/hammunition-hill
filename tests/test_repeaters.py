# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The repeaters panel: what the collector stores, and who may be served it.

Three things are worth proving, and the third is the one that is easy to lose.

**The numbers.** Distance and bearing come from the station's grid square
centre. The two pairs below were worked out with a different formula than
``geo.py`` uses (spherical law of cosines for the distance, atan2 for the
bearing, R = 6371.0088 km), so a shared mistake in ``geo.py`` cannot satisfy
its own test.

**The empty state.** No engine, a failing engine, a document from a different
engine, and no layers are four different problems, and each one says what to
run.

**The personal-use rule.** RepeaterBook's terms keep its rows on this machine
(Hammunition D-081). Hill's server can be bound to a LAN address, so the
snapshot on disk may hold those rows while the response to another host must
not. The test sends a request as a non-loopback client and fails if a
``personal_use`` row, or anything naming RepeaterBook, comes back.
"""

from __future__ import annotations

import copy
import http.client
import json
import stat
import threading
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
import repeaters_docs as docs

from hammunition_hill import repeaters
from hammunition_hill.config import Config, ServerConfig
from hammunition_hill.server import DashboardHandler, build_server, is_own_machine
from hammunition_hill.snapshot import read_snapshot


def build(listing=None, station=None, **kwargs):
    return repeaters.build_data(
        docs.listing_document() if listing is None else listing,
        docs.station_document() if station is None else station,
        **kwargs,
    )


def row(data, callsign):
    return next(r for r in data["rows"] if r["callsign"] == callsign)


# --- distance and bearing ---------------------------------------------------
def test_the_station_centre_is_the_one_worked_out_by_hand():
    """FN31pr: field F/N -> -80/+40, square 3/1 -> -74/41, subsquare p/r adds
    15/24 * 2 and 17/24 degrees, and the centre adds half a subsquare."""
    data = build()
    assert data["station"]["lat"] == pytest.approx(41.7291667, abs=1e-6)
    assert data["station"]["lon"] == pytest.approx(-72.7083333, abs=1e-6)
    assert data["grid"] == "FN31pr"


def test_boston_from_the_grid_centre():
    """41.72917,-72.70833 to 42.3601,-71.0589.

    Spherical law of cosines: 153.206 km. atan2 bearing: 62.197 degrees.
    """
    boston = row(build(), "W1AAA")
    assert boston["km"] == pytest.approx(153.2, abs=0.1)
    assert boston["bearing"] == pytest.approx(62.2, abs=0.1)


def test_new_york_from_the_grid_centre():
    """The same point to 40.7128,-74.0060: 156.687 km at 224.271 degrees."""
    new_york = row(build(), "W1BBB")
    assert new_york["km"] == pytest.approx(156.7, abs=0.1)
    assert new_york["bearing"] == pytest.approx(224.3, abs=0.1)


def test_rows_are_nearest_first():
    kms = [r["km"] for r in build()["rows"]]
    assert kms == sorted(kms)
    assert build()["rows"][0]["callsign"] == "W1CCC"  # Hartford, ~5 km


def test_the_band_comes_from_the_output_frequency():
    data = build()
    assert row(data, "W1AAA")["band"] == "2m"
    assert row(data, "W1CCC")["band"] == "2m"
    assert row(data, "W1DDD")["band"] == "70cm"
    assert repeaters.band_for_hz(0) is None
    assert repeaters.band_for_hz(7_100_000) == "40m"


def test_bands_are_listed_low_to_high_for_the_filter_row():
    assert build()["bands"] == ["2m", "70cm"]


def test_no_grid_in_the_engine_falls_back_to_hills_own_station():
    data = build(station=docs.station_document(grid=None), fallback_latlon=(41.7292, -72.7083))
    assert data["grid"] is None
    assert row(data, "W1AAA")["km"] == pytest.approx(153.2, abs=0.2)


def test_no_grid_anywhere_leaves_distance_empty_and_says_why():
    data = build(station=docs.station_document(grid=None))
    assert row(data, "W1AAA")["km"] is None
    assert row(data, "W1AAA")["bearing"] is None
    assert "grid square" in data["distance_note"]
    assert data["available"] is True


def test_no_station_document_still_shows_the_rows():
    data = repeaters.build_data(docs.listing_document(), None)
    assert data["available"] is True
    assert len(data["rows"]) == 4
    assert row(data, "W1AAA")["km"] is None


# --- what is carried --------------------------------------------------------
def test_credits_layers_and_the_merge_count_are_carried():
    data = build()
    assert data["credits"] == [docs.OPEN_CREDIT, docs.REPEATERBOOK_CREDIT]
    assert [layer["id"] for layer in data["layers"]] == ["open-repeater", "repeaterbook"]
    assert data["merged"] == 1
    assert data["skipped"] == [{"layer": "osm", "reason": "a layer not present"}]
    assert data["has_personal_use"] is True


def test_the_also_sources_of_a_merged_row_are_carried():
    assert row(build(), "W1CCC")["also"] == ["repeaterbook-api"]


def test_a_row_with_no_personal_use_layer_present_says_so():
    listing = docs.listing_document()
    listing["layers"] = [listing["layers"][0]]
    listing["rows"] = [r for r in listing["rows"] if not r["personal_use"]]
    listing["credits"] = [docs.OPEN_CREDIT]
    assert build(listing)["has_personal_use"] is False


def test_only_what_the_panel_uses_is_stored():
    stored = set(row(build(), "W1AAA"))
    assert "notes" not in stored and "label" not in stored and "updated" not in stored
    assert {"callsign", "output_hz", "offset_hz", "tone", "mode", "place", "lat", "lon"} <= stored


def test_the_row_count_is_capped_and_the_cut_is_counted():
    listing = docs.listing_document()
    base = listing["rows"][0]
    listing["rows"] = [
        {**base, "callsign": f"W1X{i:03d}", "lat": 42.0 + i * 1e-4} for i in range(30)
    ]
    data = build(listing, max_rows=10)
    assert len(data["rows"]) == 10
    assert data["truncated"] == 20
    # The cut keeps the nearest, because that is what the panel is for.
    assert [r["km"] for r in data["rows"]] == sorted(r["km"] for r in data["rows"])


# --- the empty state --------------------------------------------------------
IMPORT = "hammunition maps repeaters import FILE"
FETCH = "hammunition maps repeaters fetch-repeaterbook --state CODE"


def collect(**kwargs):
    kwargs.setdefault("finder", lambda: "/usr/bin/hammunition")
    return repeaters.collect(**kwargs)


def test_no_engine_names_how_to_get_one_and_the_import_command():
    data = collect(finder=lambda: None)
    assert data["available"] is False
    assert "hammunition" in data["reason"]
    assert IMPORT in data["reason"] and FETCH in data["reason"]
    assert data["rows"] == []


def test_a_failing_engine_says_what_failed_and_still_names_the_import():
    def runner(exe, args):
        raise repeaters.EngineError("hammunition exited 2: something")

    data = collect(runner=runner)
    assert data["available"] is False
    assert "exited 2" in data["reason"]
    assert IMPORT in data["reason"]


def test_an_empty_directory_is_the_empty_state_not_an_error():
    def runner(exe, args):
        return docs.empty_listing() if "repeaters" in args else docs.station_document()

    data = collect(runner=runner)
    assert data["available"] is False
    assert IMPORT in data["reason"] and FETCH in data["reason"]
    assert "no repeater layers" in data["reason"]


def test_a_layer_that_could_not_be_read_is_reported_when_that_is_all_there_is():
    listing = docs.empty_listing()
    listing["skipped"] = [{"layer": "osm", "reason": "an unreadable rows file"}]

    def runner(exe, args):
        return listing if "repeaters" in args else docs.station_document()

    data = collect(runner=runner)
    assert data["available"] is False
    assert "osm" in data["reason"] and "unreadable" in data["reason"]


def test_a_document_of_another_kind_or_major_is_refused_by_name():
    wrong_kind = copy.deepcopy(docs.listing_document())
    wrong_kind["kind"] = "status"
    wrong_major = copy.deepcopy(docs.listing_document())
    wrong_major["schema"] = "hammunition/2"
    for bad in (wrong_kind, wrong_major):
        data = collect(runner=lambda exe, args, bad=bad: bad)
        assert data["available"] is False
        assert "repeaters-list" in data["reason"] or "schema" in data["reason"]


def test_a_failing_station_command_costs_only_the_distance():
    def runner(exe, args):
        if args[0] == "station":
            raise repeaters.EngineError("station: not readable")
        return docs.listing_document()

    data = collect(runner=runner)
    assert data["available"] is True
    assert row(data, "W1AAA")["km"] is None


def test_the_two_engine_commands_are_read_only_and_exactly_these():
    """The collector may run these two and nothing else (the brief's rule, and
    Hammunition's D-059: a front end reads, the operator's terminal changes)."""
    assert repeaters.LIST_ARGV == ("maps", "repeaters", "list", "--json")
    assert repeaters.STATION_ARGV == ("station", "show", "--json")
    banned = {"import", "remove", "set", "install", "uninstall", "apply", "unapply"}
    for argv in (repeaters.LIST_ARGV, repeaters.STATION_ARGV):
        assert not banned & set(argv)
        assert not any(word.startswith("fetch") for word in argv)


def test_collect_asks_the_engine_those_two_and_no_more():
    asked: list[tuple[str, ...]] = []

    def runner(exe, args):
        asked.append(tuple(args))
        return docs.listing_document() if args[0] == "maps" else docs.station_document()

    collect(runner=runner)
    assert sorted(asked) == sorted([repeaters.LIST_ARGV, repeaters.STATION_ARGV])


def fake_engine(tmp_path: Path, body: str, name: str = "hammunition") -> str:
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_run_engine_parses_one_json_document(tmp_path):
    exe = fake_engine(tmp_path, f"cat <<'EOF'\n{json.dumps(docs.station_document())}\nEOF\n")
    assert repeaters.run_engine(exe, ("station", "show", "--json"))["kind"] == "station"


def test_run_engine_refuses_garbage_a_nonzero_exit_and_a_hang(tmp_path):
    with pytest.raises(repeaters.EngineError, match="JSON"):
        repeaters.run_engine(fake_engine(tmp_path, "echo not json\n"), ("x",))
    with pytest.raises(repeaters.EngineError, match="exited 3"):
        repeaters.run_engine(fake_engine(tmp_path, "echo nope >&2\nexit 3\n", "b"), ("x",))
    with pytest.raises(repeaters.EngineError, match="did not answer"):
        repeaters.run_engine(fake_engine(tmp_path, "sleep 5\n", "c"), ("x",), timeout=0.2)
    with pytest.raises(repeaters.EngineError, match="start"):
        repeaters.run_engine(str(tmp_path / "missing"), ("x",))


def test_run_engine_does_not_pass_the_callsign_to_anything_it_logs(tmp_path, caplog):
    exe = fake_engine(tmp_path, 'echo \'{"callsign": "N0CALL"}\' >&2\nexit 1\n')
    with pytest.raises(repeaters.EngineError) as caught:
        repeaters.run_engine(exe, ("station", "show", "--json"))
    assert "N0CALL" not in str(caught.value)


# --- the personal-use rule --------------------------------------------------
def public_json(data) -> str:
    return json.dumps(repeaters.public_data(data)).lower()


def test_the_public_view_drops_every_personal_use_row_and_says_how_many():
    public = repeaters.public_data(build())
    assert [r["callsign"] for r in public["rows"]] == ["W1DDD", "W1AAA"]
    assert public["withheld"] == 2
    assert all(not r["personal_use"] for r in public["rows"])


def test_the_public_view_names_nothing_of_repeaterbook():
    text = public_json(build())
    assert "repeaterbook" not in text
    assert [layer["id"] for layer in repeaters.public_data(build())["layers"]] == ["open-repeater"]
    assert repeaters.public_data(build())["credits"] == [docs.OPEN_CREDIT]


def test_the_public_view_is_a_copy_and_the_stored_data_is_untouched():
    data = build()
    before = json.dumps(data, sort_keys=True)
    repeaters.public_data(data)
    assert json.dumps(data, sort_keys=True) == before


def test_a_row_is_withheld_even_if_only_its_also_list_names_repeaterbook():
    """The engine sets personal_use for that; this holds if a future engine
    forgets, because the flag is not the only thing the filter reads."""
    data = build()
    victim = row(data, "W1AAA")
    victim["personal_use"] = False
    victim["also"] = ["repeaterbook-api"]
    public = repeaters.public_data(data)
    assert "W1AAA" not in [r["callsign"] for r in public["rows"]]
    assert "repeaterbook" not in json.dumps(public).lower()


def test_a_snapshot_that_is_not_ours_is_not_passed_through_unfiltered():
    """Garbage in the file must never become 'serve it as is'."""
    assert repeaters.public_data({"available": True, "rows": "oops"})["rows"] == []
    assert repeaters.public_data({})["rows"] == []


class Peer(Message):
    pass


def headers(**fields: str) -> Message:
    msg = Message()
    for key, value in fields.items():
        msg[key.replace("_", "-")] = value
    return msg


@pytest.mark.parametrize(
    "client,server,fields,expected",
    [
        ("127.0.0.1", "127.0.0.1", {}, True),
        ("::1", "::1", {}, True),
        ("::ffff:127.0.0.1", "127.0.0.1", {}, True),
        # This machine reaching itself by its LAN address is still this machine.
        ("192.0.2.10", "192.0.2.10", {}, True),
        # Another host on the LAN is not.
        ("192.0.2.77", "192.0.2.10", {}, False),
        ("198.51.100.5", "127.0.0.1", {}, False),
        # A reverse proxy on this machine makes every client look like
        # loopback; its forwarding headers say it is not this machine's own page.
        ("127.0.0.1", "127.0.0.1", {"X_Forwarded_For": "203.0.113.9"}, False),
        ("127.0.0.1", "127.0.0.1", {"Forwarded": "for=203.0.113.9"}, False),
        ("127.0.0.1", "127.0.0.1", {"X_Real_IP": "203.0.113.9"}, False),
        ("127.0.0.1", "127.0.0.1", {"Via": "1.1 proxy"}, False),
        ("not an address", "127.0.0.1", {}, False),
    ],
)
def test_who_counts_as_this_machine(client, server, fields, expected):
    assert is_own_machine(client, server, headers(**fields)) is expected


@pytest.fixture
def live(tmp_path):
    web = tmp_path / "web"
    data_dir = tmp_path / "data"
    web.mkdir()
    data_dir.mkdir()
    (web / "index.html").write_text("<!doctype html><title>hh</title>")
    from datetime import UTC, datetime

    from hammunition_hill.snapshot import Snapshot, write_snapshot

    write_snapshot(
        data_dir,
        Snapshot("repeaters", "repeaters", datetime.now(UTC), 1200, build()),
    )
    config = Config(
        server=ServerConfig(host="127.0.0.1", port=0),
        sources=(),
        data_dir=data_dir,
        web_dir=web,
    )
    server = build_server(config)
    state: dict[str, Any] = {"peer": None}

    inner = server.RequestHandlerClass

    class Handler(DashboardHandler):  # type: ignore[misc]
        def setup(self) -> None:
            super().setup()
            # The only honest way to be "another host" from a test that may
            # open sockets to loopback only.
            if state["peer"]:
                self.client_address = (state["peer"], 40000)

    def make(*args: Any, **kwargs: Any) -> Handler:
        return Handler(*args, config=config, csp="default-src 'none'", **kwargs)

    server.RequestHandlerClass = make  # type: ignore[assignment]
    del inner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield host, port, state, data_dir
    server.shutdown()
    server.server_close()


def fetch(live_server, path, method="GET", **hdrs):
    host, port = live_server[:2]
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path, headers=hdrs)
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, body


def rows_of(body: bytes) -> list[str]:
    return [r["callsign"] for r in json.loads(body)["data"]["rows"]]


def test_this_machine_gets_every_row(live):
    status, body = fetch(live, "/data/repeaters.json")
    assert status == 200
    assert rows_of(body) == ["W1CCC", "W1DDD", "W1AAA", "W1BBB"]


def test_another_host_never_receives_a_personal_use_row(live):
    live[2]["peer"] = "192.0.2.77"
    for method in ("GET", "HEAD"):
        status, body = fetch(live, "/data/repeaters.json", method)
        assert status == 200
        if method == "GET":
            assert rows_of(body) == ["W1DDD", "W1AAA"]
            assert b"repeaterbook" not in body.lower()
            assert b"W1BBB" not in body and b"W1CCC" not in body


def test_a_proxied_request_is_treated_as_another_host(live):
    status, body = fetch(live, "/data/repeaters.json", **{"X-Forwarded-For": "203.0.113.9"})
    assert status == 200
    assert rows_of(body) == ["W1DDD", "W1AAA"]
    assert b"repeaterbook" not in body.lower()


@pytest.mark.parametrize(
    "path",
    [
        "/data/Repeaters.json",
        "/data/REPEATERS.JSON",
        "/data/%72epeaters.json",
        "/data/./repeaters.json",
        "/data//repeaters.json",
        "/data/x/../repeaters.json",
        "/data/repeaters.json?x=1",
    ],
)
def test_no_spelling_of_the_path_reaches_the_unfiltered_file(live, path):
    live[2]["peer"] = "192.0.2.77"
    status, body = fetch(live, path)
    assert status in (200, 404)
    assert b"W1BBB" not in body and b"W1CCC" not in body and b"repeaterbook" not in body.lower()


def test_a_temp_file_from_an_atomic_write_is_never_served(live):
    data_dir = live[3]
    (data_dir / ".repeaters.abc123.tmp").write_text(json.dumps(build()))
    live[2]["peer"] = "192.0.2.77"
    status, _ = fetch(live, "/data/.repeaters.abc123.tmp")
    assert status == 404


def test_other_snapshots_are_served_untouched(live):
    live[2]["peer"] = "192.0.2.77"
    (live[3] / "solar.json").write_text(json.dumps({"data": {"flux": 142}}))
    status, body = fetch(live, "/data/solar.json")
    assert status == 200 and json.loads(body)["data"]["flux"] == 142


def test_a_snapshot_that_will_not_parse_is_not_served_raw(live):
    live[2]["peer"] = "192.0.2.77"
    (live[3] / "repeaters.json").write_text("{not json W1BBB repeaterbook")
    status, body = fetch(live, "/data/repeaters.json")
    assert status in (404, 500, 503)
    assert b"W1BBB" not in body


# --- nothing exports it -----------------------------------------------------
def test_metrics_never_carry_a_repeater(tmp_path):
    from datetime import UTC, datetime

    from hammunition_hill.metrics import render
    from hammunition_hill.snapshot import Snapshot, write_snapshot

    write_snapshot(tmp_path, Snapshot("repeaters", "repeaters", datetime.now(UTC), 1200, build()))
    text = render(tmp_path, ("repeaters",))
    for needle in ("W1AAA", "W1BBB", "W1CCC", "W1DDD", "repeaterbook"):
        assert needle.lower() not in text.lower()


def test_the_panel_offers_no_export_of_the_rows():
    """The only exports Hill has are a logbook's ADIF and the Frequencies
    panel's own list. This panel has none, and a test keeps it that way: a
    download link here would carry RepeaterBook's rows off the machine."""
    source = (Path(__file__).resolve().parents[1] / "web/panels/repeaters/panel.js").read_text()
    for forbidden in ("Blob(", "createObjectURL", "download", "navigator.clipboard"):
        assert forbidden not in source, f"the repeaters panel must not use {forbidden}"
    lib = (Path(__file__).resolve().parents[1] / "web/lib/repeaters.js").read_text()
    for forbidden in ("Blob(", "createObjectURL", "download", "navigator.clipboard"):
        assert forbidden not in lib


# --- the collector writes it ------------------------------------------------
def test_the_collector_publishes_the_snapshot_and_keeps_failure_honest(tmp_path):
    from hammunition_hill.collector import publish_repeaters

    config = Config(
        server=ServerConfig(host="127.0.0.1", port=0),
        sources=(),
        data_dir=tmp_path,
        web_dir=tmp_path,
    )
    publish_repeaters(
        config,
        collect_fn=lambda: build(),
    )
    snap = read_snapshot(tmp_path, "repeaters")
    assert snap["kind"] == "repeaters"
    assert snap["data"]["available"] is True
    assert snap["error"] is None
    assert snap["stale_after_seconds"] > 0

    def boom():
        raise RuntimeError("engine fell over")

    publish_repeaters(config, collect_fn=boom)
    snap = read_snapshot(tmp_path, "repeaters")
    assert "engine fell over" in snap["error"]
    # The last good rows stand under a failure; a stale panel is not a blank one.
    assert snap["data"]["available"] is True


def test_the_collector_without_an_engine_writes_the_empty_state(tmp_path):
    from hammunition_hill.collector import publish_repeaters

    config = Config(
        server=ServerConfig(host="127.0.0.1", port=0),
        sources=(),
        data_dir=tmp_path,
        web_dir=tmp_path,
    )
    publish_repeaters(config, collect_fn=lambda: repeaters.collect(finder=lambda: None))
    snap = read_snapshot(tmp_path, "repeaters")
    assert snap["data"]["available"] is False
    assert IMPORT in snap["data"]["reason"]


def test_repeaters_is_a_derived_snapshot_the_metrics_whitelist_knows():
    from hammunition_hill.server import DERIVED_SOURCES

    assert "repeaters" in DERIVED_SOURCES


# --- config -----------------------------------------------------------------
def test_the_repeaters_table_is_on_by_default_and_can_be_turned_off(tmp_path):
    from hammunition_hill.config import ConfigError, load_config

    def load(text: str):
        path = tmp_path / "c.toml"
        path.write_text(text)
        return load_config(path)

    assert load("").repeaters.enabled is True
    assert load("[repeaters]\nenabled = false\n").repeaters.enabled is False
    with pytest.raises(ConfigError, match="repeaters"):
        load("repeaters = 3\n")

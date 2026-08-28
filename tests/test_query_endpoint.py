# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""GET /lookup/<callsign>: the one route that takes a parameter.

The property that makes the endpoint acceptable is that it cannot cause an
outbound request -- it reads the ULS index and the collector's cache, both
already on disk. These tests drive a real bound server, because the interesting
failures (routing collisions with the static file server, HEAD/GET parity,
the off-by-default gate) live in the handler wiring, not in the lookup.
"""

import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from hammunition_hill.config import Config, LookupConfig, ServerConfig
from hammunition_hill.server import (
    _CALLSIGN,
    _LOOKUP_WINDOW_LIMIT,
    _lookup_rate_ok,
    _lookup_times,
    build_server,
)


def make_config(tmp_path, *, query_endpoint=True):
    web = tmp_path / "web"
    data = tmp_path / "data"
    web.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    (web / "index.html").write_text("<!doctype html><title>hh</title>")
    return Config(
        server=ServerConfig(host="127.0.0.1", port=0),
        sources=(),
        data_dir=data,
        web_dir=web,
        lookup=LookupConfig(providers=("fcc_uls",), query_endpoint=query_endpoint),
    )


@pytest.fixture
def live(tmp_path):
    config = make_config(tmp_path)

    db = tmp_path / "data" / "fcc_uls.sqlite3"
    connection = sqlite3.connect(db)
    connection.executescript(
        "CREATE TABLE licences (callsign TEXT PRIMARY KEY, name TEXT, operator_class TEXT,"
        " city TEXT, state TEXT, zip TEXT, status TEXT, granted TEXT, expires TEXT);"
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
    )
    connection.execute(
        "INSERT INTO licences VALUES ('W1AW','ARRL HQ','E','Newington','CT','06111','A','','')"
    )
    connection.commit()
    connection.close()

    (tmp_path / "data" / "lookup_cache.json").write_text(
        json.dumps(
            {
                "JA1XYZ": {
                    "cached_at": "2026-08-01T00:00:00+00:00",
                    "result": {"callsign": "JA1XYZ", "name": "Cached Op", "source": "qrz"},
                },
                "MISSED": {"cached_at": "2026-08-01T00:00:00+00:00", "result": None},
            }
        )
    )

    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    # The rate bucket is process-global; a previous test must not spend it.
    _lookup_times.clear()
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


def fetch(url, method="GET"):
    request = urllib.request.Request(url, method=method)  # noqa: S310 - fixed http scheme
    return urllib.request.urlopen(request, timeout=5)  # noqa: S310


def test_a_uls_hit_answers_from_the_index(live):
    with fetch(f"{live}/lookup/W1AW") as response:
        payload = json.load(response)
    assert payload["found"] is True
    assert payload["source"] == "fcc_uls"
    assert payload["record"]["name"] == "ARRL HQ"
    assert payload["record"]["operator_class"] == "E"


def test_lowercase_and_a_portable_suffix_still_resolve(live):
    """/P is the operator's, not the licence's: the base call is looked up."""
    with fetch(f"{live}/lookup/w1aw/p") as response:
        payload = json.load(response)
    assert payload["found"] is True
    assert payload["callsign"] == "W1AW/P"


def test_a_cached_provider_result_answers_when_uls_cannot(live):
    with fetch(f"{live}/lookup/JA1XYZ") as response:
        payload = json.load(response)
    assert payload["found"] is True
    assert payload["record"]["name"] == "Cached Op"


def test_a_recorded_miss_is_not_resurrected_as_a_hit(live):
    with fetch(f"{live}/lookup/MISSED") as response:
        payload = json.load(response)
    assert payload["found"] is False
    assert "record" not in payload


def test_an_unknown_callsign_is_a_clean_not_found(live):
    with fetch(f"{live}/lookup/K0NOPE") as response:
        payload = json.load(response)
    assert response.status == 200
    assert payload["found"] is False


@pytest.mark.parametrize("bad", ["", "a", "W1AW;DROP", "W1AW%20X", "A" * 20, "../secret"])
def test_garbage_is_rejected_before_it_touches_anything(live, bad):
    with pytest.raises(urllib.error.HTTPError) as caught:
        fetch(f"{live}/lookup/{bad}")
    assert caught.value.code in (400, 404)


def test_head_matches_get(live):
    """The metrics endpoint shipped with HEAD 404ing where GET was 200."""
    with fetch(f"{live}/lookup/W1AW", method="HEAD") as response:
        assert response.status == 200
        assert response.read() == b""


def test_switched_off_means_404_not_403(tmp_path):
    """An endpoint that is off should not announce that it exists."""
    config = make_config(tmp_path, query_endpoint=False)
    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            fetch(f"http://{host}:{port}/lookup/W1AW")
        assert caught.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_the_rate_limit_actually_limits(live):
    _lookup_times.clear()
    for _ in range(_LOOKUP_WINDOW_LIMIT):
        assert _lookup_rate_ok(now=100.0)
    assert not _lookup_rate_ok(now=100.0)
    # The window slides: a minute later the bucket has drained.
    assert _lookup_rate_ok(now=100.0 + 61.0)
    _lookup_times.clear()


def test_the_endpoint_returns_429_when_the_bucket_is_spent(live):
    _lookup_times.clear()
    try:
        for _ in range(_LOOKUP_WINDOW_LIMIT):
            assert _lookup_rate_ok()
        with pytest.raises(urllib.error.HTTPError) as caught:
            fetch(f"{live}/lookup/W1AW")
        assert caught.value.code == 429
        assert caught.value.headers.get("Retry-After")
    finally:
        _lookup_times.clear()


def test_the_callsign_gate_is_charset_and_length_not_format():
    """Real oddities pass; injection shapes do not."""
    for ok in ("W1AW", "GB100RSGB", "VP8/G4ABC", "N0CALL/QRP", "W1AW/P", "4U1UN"):
        assert _CALLSIGN.match(ok), ok
    for bad in ("", "W1", "w1aw", "W1AW X", "W1AW;", "W/1/AW", "/W1AW", "W1AW/", "A" * 15):
        assert not _CALLSIGN.match(bad), bad


def test_a_lookup_path_never_reaches_the_file_server(live):
    """/lookup/index.html must be a callsign miss, not the dashboard."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        fetch(f"{live}/lookup/index.html")
    assert caught.value.code == 400

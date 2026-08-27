# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The logbook, and the one write endpoint.

The endpoint tests matter most. It is the only place this server accepts input,
so the defences around it need to be proven rather than assumed -- and proven in
the negative, which is the direction that actually protects anyone.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from hammunition_hill.adif import parse_adif
from hammunition_hill.config import Config, ConfigError, LoggingConfig, ServerConfig, parse_config
from hammunition_hill.logbook import (
    Logbook,
    LogbookError,
    append,
    log_qso,
    normalize,
    recent,
    render_record,
)
from hammunition_hill.server import build_server

STATION = {"callsign": "N0CALL", "grid": "FN31pr"}


@pytest.fixture
def book(tmp_path):
    return Logbook(id="main", name="Home", path=tmp_path / "main.adi", primary=True)


# --- record shape --------------------------------------------------------
def test_a_record_is_length_prefixed_adif(book):
    fields = normalize({"CALL": "W1AW", "BAND": "20M", "MODE": "ssb"}, book, STATION)
    rendered = render_record(fields)
    assert "<CALL:4>W1AW" in rendered
    assert rendered.rstrip().endswith("<EOR>")


def test_lengths_are_bytes_not_characters(book):
    """ADIF counts octets, so a non-ASCII name must not be miscounted."""
    fields = normalize({"CALL": "W1AW", "NAME": "José"}, book, STATION)
    assert "<NAME:5>José" in render_record(fields)


def test_what_we_write_reads_back(book):
    log_qso(book, {"CALL": "W1AW", "BAND": "20M", "MODE": "SSB"}, STATION)
    records = list(parse_adif(book.path.read_text()))
    assert records[0]["CALL"] == "W1AW"
    assert records[0]["BAND"] == "20m"


def test_a_new_file_gets_a_header(book):
    log_qso(book, {"CALL": "W1AW"}, STATION)
    text = book.path.read_text()
    assert "<ADIF_VER:5>3.1.4" in text
    assert "<EOH>" in text


def test_the_header_is_written_once(book):
    for call in ("W1AW", "K1ABC", "DL1ABC"):
        log_qso(book, {"CALL": call}, STATION)
    assert book.path.read_text().count("<EOH>") == 1
    assert len(list(parse_adif(book.path.read_text()))) == 3


def test_appending_never_rewrites(book):
    log_qso(book, {"CALL": "W1AW"}, STATION)
    first = book.path.read_text()
    log_qso(book, {"CALL": "K1ABC"}, STATION)
    assert book.path.read_text().startswith(first)


# --- normalization -------------------------------------------------------
def test_station_details_are_filled_in(book):
    fields = normalize({"CALL": "W1AW"}, book, STATION)
    assert fields["STATION_CALLSIGN"] == "N0CALL"
    assert fields["MY_GRIDSQUARE"] == "FN31PR"


def test_a_logbook_can_override_the_station_callsign(tmp_path):
    portable = Logbook(id="p", name="P", path=tmp_path / "p.adi", station_callsign="N0CALL/P")
    fields = normalize({"CALL": "W1AW"}, portable, STATION)
    assert fields["STATION_CALLSIGN"] == "N0CALL/P"


def test_date_and_time_default_to_now(book):
    fields = normalize({"CALL": "W1AW"}, book, STATION)
    assert len(fields["QSO_DATE"]) == 8
    assert len(fields["TIME_ON"]) == 6


def test_case_follows_adif_convention(book):
    fields = normalize({"CALL": "w1aw", "BAND": "20M", "MODE": "ssb"}, book, STATION)
    assert fields["CALL"] == "W1AW"
    assert fields["BAND"] == "20m"
    assert fields["MODE"] == "SSB"


@pytest.mark.parametrize("call", ["", "  ", "X", "!!!", "<script>", "A" * 30])
def test_implausible_callsigns_are_refused(book, call):
    with pytest.raises(LogbookError):
        normalize({"CALL": call}, book, STATION)


def test_unknown_fields_are_dropped_not_written(book):
    """A log file is not a place to put arbitrary caller-supplied keys."""
    fields = normalize({"CALL": "W1AW", "EVIL": "x", "__proto__": "y"}, book, STATION)
    assert set(fields) <= {"CALL", "QSO_DATE", "TIME_ON", "STATION_CALLSIGN", "MY_GRIDSQUARE"}


def test_control_characters_are_stripped(book):
    fields = normalize({"CALL": "W1AW", "COMMENT": "hello\x00\x1bworld"}, book, STATION)
    assert fields["COMMENT"] == "helloworld"


def test_long_fields_are_capped(book):
    fields = normalize({"CALL": "W1AW", "COMMENT": "x" * 5000}, book, STATION)
    assert len(fields["COMMENT"]) <= 256


@pytest.mark.parametrize("date", ["2026", "not-a-date", "20261301x"])
def test_a_bad_date_is_refused(book, date):
    with pytest.raises(LogbookError, match="QSO_DATE"):
        normalize({"CALL": "W1AW", "QSO_DATE": date}, book, STATION)


# --- reading back --------------------------------------------------------
def test_recent_returns_newest_first(book):
    for call in ("W1AW", "K1ABC", "DL1ABC"):
        log_qso(book, {"CALL": call}, STATION)
    assert [r["CALL"] for r in recent(book)] == ["DL1ABC", "K1ABC", "W1AW"]


def test_recent_on_a_missing_file_is_empty(tmp_path):
    assert recent(Logbook(id="x", name="x", path=tmp_path / "nope.adi")) == []


def test_recent_reads_only_the_tail_of_a_long_log(book):
    """A long log is megabytes and this runs on every poll."""
    for i in range(4000):
        append(book, normalize({"CALL": "W1AA", "COMMENT": f"qso {i}"}, book, STATION))
    got = recent(book, limit=5)
    assert len(got) == 5
    assert all(r["CALL"] == "W1AA" for r in got)


# --- config --------------------------------------------------------------
def test_multiple_logbooks(tmp_path):
    config = parse_config({"logbooks": [
        {"id": "main", "name": "Home", "path": "a.adi", "primary": True},
        {"id": "kx2", "path": "b.adi"},
    ]}, base_dir=tmp_path)
    assert [b.id for b in config.logbooks] == ["main", "kx2"]
    assert config.primary_logbook().id == "main"


def test_first_logbook_is_primary_by_default(tmp_path):
    config = parse_config({"logbooks": [{"id": "a", "path": "a.adi"}]}, base_dir=tmp_path)
    assert config.primary_logbook().id == "a"


def test_only_one_logbook_may_be_primary(tmp_path):
    raw = {"logbooks": [
        {"id": "a", "path": "a.adi", "primary": True},
        {"id": "b", "path": "b.adi", "primary": True},
    ]}
    with pytest.raises(ConfigError, match="only one logbook"):
        parse_config(raw, base_dir=tmp_path)


def test_logging_without_a_logbook_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="no \\[\\[logbooks\\]\\]"):
        parse_config({"logging": {"enabled": True}}, base_dir=tmp_path)


def test_logging_is_off_by_default(tmp_path):
    assert parse_config({}, base_dir=tmp_path).logging.enabled is False


# --- the write endpoint --------------------------------------------------
def serve(tmp_path, *, enabled=True, host="127.0.0.1"):
    web = tmp_path / "web"
    web.mkdir(exist_ok=True)
    (web / "index.html").write_text("<!doctype html>")
    config = Config(
        server=ServerConfig(host=host, port=0),
        sources=(),
        data_dir=tmp_path / "data",
        web_dir=web,
        station=STATION,
        logging=LoggingConfig(enabled=enabled),
        logbooks=(Logbook(id="main", name="Home", path=tmp_path / "main.adi", primary=True),),
    )
    server = build_server(config)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address, port = server.server_address[:2]
    return server, f"http://{address}:{port}", config


def post(base, body, headers=None, path="/api/qso"):
    request = urllib.request.Request(  # noqa: S310 - fixed http scheme
        f"{base}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    return urllib.request.urlopen(request, timeout=5)  # noqa: S310


@pytest.fixture
def live(tmp_path):
    server, base, config = serve(tmp_path)
    yield base, config
    server.shutdown()
    server.server_close()


def test_a_qso_can_be_logged(live):
    base, config = live
    with post(base, {"qso": {"CALL": "W1AW", "BAND": "20m", "MODE": "SSB"}}) as response:
        assert json.load(response)["logged"]["CALL"] == "W1AW"
    assert "W1AW" in config.logbooks[0].path.read_text()


def test_logging_is_refused_when_disabled(tmp_path):
    server, base, _ = serve(tmp_path, enabled=False)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            post(base, {"qso": {"CALL": "W1AW"}})
        assert exc.value.code == 403
        assert "not enabled" in exc.value.read().decode()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("content_type", [
    "application/x-www-form-urlencoded", "text/plain", "multipart/form-data", "",
])
def test_only_json_bodies_are_accepted(live, content_type):
    """These three are exactly what a page can send cross-origin without preflight."""
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base, {"qso": {"CALL": "W1AW"}}, {"Content-Type": content_type})
    assert exc.value.code == 403
    assert "application/json" in exc.value.read().decode()


def test_a_cross_origin_fetch_is_refused(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base, {"qso": {"CALL": "W1AW"}}, {"Sec-Fetch-Site": "cross-site"})
    assert exc.value.code == 403


def test_a_mismatched_origin_is_refused(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base, {"qso": {"CALL": "W1AW"}}, {"Origin": "https://evil.example"})
    assert exc.value.code == 403


def test_a_rebound_host_name_is_refused(live):
    """DNS rebinding points an attacker's name at 127.0.0.1 to become same-origin."""
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base, {"qso": {"CALL": "W1AW"}}, {"Host": "evil.example"})
    assert exc.value.code == 403
    assert "Host" in exc.value.read().decode()


def test_an_oversized_body_is_refused(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base, {"qso": {"CALL": "W1AW", "COMMENT": "x" * 20000}})
    assert exc.value.code == 400


def test_an_invalid_callsign_is_refused(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base, {"qso": {"CALL": "!!!"}})
    assert exc.value.code == 400


def test_other_paths_and_methods_stay_closed(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base, {}, path="/api/anything")
    assert exc.value.code in (404, 405)

    for method in ("PUT", "DELETE", "PATCH"):
        request = urllib.request.Request(f"{base}/api/qso", method=method)  # noqa: S310
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)  # noqa: S310
        assert exc.value.code in (405, 501)


def test_the_endpoint_cannot_cause_an_outbound_fetch():
    """The property that survives even with the endpoint on.

    Checked against the module's actual imports rather than its text -- a
    substring search matches prose, and "cross-origin requests are not accepted"
    is not a network call.
    """
    import ast
    import inspect

    from hammunition_hill import server

    tree = ast.parse(inspect.getsource(server))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    # Full module paths, because the distinction matters: urllib.parse reads a
    # URL string, urllib.request goes and fetches it. http.server is how we
    # serve; http.client would be how we call out.
    outbound = {"httpx", "requests", "aiohttp", "urllib.request", "http.client", "socket"}
    offending = imported & outbound
    assert not offending, f"server gained a network client: {offending}"

    # And no call to the collector's fetch helper, whatever it is imported as.
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "get_bounded" not in calls

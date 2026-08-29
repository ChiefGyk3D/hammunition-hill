# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Integration tests against a real bound server on an ephemeral port."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from hammunition_hill.config import Config, ServerConfig
from hammunition_hill.server import build_csp, build_server


@pytest.fixture
def live(tmp_path):
    web = tmp_path / "web"
    data = tmp_path / "data"
    web.mkdir()
    data.mkdir()
    (web / "index.html").write_text("<!doctype html><title>hh</title>")
    (data / "solar.json").write_text(json.dumps({"data": {"flux": 142}}))
    (tmp_path / "secret.txt").write_text("must never be served")

    config = Config(
        server=ServerConfig(host="127.0.0.1", port=0),
        sources=(),
        data_dir=data,
        web_dir=web,
        embed_hosts=("radar.weather.gov",),
    )
    server = build_server(config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}", tmp_path
    server.shutdown()
    server.server_close()


def get(url, method="GET"):
    request = urllib.request.Request(url, method=method)  # noqa: S310 - fixed http scheme
    return urllib.request.urlopen(request, timeout=5)  # noqa: S310


def test_serves_the_dashboard(live):
    base, _ = live
    with get(f"{base}/") as response:
        assert response.status == 200
        assert b"<!doctype html>" in response.read()


def test_serves_snapshots(live):
    base, _ = live
    with get(f"{base}/data/solar.json") as response:
        assert json.load(response)["data"]["flux"] == 142


def test_snapshots_are_never_cached(live):
    base, _ = live
    with get(f"{base}/data/solar.json") as response:
        assert response.headers["Cache-Control"] == "no-store"


def test_the_app_itself_must_revalidate(live):
    """Static files carry no-cache, because the deployment is a wall display.

    With no Cache-Control at all, browsers cache heuristically -- about 10% of
    the file's age -- and a kiosk browser that has been up for weeks kept
    running old panel code after an upgrade, reload included: the reload was
    served from its own cache. The operator saw tabs that had been removed and
    a bug that had been fixed. no-cache forces revalidation without forbidding
    the 304 path that makes revalidation cheap.
    """
    base, _ = live
    with get(f"{base}/") as response:
        assert response.headers["Cache-Control"] == "no-cache"
    with get(f"{base}/index.html") as response:
        assert response.headers["Cache-Control"] == "no-cache"


def test_revalidation_is_a_304_not_a_redownload(live):
    """The cheap half of the no-cache promise: unchanged files answer 304."""
    base, _ = live
    with get(f"{base}/index.html") as response:
        stamp = response.headers["Last-Modified"]
        assert stamp

    request = urllib.request.Request(  # noqa: S310 - fixed http scheme
        f"{base}/index.html", headers={"If-Modified-Since": stamp}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            status = response.status
    except urllib.error.HTTPError as err:
        status = err.code
    assert status == 304


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/../../etc/passwd",
        "/%2e%2e/secret.txt",
        "/data/../../secret.txt",
        "/data/%2e%2e%2fsecret.txt",
        "/....//secret.txt",
    ],
)
def test_traversal_cannot_escape_either_root(live, path):
    base, tmp_path = live
    try:
        with get(f"{base}{path}") as response:
            assert b"must never be served" not in response.read()
    except urllib.error.HTTPError as exc:
        assert exc.code in (400, 403, 404)


def test_directory_listings_are_off(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(f"{base}/data/")
    assert exc.value.code == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_writes_are_rejected(live, method):
    """There is no write path. Confirm it stays that way."""
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(f"{base}/", method=method)
    assert exc.value.code in (405, 501)


def test_security_headers_present(live):
    base, _ = live
    with get(f"{base}/") as response:
        headers = response.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "geolocation=()" in headers["Permissions-Policy"]
    assert "usb=()" in headers["Permissions-Policy"]
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "default-src 'none'" in headers["Content-Security-Policy"]


def test_python_version_is_not_advertised(live):
    base, _ = live
    with get(f"{base}/") as response:
        assert "Python" not in response.headers.get("Server", "")


# --- CSP construction ---------------------------------------------------
def test_csp_locks_everything_down_by_default():
    policy = build_csp(())
    assert "default-src 'none'" in policy
    assert "script-src 'self'" in policy
    assert "connect-src 'self'" in policy
    assert "frame-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "form-action 'none'" in policy


def test_csp_admits_only_declared_embed_hosts():
    policy = build_csp(("radar.weather.gov",))
    assert "https://radar.weather.gov" in policy
    # An embed host must never widen script or connect.
    assert "script-src 'self';" in policy
    assert "connect-src 'self';" in policy


def test_embed_hosts_are_deduplicated():
    assert build_csp(("a.example", "a.example")).count("https://a.example") == 2  # img + frame

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The static file server.

It serves ``web/`` and ``data/`` and nothing else. No query handling, no routes.
Adding an endpoint here means taking on an attack surface this project exists to
avoid -- if you find yourself wanting one, put the work in the collector instead.

There is exactly one exception, and it is off by default: ``POST /api/qso``,
which appends a QSO to a logbook when ``[logging] enabled`` is set. It is the
narrowest thing that can do the job -- see :func:`_check_write_request` for the
three defences and docs/LOGBOOK.md for why they are the right three. Crucially
it still cannot cause an outbound fetch, so "a request cannot make the collector
fetch anything" holds even with it on.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import threading
import time
from collections import deque
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from .config import Config
from .logbook import LogbookError, log_qso

log = logging.getLogger(__name__)

DATA_PREFIX = "/data/"
QSO_PATH = "/api/qso"
METRICS_PATH = "/metrics"
LOOKUP_PREFIX = "/lookup/"

# The query endpoint's callsign gate. Charset and length, nothing cleverer: a
# format regex tight enough to be interesting rejects real calls, and the first
# draft of this one did -- it allowed only a short suffix after the slash, and
# prefix-first portable forms like VP8/G4ABC put the LONG part there. Both
# orders are real (W1AW/P and VP8/G4ABC), so both sides accept up to a full
# call. Everything past this line only ever reaches a parameterised SQLite
# query or a dict lookup. Uppercased first, so the pattern has one case to say.
_CALLSIGN = re.compile(r"^(?=[A-Z0-9/]{3,14}$)[A-Z0-9]+(?:/[A-Z0-9]+)?$")

# One bucket for the whole server, deliberately: the design constraint is
# "cannot be used to hammer anything", which is a property of the process, not
# of one client. Per-IP buckets behind a home router all see the same address
# anyway. Sixty in any rolling minute is far beyond a human typing callsigns
# and far below anything that could hurt SQLite.
_LOOKUP_WINDOW_SECONDS = 60.0
_LOOKUP_WINDOW_LIMIT = 60
_lookup_times: deque[float] = deque()
_lookup_lock = threading.Lock()


def _lookup_rate_ok(now: float | None = None) -> bool:
    stamp = time.monotonic() if now is None else now
    with _lookup_lock:
        while _lookup_times and stamp - _lookup_times[0] > _LOOKUP_WINDOW_SECONDS:
            _lookup_times.popleft()
        if len(_lookup_times) >= _LOOKUP_WINDOW_LIMIT:
            return False
        _lookup_times.append(stamp)
        return True


# Snapshots the collector writes that are not [[sources]] entries: the startup
# reference tables and the two derived models. Listed here rather than globbed
# off disk so a stray file in the data directory cannot become a metric.
DERIVED_SOURCES = frozenset(
    {
        "station",
        "prefixes",
        "imagery",
        "morse",
        "antenna",
        "propagation",
        "satellites",
        "tle",
    }
)

# A QSO record is a few hundred bytes. Anything larger is not one.
MAX_BODY_BYTES = 8192

# Hosts that cannot be pointed at us by DNS rebinding.
_SAFE_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0"})


def _host_is_expected(host_header: str, bound_host: str) -> bool:
    """Reject a Host we were not addressed by.

    DNS rebinding works by pointing an attacker-controlled *name* at 127.0.0.1,
    which makes their page same-origin with us. An IP literal cannot be rebound,
    so bare addresses are safe and unexpected names are not.
    """
    host = (host_header or "").split(":")[0].strip().lower()
    if not host:
        return False
    if host in _SAFE_HOST_NAMES or host == bound_host.lower():
        return True
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def build_csp(embed_hosts: tuple[str, ...], image_hosts: tuple[str, ...] = ()) -> str:
    """Content-Security-Policy, derived from config rather than hand-maintained.

    Everything defaults to 'none' and is opened one directive at a time. Tier 2
    hosts are the only external origins that ever appear, and only in the two
    directives that can use them.

    The two lists are separate because an imagery tile needs ``img-src`` and
    nothing else. An ``<img>`` cannot run script; a frame from the same host
    can. Granting a radar server the right to be framed because we wanted to
    show a picture from it would be handing out a capability nobody asked for,
    so ``[[imagery]]`` hosts reach exactly one directive and ``[embeds]``
    allow_hosts -- which is what an operator sets when they do want a frame --
    reaches both.
    """
    framable = sorted(set(embed_hosts))
    loadable = sorted(set(embed_hosts) | set(image_hosts))
    img = " ".join(["'self'", "data:", *(f"https://{h}" for h in loadable)])
    frame = " ".join(f"https://{h}" for h in framable) or "'none'"
    return "; ".join(
        (
            "default-src 'none'",
            "script-src 'self'",
            "style-src 'self'",
            f"img-src {img}",
            "font-src 'self'",
            "media-src 'self'",
            "connect-src 'self'",
            f"frame-src {frame}",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )


class DashboardHandler(SimpleHTTPRequestHandler):
    """Read-only handler over two directories, with the headers turned up."""

    server_version = "hammunition-hill"
    sys_version = ""  # Do not advertise the Python version.

    def __init__(self, *args: Any, config: Config, csp: str, **kwargs: Any) -> None:
        self._config = config
        self._csp = csp
        super().__init__(*args, directory=str(config.web_dir), **kwargs)

    # --- routing -----------------------------------------------------------
    def translate_path(self, path: str) -> str:
        """Map a URL path onto one of exactly two directories.

        We do not reuse the parent implementation. Path handling is the one
        place a static server can still be broken into, and a short function
        whose containment check is visible beats inheriting behaviour that has
        to be reasoned about.
        """
        path = unquote(path.split("?", 1)[0].split("#", 1)[0], errors="surrogatepass")

        if path.startswith(DATA_PREFIX):
            root, relative = self._config.data_dir, path[len(DATA_PREFIX) :]
        else:
            root, relative = self._config.web_dir, path.lstrip("/")

        # Drop every traversal and empty component rather than resolving them.
        # There is no legitimate request here that needs to walk upward.
        parts = [part for part in PurePosixPath(relative).parts if part not in ("", ".", "..", "/")]
        candidate = root.joinpath(*parts) if parts else root

        try:
            if candidate.is_dir():
                candidate = candidate / "index.html"
            resolved = candidate.resolve()
            # Belt and braces: a symlink inside either root could still point out.
            resolved.relative_to(root.resolve())
        except (ValueError, OSError):
            return str(root / "\0")  # A path that cannot exist -> 404.
        return str(resolved)

    def do_GET(self) -> None:  # noqa: N802
        """One route of our own, then the file server.

        Checked before translate_path so /metrics can never be confused with a
        file called "metrics", and gated on config so a repository that ships
        the code does not ship the endpoint.
        """
        clean = self.path.split("?")[0]
        if clean == METRICS_PATH:
            self._serve_metrics()
            return
        if clean.startswith(LOOKUP_PREFIX):
            self._serve_lookup(clean[len(LOOKUP_PREFIX) :])
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        """Same route, no body.

        Without this the parent's file lookup answers, so a HEAD would 404 on a
        path where GET returns 200 -- which is the sort of inconsistency a proxy
        or a health check trips over long after anyone remembers why.
        """
        clean = self.path.split("?")[0]
        if clean == METRICS_PATH:
            self._serve_metrics(body=False)
            return
        if clean.startswith(LOOKUP_PREFIX):
            self._serve_lookup(clean[len(LOOKUP_PREFIX) :], body=False)
            return
        super().do_HEAD()

    def _serve_metrics(self, *, body: bool = True) -> None:
        if not self._config.metrics.enabled:
            # 404 rather than 403: an endpoint that is switched off should not
            # announce that it exists.
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        from .metrics import CONTENT_TYPE, render

        sources = tuple(sorted({s.id for s in self._config.sources} | DERIVED_SOURCES))
        try:
            payload = render(self._config.data_dir, sources).encode("utf-8")
        except OSError:
            # A scrape must not be able to take the dashboard down, and a
            # half-written body is worse for Prometheus than a clean failure.
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "metrics unavailable")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(payload)

    def _serve_lookup(self, raw: str, *, body: bool = True) -> None:
        """GET /lookup/<callsign>: the local index, and nothing else.

        The property that makes this endpoint acceptable is that it CANNOT
        cause an outbound request. It reads two things, both already on disk:
        the offline FCC ULS index, and the collector's own lookup cache --
        results a provider already returned for callsigns the collector already
        saw. There is no code path from here to a socket, so "a request cannot
        make the collector fetch anything" survives the first route that takes
        a parameter.

        Off by default. It is still an endpoint that accepts input, which is a
        real change to the attack surface, so it is a choice -- see
        docs/CALLSIGN-LOOKUP.md for the design and the argument.
        """
        if not self._config.lookup.query_endpoint:
            # 404 rather than 403, same as /metrics: an endpoint that is
            # switched off should not announce that it exists.
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        if not _lookup_rate_ok():
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            self.send_header("Retry-After", "10")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        callsign = unquote(raw).strip().upper()
        if not _CALLSIGN.match(callsign):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "not a callsign"}, body=body)
            return

        # The portable suffix is the operator's, not the licence's: /P is not
        # in anybody's database, so the base call is what gets looked up and
        # the response echoes what was asked.
        base = callsign.split("/", 1)[0]

        record, source = self._lookup_local(base)
        payload: dict[str, Any] = {"callsign": callsign, "found": record is not None}
        if record is not None:
            payload["source"] = source
            payload["record"] = record
        self._send_json(HTTPStatus.OK, payload, body=body)

    def _lookup_local(self, callsign: str) -> tuple[dict[str, Any] | None, str]:
        """The ULS index first, then the collector's cache. Disk only."""
        from .lookup.cache import CACHE_FILE
        from .lookup.uls import DEFAULT_DB_NAME, UlsIndex

        db_path = self._config.lookup.uls_db or (self._config.data_dir / DEFAULT_DB_NAME)
        index = UlsIndex(db_path)
        try:
            if index.available and (row := index.lookup(callsign)) is not None:
                return row, "fcc_uls"
        finally:
            index.close()

        cache_path = self._config.data_dir / CACHE_FILE
        try:
            entries = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, ""
        entry = entries.get(callsign) if isinstance(entries, dict) else None
        if isinstance(entry, dict) and isinstance(entry.get("result"), dict):
            result = dict(entry["result"])
            result.setdefault("cached_at", entry.get("cached_at"))
            return result, str(result.get("source") or "cache")
        return None, ""

    # --- policy ------------------------------------------------------------
    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", self._csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), usb=(), payment=(), interest-cohort=()",
        )
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if self.path.startswith(DATA_PREFIX):
            # Snapshots change; never let a proxy or the browser pin one.
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def list_directory(self, path: str) -> None:  # type: ignore[override]
        """No directory listings. Ever."""
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
        return None

    def _reject(self) -> None:
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "This server is read-only")

    do_PUT = do_DELETE = do_PATCH = _reject  # noqa: N815

    # --- the one write path ------------------------------------------------
    def _check_write_request(self) -> str | None:
        """Why this write must be refused, or None if it may proceed.

        Three defences, each closing a different door:

        1. **Content-Type must be application/json.** Form-encoded, multipart and
           plain-text are the only bodies a page can send cross-origin without a
           preflight. Requiring JSON makes any cross-origin attempt preflighted,
           and we send no CORS headers at all, so the browser refuses it before
           this code runs.
        2. **Sec-Fetch-Site and Origin must be same-origin.** Browsers set these
           themselves; a page cannot forge them.
        3. **Host must be one we could actually be addressed by**, which is what
           stops DNS rebinding.
        """
        if not self._config.logging.enabled:
            return "logging is not enabled; set [logging] enabled = true"

        if not _host_is_expected(self.headers.get("Host", ""), self._config.server.host):
            return "unexpected Host header"

        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            return "Content-Type must be application/json"

        fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if fetch_site and fetch_site != "same-origin":
            return "cross-origin requests are not accepted"

        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            expected = f"http://{self.headers.get('Host', '')}"
            if origin.lower() not in (expected.lower(), f"https://{self.headers.get('Host', '')}"):
                return "Origin does not match"

        return None

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any], *, body: bool = True) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(encoded)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != QSO_PATH:
            self._reject()
            return

        refusal = self._check_write_request()
        if refusal:
            log.warning("refused write: %s", refusal)
            self._send_json(HTTPStatus.FORBIDDEN, {"error": refusal})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "bad Content-Length"})
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "body missing or too large"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"bad JSON: {exc}"})
            return
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "expected a JSON object"})
            return

        book = self._config.logbook(str(payload.get("logbook") or "")) or (
            self._config.primary_logbook()
        )
        if book is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "no logbook configured"})
            return

        try:
            written = log_qso(book, payload.get("qso") or {}, self._config.station)
        except LogbookError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except OSError as exc:
            log.error("could not write logbook %s: %s", book.id, exc)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "could not write"})
            return

        self._send_json(HTTPStatus.OK, {"logged": written, "logbook": book.id})

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)


def build_server(config: Config) -> ThreadingHTTPServer:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    csp = build_csp(config.embed_hosts, config.csp_hosts())
    handler = partial(DashboardHandler, config=config, csp=csp)
    server = ThreadingHTTPServer((config.server.host, config.server.port), handler)
    server.daemon_threads = True
    return server

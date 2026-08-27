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


def build_csp(embed_hosts: tuple[str, ...]) -> str:
    """Content-Security-Policy, derived from config rather than hand-maintained.

    Everything defaults to 'none' and is opened one directive at a time. Tier 2
    embed hosts are the only external origins that ever appear, and only in the
    two directives that can use them.
    """
    external = " ".join(f"https://{h}" for h in sorted(set(embed_hosts)))
    img = f"'self' data: {external}".strip()
    frame = external or "'none'"
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

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
    handler = partial(DashboardHandler, config=config, csp=build_csp(config.embed_hosts))
    server = ThreadingHTTPServer((config.server.host, config.server.port), handler)
    server.daemon_threads = True
    return server

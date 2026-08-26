"""The static file server.

It does exactly two things: serve ``web/`` and serve ``data/``. There are no
routes, no query handling, and no request body is ever read. Adding an endpoint
here means taking on an attack surface this project exists to avoid -- if you
find yourself wanting one, put the work in the collector instead.
"""

from __future__ import annotations

import logging
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from .config import Config

log = logging.getLogger(__name__)

DATA_PREFIX = "/data/"


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

    do_POST = do_PUT = do_DELETE = do_PATCH = _reject  # noqa: N815

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), fmt % args)


def build_server(config: Config) -> ThreadingHTTPServer:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    handler = partial(DashboardHandler, config=config, csp=build_csp(config.embed_hosts))
    server = ThreadingHTTPServer((config.server.host, config.server.port), handler)
    server.daemon_threads = True
    return server

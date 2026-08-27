#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""End-to-end smoke test: collector fetches, server serves, headers are right.

The unit tests mock the transport, which is correct for testing parsers and
wrong for testing that the whole thing runs. This starts a real `hamhill serve`
against a real local upstream and checks the loop closes: an HTTP fetch becomes
a snapshot on disk becomes a response to a browser, with the security headers
attached.

Local upstream on purpose. Pointing CI at NOAA would make a green run depend on
their uptime and would put this project's CI traffic on a free government
service, which is not a reasonable thing to do on every push.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[2]

# A minimal but real SWPC-shaped payload: [header row, ...data rows].
KINDEX = json.dumps(
    [
        ["time_tag", "Kp", "a_running", "station_count"],
        ["2026-08-27 00:00:00.000", "2.00", "7", "8"],
        ["2026-08-27 03:00:00.000", "3.67", "12", "8"],
    ]
)

REQUIRED_HEADERS = {
    "Content-Security-Policy": "default-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = KINDEX.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass  # Quiet: the interesting output is ours, not the stub's.


_process: subprocess.Popen | None = None


class SmokeFailed(Exception):
    """A check did not pass. Raised rather than exiting in place.

    `fail()` used to call sys.exit, which meant every function that ended in a
    call to it had one path returning a value and one falling off the end --
    syntactically an implicit `return None`, even though it could never be
    reached. CodeQL flagged exactly that, and it was right: nothing in the
    signature or the control flow told a reader the call was terminal.

    Raising makes every path either return a value or raise, and puts the
    diagnostics in one handler instead of in a function called from everywhere.
    """


def free_port() -> int:
    """A port nothing is listening on right now.

    Fixed ports are fine on a fresh CI runner and a nuisance locally: a
    collector left over from an interrupted run holds the port, and the next
    attempt then fails looking like a broken test rather than a busy socket.
    The bind-and-release race is acceptable for a test harness.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def fail(message: str) -> NoReturn:
    raise SmokeFailed(message)


def report_failure(message: str) -> None:
    """Print the failure with the collector's own output attached.

    A timeout that says only "timed out" sends whoever is reading the log off to
    reproduce it locally. The reason is nearly always in the collector's output,
    so print it here rather than making them go and find it.
    """
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
    if _process is not None and _process.stdout is not None:
        output = _process.stdout.read()
        if output:
            print("--- collector output ---")
            print(output)
            print("--- end collector output ---")
    print(f"::error::{message}")


def wait_for(predicate, timeout: float, description: str):  # type: ignore[no-untyped-def]
    """Poll until true. CI machines are slow and vary; fixed sleeps flake."""
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
        except Exception as exc:  # noqa: BLE001 - retrying is the point
            last = exc
        else:
            if result:
                return result
            last = result
        time.sleep(0.5)
    raise SmokeFailed(f"timed out after {timeout}s waiting for {description} (last: {last!r})")


def main() -> int:
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    upstream_port = upstream.server_address[1]
    Thread(target=upstream.serve_forever, daemon=True).start()
    print(f"stub upstream on 127.0.0.1:{upstream_port}")

    with TemporaryDirectory() as workdir:
        work = Path(workdir)
        dashboard_port = free_port()
        (work / "config.toml").write_text(
            f"""
[server]
host = "127.0.0.1"
port = {dashboard_port}

[station]
callsign = "N0CALL"
grid = "DM79"

[paths]
data_dir = "{work / "data"}"
web_dir = "{ROOT / "web"}"

[[sources]]
id = "kindex"
kind = "swpc"
url = "http://127.0.0.1:{upstream_port}/kindex.json"
local = true
interval = 30
options = {{ product = "planetary_k_index" }}
""",
            encoding="utf-8",
        )

        global _process
        process = _process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "hammunition_hill", "serve", "--config", "config.toml"],
            cwd=work,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            base = f"http://127.0.0.1:{dashboard_port}"

            def index_served() -> bool:
                if process.poll() is not None:
                    fail("the collector exited before serving anything")
                with urllib.request.urlopen(f"{base}/", timeout=2) as response:  # noqa: S310
                    return response.status == 200

            wait_for(index_served, 30, "the dashboard to serve index.html")
            print("index.html served")

            # 1. The security headers are actually on the wire, not just in a
            #    unit test's idea of the handler.
            with urllib.request.urlopen(f"{base}/", timeout=5) as response:  # noqa: S310
                for header, expected in REQUIRED_HEADERS.items():
                    actual = response.headers.get(header)
                    if actual is None:
                        fail(f"missing header {header}")
                    if expected not in actual:
                        fail(f"header {header} is {actual!r}, expected to contain {expected!r}")
            print(f"{len(REQUIRED_HEADERS)} security headers present")

            # 2. The collector actually fetched and wrote a snapshot.
            def snapshot_ready() -> dict | None:
                with urllib.request.urlopen(f"{base}/data/kindex.json", timeout=2) as response:  # noqa: S310
                    payload = json.load(response)
                return payload if payload.get("data") is not None else None

            snapshot = wait_for(snapshot_ready, 60, "the first collector cycle")
            if snapshot.get("error"):
                fail(f"snapshot carries an error: {snapshot['error']}")
            for key in ("source", "kind", "fetched_at", "stale_after_seconds", "data"):
                if key not in snapshot:
                    fail(f"snapshot is missing {key!r}")
            print(f"snapshot written and served: {snapshot['source']} ({snapshot['kind']})")

            # 3. Traversal out of the served directories is refused. The path
            #    handling is the one part of a static server still worth
            #    attacking, so prove it against a running process.
            for attack in (
                "/../../etc/passwd",
                "/data/../../etc/passwd",
                "/%2e%2e/%2e%2e/etc/passwd",
                "/data/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
                "/....//....//etc/passwd",
            ):
                try:
                    with urllib.request.urlopen(base + attack, timeout=5) as response:  # noqa: S310
                        body = response.read(200)
                    if b"root:" in body:
                        fail(f"path traversal succeeded for {attack}")
                    print(f"  {attack} -> {response.status} (no leak)")
                except urllib.error.HTTPError as exc:
                    print(f"  {attack} -> {exc.code}")
            print("path traversal refused")

            # 4. The write endpoint stays shut while logging is off.
            try:
                request = urllib.request.Request(  # noqa: S310
                    f"{base}/log",
                    data=b'{"call":"W1AW"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                    fail(f"POST /log returned {response.status} with logging disabled")
            except urllib.error.HTTPError as exc:
                if exc.code < 400:
                    fail(f"POST /log returned {exc.code} with logging disabled")
                print(f"POST /log refused with {exc.code} while logging is off")

            print("\nsmoke test passed")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            upstream.shutdown()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SmokeFailed as failure:
        report_failure(str(failure))
        sys.exit(1)

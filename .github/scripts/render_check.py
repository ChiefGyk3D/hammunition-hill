#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Load every dashboard in a real browser and fail on anything it complains about.

Roughly three thousand lines of JavaScript ship in web/, and the panel host
wraps each module's render() in a try/catch -- which is right for a wall display
(one broken panel should not take out the other eighteen) and means a broken
panel is *invisible to every other kind of test*. It renders one small error
line on one dashboard and nothing else notices.

So this drives Chromium over each dashboard and fails on:

  - any uncaught exception or console error,
  - any panel that rendered the host's "panel error:" fallback,
  - any request to a host outside this origin.

That last one matters most. The whole architecture rests on the browser talking
only to this origin plus imagery hosts the operator named. A panel that acquired
a fetch to somewhere else would be a real regression and nothing else here would
see it -- the CSP would block it in a compliant browser, but the attempt itself
is the bug.

Screenshots are written for the CI artifact, because "it rendered" and "it looks
right" are different claims and only a person can make the second one.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from threading import Thread
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[2]
# Where the CI job's upload step looks for them; RENDER_SHOTS overrides it
# so a contributor can put them elsewhere.
SHOTS = Path(os.environ.get("RENDER_SHOTS") or Path(gettempdir()) / "hamhill-render")

KINDEX = json.dumps(
    [
        ["time_tag", "Kp", "a_running", "station_count"],
        ["2026-08-27 00:00:00.000", "2.00", "7", "8"],
        ["2026-08-27 03:00:00.000", "3.67", "12", "8"],
    ]
)


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = KINDEX.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


DRIVER = r"""
const { chromium } = require('playwright');

const PORT = process.argv[2];
const SHOTS = process.argv[3];
const BASE = `http://127.0.0.1:${PORT}/`;

(async () => {
  // CHROMIUM_PATH lets this run against a browser that is already on the
  // machine, so a contributor can reproduce a CI render failure without
  // downloading playwright's own build.
  const executablePath = process.env.CHROMIUM_PATH || undefined;
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const problems = [];

  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });

  // 404 handling, split by who actually knows what failed.
  //
  // The console message for a failed resource does not name the URL, so it
  // cannot be judged on its own -- and pairing it with a response event races,
  // because the two arrive in no guaranteed order. So the response listener is
  // authoritative (it has the URL) and the console's URL-less 404 noise is
  // dropped wholesale. Every other console error is kept.
  //
  // A 404 on /data/*.json is the app's normal "that source is not configured"
  // path: this run defines one source, so most panels legitimately get one and
  // render their empty state. A 404 on anything else -- a panel module, the
  // stylesheet, the panel index -- is a real finding.
  const RESOURCE_404 = /Failed to load resource.*\b404\b/i;
  let unconfigured = 0;

  page.on('response', (res) => {
    if (res.status() < 400) return;
    const path = new URL(res.url()).pathname;
    if (res.status() === 404 && /^\/data\/[\w-]+\.json$/.test(path)) unconfigured += 1;
    else problems.push(`HTTP ${res.status()} for ${res.url()}`);
  });

  // Which snapshots the app has asked for since the last tab click. poll()
  // only fetches what the *visible* dashboard wants, so a switch that does not
  // fetch leaves every panel on the new tab painting its empty state until the
  // next ten-second interval. That is invisible to a screenshot taken after it
  // finally lands, so it is checked here rather than looked for by eye.
  let requestedSinceClick = new Set();
  page.on('request', (req) => {
    const match = new URL(req.url()).pathname.match(/^\/data\/([\w-]+)\.json$/);
    if (match) requestedSinceClick.add(match[1]);
  });

  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    if (RESOURCE_404.test(msg.text())) return;  // judged by the listener above
    problems.push(`console error: ${msg.text()}`);
  });

  page.on('pageerror', (err) => problems.push(`uncaught exception: ${err.message}`));
  page.on('requestfailed', (req) => {
    // A blocked external request is itself the finding; report the attempt.
    problems.push(`request failed: ${req.url()} (${req.failure()?.errorText})`);
  });

  page.on('request', (req) => {
    const url = new URL(req.url());
    const local = url.hostname === '127.0.0.1' || url.hostname === 'localhost';
    if (!local && url.protocol !== 'data:') {
      problems.push(`request left this origin: ${req.url()}`);
    }
  });

  // NOT networkidle: the dashboard polls its snapshots every ten seconds and
  // is never idle by design, so networkidle waits until it times out.
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#tabs button', { timeout: 30000 });

  // Read the dashboards from the page itself rather than hardcoding a list,
  // so adding a dashboard is covered without editing this script.
  const tabs = await page.$$eval('#tabs button', (els) => els.map((e) => e.textContent.trim()));
  if (tabs.length === 0) problems.push('no dashboard tabs rendered');
  console.log(`dashboards: ${tabs.join(', ')}`);

  for (const tab of tabs) {
    requestedSinceClick = new Set();
    await page.click(`#tabs button:text-is("${tab}")`);
    // Panels render synchronously from cached snapshots; give the tier 0
    // clocks a tick and any lazy image a moment to be requested.
    await page.waitForTimeout(1200);

    // Everything this dashboard's panels declare must have been asked for by
    // now -- not on the next interval, by which time a person has already read
    // "waiting for the first cycle" and drawn a conclusion.
    const wanted = await page.$$eval('#grid .panel', (els) =>
      Promise.all(
        els.map((e) =>
          fetch(`./panels/${e.dataset.panel}/panel.json`)
            .then((r) => r.json())
            .then((m) => m.sources || [])
            .catch(() => []),
        ),
      ).then((lists) => [...new Set(lists.flat())]),
    );
    const unfetched = wanted.filter((id) => !requestedSinceClick.has(id));
    if (unfetched.length) {
      problems.push(
        `${tab}: switched to this dashboard without fetching ${unfetched.join(', ')} ` +
          `-- its panels sit on their empty state until the next poll`,
      );
    }

    const panels = await page.$$eval('#grid .panel', (els) =>
      els.map((e) => ({
        id: e.dataset.panel,
        body: e.querySelector('.panel-body')?.textContent ?? '',
      })),
    );
    if (panels.length === 0) problems.push(`${tab}: no panels rendered`);

    for (const panel of panels) {
      if (panel.body.includes('panel error:')) {
        problems.push(`${tab}/${panel.id}: ${panel.body.trim().slice(0, 200)}`);
      }
    }
    const slug = tab.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    await page.screenshot({ path: `${SHOTS}/${slug}.png`, fullPage: true });
    console.log(`  ${tab}: ${panels.length} panels ok`);
  }

  await browser.close();

  if (problems.length) {
    for (const p of problems) console.log(`::error::${p}`);
    console.log(`\n${problems.length} problem(s)`);
    process.exit(1);
  }
  console.log(`\nevery dashboard rendered cleanly`);
  console.log(`${unconfigured} snapshot 404s from sources this run does not configure (expected)`);
})().catch((err) => {
  console.log(`::error::driver crashed: ${err.stack || err}`);
  process.exit(1);
});
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
    """Annotated NoReturn so callers -- and type checkers -- know it is terminal.

    Not flagged by CodeQL the way smoke.py's was, because these calls sit inside
    a loop rather than mixing with a return in the same function. Same honesty
    either way: a signature saying `-> None` on something that never returns is
    just wrong.
    """
    print(f"::error::{message}")
    sys.exit(1)


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    upstream_port = upstream.server_address[1]
    Thread(target=upstream.serve_forever, daemon=True).start()

    port = free_port()
    with TemporaryDirectory() as workdir:
        work = Path(workdir)
        (work / "config.toml").write_text(
            f"""
[server]
host = "127.0.0.1"
port = {port}

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

        # The driver is written into the repository root, not the temp
        # directory, so that `require('playwright')` resolves against
        # ROOT/node_modules. Node walks *up* from the script's directory, and a
        # driver in /tmp would never find a module installed in the checkout.
        # NODE_PATH still overrides this for anyone with playwright elsewhere.
        driver = ROOT / ".render-driver.js"
        driver.write_text(DRIVER, encoding="utf-8")

        server = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "hammunition_hill", "serve", "--config", "config.toml"],
            cwd=work,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    output = server.stdout.read() if server.stdout else ""
                    fail(f"the dashboard exited before serving:\n{output}")
                try:
                    with urllib.request.urlopen(  # noqa: S310
                        f"http://127.0.0.1:{port}/", timeout=2
                    ) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    time.sleep(0.5)
            else:
                fail("the dashboard never came up")

            # Let the first collector cycle land so panels have real data and
            # are not all showing "waiting for the first cycle".
            time.sleep(6)

            result = subprocess.run(  # noqa: S603
                ["node", str(driver), str(port), str(SHOTS)],  # noqa: S607
                cwd=ROOT,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode != 0:
                output = ""
                if server.stdout is not None:
                    server.terminate()
                    server.wait(timeout=10)
                    output = server.stdout.read()
                if output:
                    print("--- dashboard output ---")
                    print(output)
                return 1

            print(f"\nscreenshots in {SHOTS}")
            return 0
        finally:
            (ROOT / ".render-driver.js").unlink(missing_ok=True)
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
            upstream.shutdown()


if __name__ == "__main__":
    sys.exit(main())

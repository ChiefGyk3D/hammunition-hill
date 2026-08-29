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
import socketserver
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


# A published element set, so the satellite panel renders with content rather
# than its "no elements yet" state. Without it the populated path -- the pass
# table, the countdown, the elevation banding -- is never rendered here at all,
# and a bug in it would ship.
#
# The epoch is old, so the predicted times mean nothing. That is fine and worth
# being clear about: this exercises the layout and the code path, not the
# astronomy, which tests/test_satellites.py covers with real invariants.
TLES = """ISS (ZARYA)
1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991
2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482
"""


# An RBN feed, spoken well enough for the real client: a login prompt, then
# spots. Nothing in this repository exercised a stream client end to end before
# -- the read loop, the login, the tally and the snapshot write were only ever
# tested in pieces, and the panel that renders the result was never rendered
# with a result in it.
RBN_SPOTS = [
    "DX de W3LPL-#:   14025.0  N0CALL         CW    23 dB  28 WPM  CQ      1234Z",
    "DX de VE7CC-#:    7030.5  N0CALL         CW    12 dB  25 WPM  CQ      1235Z",
    "DX de KM3T-#:    21023.4  N0CALL         CW     6 dB  22 WPM  CQ      1236Z",
    "DX de DL8LAS-#:  14074.0  JA1XYZ         FT8   -8 dB  15 WPM  CQ      1237Z",
    "DX de EA5WU-#:    3573.0  VK2DEF         FT8  -21 dB  15 WPM  CQ      1238Z",
    "DX de SM7IUN-#:  14025.5  G0ABC          CW    17 dB  30 WPM  DX      1239Z",
    "DX de OH6BG-#:   21074.0  ZS6XYZ         FT8   -3 dB  15 WPM  CQ      1240Z",
    "DX de W1NT-#:     7025.0  VE3ABC         CW    31 dB  24 WPM  CQ      1241Z",
]


class RbnStub(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            self.wfile.write(b"Please enter your call: ")
            self.wfile.flush()
            self.rfile.readline()  # whatever callsign the client sends
            for line in RBN_SPOTS:
                self.wfile.write((line + "\r\n").encode())
            self.wfile.flush()
            # Hold the connection so the client does not reconnect in a loop
            # for the length of the run.
            time.sleep(120)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class ThreadedTCP(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


# F10.7 flux rows as SWPC's JSON serves them. With flux present the MUF
# indicator and the DX Path panel render their populated paths -- before this
# both sat on "waiting for solar flux" in every screenshot and a broken chart
# would have shipped invisibly.
F107 = json.dumps(
    [
        {"time_tag": "2026-08-27T00:00:00", "flux": 148.2},
        {"time_tag": "2026-08-28T00:00:00", "flux": 152.4},
    ]
)


def psk_reports() -> str:
    """Reception reports of N0CALL, stamped fresh so ages read sanely.

    Bands and locators are spread on purpose: the globes panel draws one
    sphere per band with activity, and a run where these reports are the only
    spot supply proves the reception wiring end to end -- if the panel stopped
    reading the pskreporter/wspr snapshots, the Map dashboard would render the
    globes' empty state and the driver's check below would say so.
    """
    now = int(time.time())
    rows = [
        ("JA1NUT", "PM95vp", 14074100, "FT8", -12, now - 90),
        ("VK4CT", "QG62lp", 14074300, "FT8", -18, now - 150),
        ("G4HZV", "IO91wm", 7074000, "FT8", -7, now - 200),
        ("PY2GN", "GG66rg", 21074500, "FT8", -15, now - 260),
        ("W6BB", "CM87xe", 7074200, "FT8", 2, now - 320),
    ]
    reports = "".join(
        f'<receptionReport receiverCallsign="{call}" receiverLocator="{grid}" '
        f'senderCallsign="N0CALL" frequency="{hz}" mode="{mode}" sNR="{snr}" '
        f'flowStartSeconds="{at}"/>'
        for call, grid, hz, mode, snr, at in rows
    )
    return (
        f'<?xml version="1.0"?>'
        f'<receptionReports currentSeconds="{now}">{reports}</receptionReports>'
    )


def wspr_reports() -> str:
    """wspr.live's ClickHouse JSON shape, 64-bit ints quoted as it emits them."""
    stamp = time.strftime("%Y-%m-%d %H:%M:00", time.gmtime(time.time() - 120))
    rows = [
        {
            "time": stamp,
            "rx_sign": "OE9GHV",
            "rx_lat": 47.3,
            "rx_lon": 9.6,
            "rx_loc": "JN47tm",
            "distance": "6423",
            "snr": -21,
            "power": 37,
            "frequency": "10140200",
        },
        {
            "time": stamp,
            "rx_sign": "ZL2005SWL",
            "rx_lat": -41.2,
            "rx_lon": 174.9,
            "rx_loc": "RE78js",
            "distance": "13102",
            "snr": -26,
            "power": 37,
            "frequency": "10140150",
        },
    ]
    return json.dumps({"meta": [], "data": rows, "rows": len(rows)})


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/f107"):
            body, content_type = F107.encode(), "application/json"
        elif self.path.startswith("/psk"):
            body, content_type = psk_reports().encode(), "text/xml"
        elif self.path.startswith("/wspr"):
            body, content_type = wspr_reports().encode(), "application/json"
        elif self.path.endswith(".txt"):
            body, content_type = TLES.encode(), "text/plain"
        else:
            body, content_type = KINDEX.encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
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

  // Freeze the wall clock. Half the panels print the time, so without this two
  // runs over identical code produce different PNGs -- and since these
  // screenshots are checked into docs/images, every `make screenshots` would
  // dirty every file and the diff would stop meaning "something changed".
  //
  // setFixedTime, not clock.install: the latter also freezes timers, and the
  // app's poll interval and the tier 0 panels' one-second tick both need to
  // keep running for the checks below to mean anything.
  //
  // This does not make every file byte-identical between runs. A panel's age
  // badge is the gap between the frozen page clock and the snapshot's real
  // fetched_at, so any dashboard carrying a live source still moves by the
  // seconds the collector took to start. Pinning that too would mean the
  // collector stamping a fake time for the benefit of a screenshot, which is
  // not a trade worth making. Five of the six settle; home.png may not.
  await page.clock.setFixedTime(new Date('2026-03-20T18:30:00Z'));

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
    // ERR_ABORTED is not a failure: it is what every in-flight fetch reports
    // when a navigation cancels it, and the customize scenario reloads the
    // page on purpose. Flagging those made "test reloads the page" and "the
    // dashboard cannot fetch its data" indistinguishable.
    if (req.failure()?.errorText === 'net::ERR_ABORTED') return;
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
  // .tab-edit is the customize toggle, not a dashboard; clicking it mid-census
  // put the page into edit mode and the rest of the loop into the weeds.
  const tabs = await page.$$eval('#tabs button:not(.tab-edit)', (els) =>
    els.map((e) => e.textContent.trim()));
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

    // No two panels may overlap. The masonry sizing computes each panel's
    // row span from its measured height, and the failure mode of getting
    // that arithmetic wrong is silent everywhere else: the page loads, no
    // console error, every panel renders -- and each one is painted over by
    // the next. It shipped exactly that way once, on the phone breakpoint,
    // where the grid gap differed from the constant the arithmetic assumed.
    const overlaps = await page.$$eval('#grid .panel', (els) => {
      const found = [];
      const rects = els.map((e) => ({ id: e.dataset.panel, r: e.getBoundingClientRect() }));
      for (let i = 0; i < rects.length; i++) {
        for (let j = i + 1; j < rects.length; j++) {
          const a = rects[i].r, b = rects[j].r;
          const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          // A shared border rounds to a sliver; demand real intrusion.
          if (x > 2 && y > 2) {
            const size = `${Math.round(x)}x${Math.round(y)}px`;
            found.push(`${rects[i].id} overlaps ${rects[j].id} by ${size}`);
          }
        }
      }
      return found;
    });
    for (const overlap of overlaps) problems.push(`${tab}: ${overlap}`);
    const slug = tab.toLowerCase().replace(/[^a-z0-9]+/g, '-');
    await page.screenshot({ path: `${SHOTS}/${slug}.png`, fullPage: true });
    console.log(`  ${tab}: ${panels.length} panels ok`);
  }

  // --- reception reports actually feed the displays -----------------------
  // The harness seeds five PSK Reporter reports (20/40/15 m) and two WSPR
  // reports (30 m), and configures no cluster or WSJT-X -- so reception
  // reports are the ONLY spot supply. If either panel stops reading the
  // pskreporter/wspr snapshots it renders its empty state, and a screenshot
  // of an empty state looks exactly like a quiet band unless something counts.
  await page.click('#tabs button:text-is("Home")');
  await page.waitForTimeout(600);
  const receptionRows = await page.$$eval(
    '#grid .panel[data-panel="reception"] .rbn-row', (els) => els.length);
  if (receptionRows !== 7) {
    problems.push(`reception: 7 seeded reports should render 7 rows, got ${receptionRows}`);
  }
  await page.click('#tabs button:text-is("Map")');
  await page.waitForTimeout(600);
  const globeCells = await page.$$eval(
    '#grid .panel[data-panel="globes"] .globe-cell', (els) => els.length);
  if (globeCells !== 4) {
    problems.push(
      `globes: seeded reports span 4 bands (20/40/30/15 m) but ${globeCells} spheres rendered`);
  }
  console.log(`  reception: ${receptionRows} rows, ${globeCells} band globes lit`);

  // --- the DX path chart is drawn, not an empty state ----------------------
  // Still on the Map tab from the loop above. The harness supplies flux and a
  // station grid, so the panel must render the full band-by-hour lattice; a
  // wiring break (snapshot renamed, lib import broken) renders the empty
  // state, which no screenshot reviewer would reliably notice.
  await page.click('#tabs button:text-is("Map")');
  await page.waitForTimeout(600);
  const pmfCells = await page.$$eval(
    '#grid .panel[data-panel="pathmuf"] .pmf-grid > .pmf-cell:not(.pmf-corner)',
    (els) => els.length);
  if (pmfCells !== 9 * 24) {
    problems.push(`pathmuf: expected ${9 * 24} chart cells (9 bands x 24 hours), got ${pmfCells}`);
  }
  const pmfOpen = await page.$$eval(
    '#grid .panel[data-panel="pathmuf"] .pmf-grid .pmf-prime', (els) => els.length);
  if (pmfOpen === 0) {
    problems.push(
      'pathmuf: at SFI 152 no hour on any band rendered as open, which is not a real sky');
  }
  console.log(`  pathmuf: ${pmfCells} cells, ${pmfOpen} open`);

  // --- customization survives a reload -----------------------------------
  // Hide a panel, move another, reload the page cold, and demand both stuck.
  // The property being tested is persistence, so the reload is the test: an
  // implementation that keeps layout in a variable passes everything above.
  await page.click('#tabs button:text-is("Home")');
  await page.waitForTimeout(400);
  const before = await page.$$eval('#grid .panel', (els) => els.map((e) => e.dataset.panel));
  await page.click('#tabs .tab-edit');
  await page.waitForTimeout(400);
  await page.click(`#grid .panel[data-panel="${before[0]}"] .edit-btn[title="Hide this panel"]`);
  await page.waitForTimeout(300);
  await page.click(`#grid .panel[data-panel="${before[1]}"] .edit-btn[title="Move later"]`);
  await page.waitForTimeout(300);
  await page.reload({ waitUntil: 'load' });
  await page.waitForTimeout(1200);
  const after = await page.$$eval('#grid .panel', (els) => els.map((e) => e.dataset.panel));
  if (after.includes(before[0])) {
    problems.push(`customize: hid ${before[0]}, but it came back after reload`);
  }
  if (after.length !== before.length - 1) {
    const got = `${after.length}`;
    problems.push(`customize: expected ${before.length - 1} panels after hiding one, got ${got}`);
  }
  if (before[1] && after[0] === before[1]) {
    problems.push(`customize: moved ${before[1]} later, but it still renders first`);
  }
  // Reset, so the harness leaves no state behind for the screenshot runs.
  await page.click('#tabs .tab-edit');
  await page.waitForTimeout(300);
  await page.click('#grid .edit-reset');
  await page.waitForTimeout(300);
  const restored = await page.$$eval('#grid .panel', (els) => els.length);
  if (restored !== before.length) {
    problems.push(`customize: reset restored ${restored} panels, expected ${before.length}`);
  }
  console.log('  customize: hide, reorder, reload, reset ok');

  // The three rooms the stylesheet promises: phone, laptop, TV. Only the
  // laptop width was ever rendered, and the TV tier shipped broken -- the
  // zoom put getBoundingClientRect in a different coordinate space from the
  // grid lattice, every panel got ~1.9x the rows it needed, and each one
  // trailed a void nearly its own height. Two checks per size, both of which
  // that bug fails: no sideways scroll, and every panel's assigned row span
  // agrees with the height the packer should have derived for it.
  for (const size of [{ w: 390, h: 844, name: 'phone' }, { w: 3840, h: 2160, name: 'tv-4k' }]) {
    await page.setViewportSize({ width: size.w, height: size.h });
    await page.waitForTimeout(700);
    const layout = await page.evaluate(() => {
      const doc = document.documentElement;
      const style = getComputedStyle(document.querySelector('#grid'));
      const row = parseFloat(style.gridAutoRows) || 8;
      const gap = parseFloat(style.rowGap) || 12;
      const wrong = [];
      for (const panel of document.querySelectorAll('#grid .panel')) {
        // One backslash: DRIVER is a raw string, so what is written here is
        // exactly what the JS engine sees. \\d arrived as a regex for a
        // literal backslash, matched nothing, and flagged every panel.
        const span = Number((panel.style.gridRow.match(/span (\d+)/) || [])[1]);
        const need = Math.max(1, Math.ceil((panel.offsetHeight + gap) / (row + gap)));
        if (!span || Math.abs(span - need) > 1) {
          wrong.push(`${panel.dataset.panel}: spans ${span || 'auto'} rows, needs ${need}`);
        }
      }
      return { overflow: doc.scrollWidth - doc.clientWidth, wrong };
    });
    if (layout.overflow > 0) {
      problems.push(`${size.name}: page scrolls sideways by ${layout.overflow}px`);
    }
    for (const line of layout.wrong) problems.push(`${size.name}: ${line}`);
    const verdict = layout.wrong.length ? 'span drift' : 'packed sanely';
    console.log(`  ${size.name}: ${verdict}, overflow ${layout.overflow}px`);
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

    rbn = ThreadedTCP(("127.0.0.1", 0), RbnStub)
    rbn_port = rbn.server_address[1]
    Thread(target=rbn.serve_forever, daemon=True).start()

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

[[sources]]
id = "tle"
kind = "tle"
url = "http://127.0.0.1:{upstream_port}/amateur.txt"
local = true
interval = 86400

[[sources]]
id = "rbn"
kind = "rbn"
url = "telnet://127.0.0.1:{rbn_port}"
local = true
options = {{ callsign = "N0CALL", flush_seconds = 1 }}

[[sources]]
id = "solarflux"
kind = "swpc"
url = "http://127.0.0.1:{upstream_port}/f107.json"
local = true
interval = 300
options = {{ product = "f107_flux" }}

[[sources]]
id = "pskreporter"
kind = "pskreporter"
url = "http://127.0.0.1:{upstream_port}/psk"
local = true
interval = 300
options = {{ callsign = "N0CALL" }}

[[sources]]
id = "wspr"
kind = "wspr"
url = "http://127.0.0.1:{upstream_port}/wspr"
local = true
interval = 300
options = {{ callsign = "N0CALL" }}
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

            # Wait for the snapshots this run configures, rather than sleeping a
            # guessed number of seconds. A fixed sleep is wrong in both
            # directions: too short and the screenshots catch panels mid-start,
            # too long and every PR pays for the margin. Waiting on the files
            # also fails loudly if one never arrives, which a sleep cannot.
            expected = [
                "kindex.json",
                "solarflux.json",
                "tle.json",
                "satellites.json",
                "propagation.json",
                "rbn.json",
                "pskreporter.json",
                "wspr.json",
            ]
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                missing = [n for n in expected if not (work / "data" / n).exists()]
                if not missing:
                    break
                time.sleep(0.5)
            else:
                fail(f"the collector never produced {', '.join(missing)}")

            # The derived loops write a placeholder before their inputs land, so
            # the file existing is not the same as the panel having content.
            # One extra beat covers that; the satellite loop retries in five
            # seconds and the propagation one in fifteen.
            time.sleep(16)

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

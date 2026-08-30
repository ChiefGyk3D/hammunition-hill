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


# A DX cluster, spoken like a DXSpider node: a login prompt, then DX de
# lines. Until this stub existed the harness had no cluster at all, so the
# cluster stream client was never exercised end to end in CI and the DX
# CLUSTER panel only ever rendered its not-configured state here. G0ABC is
# the call the watch-notification scenario watches for.
CLUSTER_SPOTS = [
    "DX de W3LPL:     14025.0  G0ABC        CW 25 dB                    1234Z",
    "DX de K3LR:       7074.0  JA1XYZ       FT8 -11 dB                  1235Z",
    "DX de N2NT:      21205.0  VK2DEF       SSB loud                    1236Z",
]


class ClusterStub(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            self.wfile.write(b"login: ")
            self.wfile.flush()
            self.rfile.readline()
            for line in CLUSTER_SPOTS:
                self.wfile.write((line + "\r\n").encode())
            self.wfile.flush()
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

  // Watch notifications, armed before the first script runs: the Notification
  // constructor is replaced with a recorder (headless CI has no notification
  // tray to inspect), permission reads as granted, and the watch list already
  // contains G0ABC -- the call the cluster stub spots. Re-applied on every
  // navigation, so the assertion late in this run sees what the CURRENT page
  // fired on its first poll.
  await page.addInitScript(() => {
    window.__notifications = [];
    window.Notification = class {
      static permission = 'granted';
      static async requestPermission() { return 'granted'; }
      constructor(title, options) {
        window.__notifications.push({ title, body: options?.body ?? '' });
      }
    };
    localStorage.setItem('hh.watch.calls', JSON.stringify(['G0ABC']));
  });

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
  // put the page into edit mode and the rest of the loop into the weeds. The
  // about button repeated the failure the day it shipped: the census clicked
  // "about", the sheet it opened overlaid the tab bar, and the next tab click
  // timed out underneath it. Every non-dashboard control added to this bar
  // must be excluded here -- and covered by its own scenario below, because
  // "excluded from the census" must never come to mean "never exercised".
  const tabs = await page.$$eval(
    '#tabs button:not(.tab-edit):not(.tab-about):not(.tab-rotate)', (els) =>
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

  // --- the 2D map draws a world, and the path plotter tells the truth ------
  // Still on the Map tab. Switching to the flat projection must actually
  // paint one: a projection bug renders a clean empty rectangle with no
  // console error, so the check is pixel diversity, not absence of failure.
  // Then the plotted path's distance is compared against 9408 km -- the
  // DM79 -> PM95 great circle computed independently in Python when this
  // check was written, not by the code under test. (The first constant was
  // 9376, from mis-centring PM95 at 139.5°E instead of 139.0; the check
  // caught its own author's arithmetic before it caught anything else.)
  const mapPanel = '#grid .panel[data-panel="map"]';
  await page.click(`${mapPanel} .chip:text-is("2D")`);
  await page.waitForTimeout(600);
  const painted = await page.$eval(`${mapPanel} canvas`, (canvas) => {
    const ctx = canvas.getContext('2d');
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let diff = 0;
    const [r0, g0, b0] = [data[0], data[1], data[2]];
    for (let i = 0; i < data.length; i += 40) {
      const delta =
        Math.abs(data[i] - r0) + Math.abs(data[i + 1] - g0) + Math.abs(data[i + 2] - b0);
      if (delta > 30) diff += 1;
    }
    return diff;
  });
  if (painted < 500) {
    problems.push(
      `2D map: only ${painted} sampled pixels differ from the corner -- a blank projection`,
    );
  }
  await page.click(`${mapPanel} .chip:text-is("PLOT PATH")`);
  await page.waitForTimeout(300);
  await page.fill(`${mapPanel} .pmf-input`, 'PM95');
  await page.press(`${mapPanel} .pmf-input`, 'Enter');
  await page.waitForTimeout(500);
  const pathText = await page.$$eval(`${mapPanel} p.count`, (els) =>
    els.map((e) => e.textContent).find((t) => t.includes('km /')) ?? '');
  const km = Number((pathText.match(/(\d+) km/) || [])[1]);
  if (!km || Math.abs(km - 9408) > 30) {
    problems.push(`plot path: DM79 -> PM95 should read ~9408 km, got "${pathText}"`);
  }
  if (!/short \d+°/.test(pathText) || !/long \d+°/.test(pathText)) {
    problems.push(`plot path: caption is missing bearings: "${pathText}"`);
  }
  console.log(`  map tools: 2D painted ${painted} samples, path reads ${km} km`);
  // Put the panel back the way the screenshots expect it.
  await page.click(`${mapPanel} .chip:text-is("CLEAR")`);
  await page.click(`${mapPanel} .chip:text-is("PLOT PATH")`);
  await page.click(`${mapPanel} .chip:text-is("3D")`);
  await page.waitForTimeout(300);

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

  // --- the about card ----------------------------------------------------
  // Open it from the tab, demand the links that justify its existence, close
  // it, and prove the tab bar still works afterwards -- the exact sequence
  // that timed out when the census clicked "about" by accident.
  await page.click('#tabs .tab-about');
  await page.waitForTimeout(400);
  const aboutLinks = await page.$$eval('.about-sheet a', (els) => els.length);
  if (aboutLinks < 10) {
    problems.push(`about: expected the full link set, got ${aboutLinks}`);
  }
  const badLinks = await page.$$eval('.about-sheet a', (els) =>
    els.filter((a) => !a.href.startsWith('https://')).map((a) => a.href));
  if (badLinks.length) problems.push(`about: non-https links: ${badLinks.join(', ')}`);
  await page.click('#tabs .tab-about');
  await page.waitForTimeout(200);
  const sheetGone = await page.$('.about-sheet');
  if (sheetGone) problems.push('about: sheet did not close on second click');
  await page.click('#tabs button:text-is("Home")');
  await page.waitForTimeout(300);
  console.log(`  about: ${aboutLinks} links, opens and closes`);

  // --- an idle dashboard holds still --------------------------------------
  // The operator's report was "sluggish after a while", and the cause was
  // invisible to every check above: the tier 0 ticker rebuilt the exam
  // trainer, the CW quiz and the antenna tools from scratch every second,
  // thousands of nodes made and discarded per second while the page just sat
  // there. So this is measured structurally, not with a stopwatch: count the
  // nodes ADDED to the grid over five idle seconds. Only the panels that
  // declare a tick (the clock, the beacon slots) may rebuild, and they are
  // small on purpose. A stopwatch assertion would flake on a loaded CI
  // runner; a node count is the same on every machine.
  //
  // Operating, specifically: it carries every heavy tier 0 panel -- exam, CW,
  // tools, logbook, callsign -- so it is where the churn actually happened.
  // On Home the only tier 0 panel is the clock, and the bug barely registers.
  await page.click('#tabs button:text-is("Operating")');
  await page.waitForTimeout(1500);
  const idleChurn = await page.evaluate(() => new Promise((resolve) => {
    let added = 0;
    // Count the whole subtree of each added node, not just the node itself.
    // replaceChildren() reports its direct children as addedNodes with their
    // subtrees already attached, so `addedNodes.length` counts fragments --
    // the falsification run measured the resurrected bug at 150 against a
    // bound of 500, a check that passed on the exact thing it watches for.
    const watcher = new MutationObserver((records) => {
      for (const r of records) {
        for (const n of r.addedNodes) {
          added += 1 + (n.querySelectorAll ? n.querySelectorAll('*').length : 0);
        }
      }
    });
    watcher.observe(document.querySelector('#grid'), { childList: true, subtree: true });
    setTimeout(() => { watcher.disconnect(); resolve(added); }, 5000);
  }));
  // Measured: the beacon table's once-a-second rebuild puts a healthy
  // Operating tab at ~310 nodes per 5s; resurrecting the bug measured 2360.
  // The bound sits between with real margin on both sides.
  if (idleChurn > 900) {
    problems.push(
      `idle churn: ${idleChurn} DOM nodes added in 5 idle seconds -- ` +
        'something rebuilds panels that have nothing new to say',
    );
  }
  console.log(`  idle churn: ${idleChurn} nodes added in 5s`);

  // --- switching tabs does not accumulate ---------------------------------
  // Cycle every dashboard five times and demand the document come back to the
  // size one pass leaves it at. Growth here means a leak a person only meets
  // "after a while": listeners or nodes surviving the switch, compounding
  // until the wall display needs a nightly reload.
  const cycle = async () => {
    for (const tab of tabs) {
      await page.click(`#tabs button:text-is("${tab}")`);
      await page.waitForTimeout(250);
    }
    await page.click('#tabs button:text-is("Home")');
    await page.waitForTimeout(250);
  };
  await cycle();
  const nodesAfterOne = await page.evaluate(() => document.querySelectorAll('*').length);
  for (let i = 0; i < 4; i++) await cycle();
  const nodesAfterFive = await page.evaluate(() => document.querySelectorAll('*').length);
  if (nodesAfterFive > nodesAfterOne * 1.15) {
    problems.push(
      `tab cycling grows the DOM: ${nodesAfterOne} nodes after one pass, ` +
        `${nodesAfterFive} after five -- something survives the switch`,
    );
  }
  console.log(`  tab cycling: ${nodesAfterOne} -> ${nodesAfterFive} nodes over 5 cycles`);

  // --- clicks land --------------------------------------------------------
  // The sluggishness had a second face: a click that raced a rebuild hit a
  // button that had just been thrown away, and did nothing. Chips carry their
  // own state change (the .on class moves), so click each exam element chip
  // and demand the state actually moved -- a detached-button click fails this
  // structurally, no timing involved. The wait is one poll interval plus a
  // tick, long enough for the old bug to fire between mousedown and check.
  await page.click('#tabs button:text-is("Operating")');
  await page.waitForTimeout(1100);
  // Labels first, elements per click: a chip click legitimately rebuilds the
  // panel, so a handle held across one is detached by design, not by bug.
  const chipLabels = await page.$$eval(
    '#grid .panel[data-panel="exam"] .cw-tabs:not(.cw-subtabs) .chip',
    (els) => els.map((e) => e.textContent.trim()),
  );
  const elementRow = '#grid .panel[data-panel="exam"] .cw-tabs:not(.cw-subtabs)';
  for (const label of chipLabels) {
    await page.click(`${elementRow} .chip:text-is("${label}")`);
    await page.waitForTimeout(1100);
    const lit = await page.$eval(
      '#grid .panel[data-panel="exam"] .cw-tabs:not(.cw-subtabs) .chip.on',
      (e) => e.textContent.trim(),
    ).catch(() => null);
    if (lit !== label) {
      problems.push(
        `exam chip "${label}" clicked but "${lit}" is selected -- the click was lost`,
      );
    }
  }
  if (chipLabels.length) {
    console.log(`  clicks land: ${chipLabels.length} exam chips held their selection`);
  }
  await page.click('#tabs button:text-is("Home")');
  await page.waitForTimeout(400);

  // --- the callsign is editable in the header ------------------------------
  // Presentation-only by design: the override lives in this browser and the
  // hint says so. The checks are the honest lifecycle -- set, survive a
  // reload, reset -- because a header that forgets on refresh teaches the
  // operator the feature is broken.
  await page.click('#station .station-edit');
  await page.fill('#station .station-input', 'W1AW/3');
  await page.press('#station .station-input', 'Enter');
  await page.waitForTimeout(200);
  let header = await page.$eval('#station', (e) => e.textContent);
  if (!header.includes('W1AW/3')) {
    problems.push(`callsign: set W1AW/3 but the header reads "${header}"`);
  }
  await page.reload({ waitUntil: 'load' });
  await page.waitForTimeout(1200);
  header = await page.$eval('#station', (e) => e.textContent);
  if (!header.includes('W1AW/3')) {
    problems.push(`callsign: override did not survive a reload -- header reads "${header}"`);
  }
  await page.click('#station .station-edit');
  await page.fill('#station .station-input', '');
  await page.press('#station .station-input', 'Enter');
  await page.waitForTimeout(200);
  header = await page.$eval('#station', (e) => e.textContent);
  if (!header.includes('N0CALL')) {
    problems.push(`callsign: clearing should return to config's N0CALL, header reads "${header}"`);
  }

  // A station with no callsign must OFFER one, not render a blank corner --
  // served here by stripping the field in flight, since the harness config
  // sensibly has one.
  const bare = await browser.newPage({ viewport: { width: 1400, height: 400 } });
  await bare.route('**/data/station.json', async (route) => {
    const res = await route.fetch();
    const body = JSON.parse(await res.text());
    delete body.data.callsign;
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await bare.goto(BASE, { waitUntil: 'domcontentloaded' });
  await bare.waitForSelector('#station .station-edit', { timeout: 15000 });
  const unset = await bare.$eval('#station', (e) => e.textContent);
  if (!unset.toLowerCase().includes('set callsign')) {
    problems.push(
      `callsign: with none configured the header reads "${unset}", not an offer to set one`,
    );
  }
  await bare.close();
  console.log(`  callsign: set, kept over reload, reset; unset offers "${unset.trim()}"`);

  // --- kiosk rotation actually rotates, and off means off ------------------
  // Excluded from the census above, so per the standing rule it gets its own
  // scenario. The interval is dropped to 2s through the same localStorage key
  // an operator would use; the click that enables rotation counts as the last
  // interaction, so one interval of stillness must pass before the first turn.
  await page.evaluate(() => localStorage.setItem('hh.rotate.seconds', '2'));
  await page.reload({ waitUntil: 'load' });
  await page.waitForTimeout(1000);
  const tabBefore = await page.$eval('#tabs .tab.on', (e) => e.textContent);
  await page.click('#tabs .tab-rotate');
  await page.waitForTimeout(3500);
  const tabAfter = await page.$eval('#tabs .tab.on', (e) => e.textContent);
  if (tabAfter === tabBefore) {
    problems.push(`rotate: enabled at 2s and still on "${tabBefore}" after 3.5s of stillness`);
  }
  await page.click('#tabs .tab-rotate');  // off
  const tabParked = await page.$eval('#tabs .tab.on', (e) => e.textContent);
  await page.waitForTimeout(3000);
  const tabStill = await page.$eval('#tabs .tab.on', (e) => e.textContent);
  if (tabStill !== tabParked) {
    problems.push(`rotate: switched OFF on "${tabParked}" but drifted to "${tabStill}"`);
  }
  await page.evaluate(() => localStorage.removeItem('hh.rotate.seconds'));
  await page.click('#tabs button:text-is("Home")');
  await page.waitForTimeout(300);
  console.log(`  rotate: turned ${tabBefore} -> ${tabAfter}, then held ${tabParked} when off`);

  // --- watch notifications fire, once, for the watched call ----------------
  // The cluster stub spotted G0ABC; the init script put G0ABC on the watch
  // list and recorded what Notification was asked to show. The page has been
  // through at least one poll since its last reload, so the recorder must
  // hold exactly one G0ABC alert -- zero means the wiring is dead, and the
  // dedupe rule is unit-checked below where timing cannot blur it.
  const fired = await page.evaluate(() => window.__notifications);
  const g0abc = fired.filter((n) => n.title.includes('G0ABC'));
  if (g0abc.length !== 1) {
    problems.push(
      `watch: expected exactly one G0ABC notification, got ${g0abc.length} ` +
        `of ${fired.length} total: ${JSON.stringify(fired).slice(0, 200)}`,
    );
  } else {
    console.log(`  watch: notified "${g0abc[0].title}" -- ${g0abc[0].body}`);
  }
  const watchUi = await page.$('#grid .panel[data-panel="spots"] .watch-input');
  if (!watchUi) problems.push('watch: no watch-list input in the spots panel');

  // The pure functions, unit-tested in the page -- the only unit rig web/
  // has. Dedupe, base-call matching, expiry, and the band-opening diff.
  const watchUnits = await page.evaluate(async () => {
    const m = await import('./lib/watch.js');
    const failures = [];
    const spot = { call: 'W1AW/3', band: '20m' };
    const first = m.matchSpots(['W1AW'], [spot], new Map(), 1000);
    if (first.alerts.length !== 1) failures.push('base-call match missed W1AW/3');
    const again = m.matchSpots(['W1AW'], [spot], first.seen, 2000);
    if (again.alerts.length !== 0) failures.push('dedupe re-alerted inside the window');
    const later = m.matchSpots(['W1AW'], [spot], first.seen, 1000 + 31 * 60 * 1000);
    if (later.alerts.length !== 1) failures.push('expired entry did not re-alert');
    const opened = m.newlyOpen(
      [{ band: '20m', level: 'warn' }, { band: '40m', level: 'good' }],
      [{ band: '20m', level: 'good' }, { band: '40m', level: 'good' }],
    );
    if (opened.length !== 1 || opened[0].band !== '20m') {
      failures.push(`newlyOpen returned ${JSON.stringify(opened)}`);
    }
    return failures;
  });
  for (const failure of watchUnits) problems.push(`watch units: ${failure}`);
  if (!watchUnits.length) console.log('  watch units: match, dedupe, expiry, band diff ok');

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

    cluster = ThreadedTCP(("127.0.0.1", 0), ClusterStub)
    cluster_port = cluster.server_address[1]
    Thread(target=cluster.serve_forever, daemon=True).start()

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
id = "cluster"
kind = "dxcluster"
url = "telnet://127.0.0.1:{cluster_port}"
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
                "cluster.json",
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

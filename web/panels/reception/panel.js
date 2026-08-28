// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can see one at https://mozilla.org/MPL/2.0/.

// Reception reports: every station that decoded YOUR signal.
//
// The RBN panel answers "is my signal getting out" for CW. This one answers
// it for the digital modes -- PSK Reporter carries the FT8/FT4/JS8 decodes of
// you, WSPR carries the beacon decodes -- merged newest-first, because the
// question is the same whichever network answered it.
//
// The SNR thresholds are per-family, not the RBN's: +6 dB is armchair copy on
// CW and impossible on WSPR, where -10 dB is a strong signal and decodes run
// to -28. A colour scale that ignored that would paint every WSPR report red.

import { distanceKm, gridToLatLon } from "../../lib/callsign.js";
import { bandColor } from "../../lib/bandcolors.js";

const MAX_ROWS = 18;

function snrClass(mode, db) {
  if (db == null) return "";
  const wspr = mode === "WSPR";
  if (db >= (wspr ? -10 : -5)) return "rbn-strong";
  if (db >= (wspr ? -23 : -18)) return "rbn-fair";
  return "rbn-weak";
}

function reportLocation(report) {
  if (report.lat != null && report.lon != null) {
    return { lat: report.lat, lon: report.lon };
  }
  if (report.grid) {
    const fromGrid = gridToLatLon(report.grid);
    if (fromGrid) return { lat: fromGrid[0], lon: fromGrid[1] };
  }
  return null;
}

function reportDistanceKm(report, station) {
  if (report.distance_km != null) return report.distance_km;
  if (!station?.located) return null;
  const at = reportLocation(report);
  if (!at) return null;
  return distanceKm(station.lat, station.lon, at.lat, at.lon);
}

function merged(data) {
  const reports = [
    ...(data.pskreporter?.data?.spots ?? []),
    ...(data.wspr?.data?.spots ?? []),
  ];
  reports.sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
  return reports;
}

export function render(root, { data, station, el }) {
  const psk = data.pskreporter?.data;
  const wspr = data.wspr?.data;
  if (!psk && !wspr) {
    root.replaceChildren(
      el(
        "p",
        "empty",
        "no reception sources configured — add a pskreporter or wspr source " +
          "with your callsign in options (docs/CONFIGURATION.md) and every " +
          "station that decodes you shows up here",
      ),
    );
    return;
  }

  const reports = merged(data);
  const who = psk?.call ?? wspr?.call ?? "you";
  if (!reports.length) {
    root.replaceChildren(
      el(
        "p",
        "empty",
        `no reports of ${who} in the window yet — transmit on a digital mode ` +
          `(or a WSPR beacon) and the stations that decode you appear here`,
      ),
    );
    return;
  }

  // Five columns, not the RBN's six: every report is inside a short window
  // by construction, so an age column would read "2m" eighteen times while
  // the callsign -- the actual datum -- got ellipsised in a narrow panel.
  const list = el("div", "rbn-list");
  for (const report of reports.slice(0, MAX_ROWS)) {
    const row = el("div", "rbn-row rcp-row");
    const band = el("span", "rbn-band", report.band || (report.khz ? `${Math.round(report.khz)}` : ""));
    if (report.band) band.style.color = bandColor(report.band);
    const km = reportDistanceKm(report, station);
    row.append(
      el("span", "rbn-spotter", report.call),
      el("span", `rbn-snr ${snrClass(report.mode, report.snr)}`, report.snr != null ? `${report.snr} dB` : ""),
      band,
      el("span", "rbn-mode", report.mode || ""),
      el("span", "rcp-km", km != null ? `${Math.round(km)} km` : ""),
    );
    list.append(row);
  }

  const parts = [list];
  const sources = [
    psk ? `PSK Reporter (${psk.count} in ${psk.window_minutes} min)` : null,
    wspr ? `WSPR (${wspr.count} in ${wspr.window_minutes} min)` : null,
  ].filter(Boolean);
  const stations = new Set(reports.map((r) => r.call)).size;
  parts.push(
    el(
      "p",
      "rbn-note",
      `${reports.length} reports of ${who} from ${stations} stations, ` +
        `newest first — ${sources.join(", ")}`,
    ),
  );
  root.replaceChildren(...parts);
}

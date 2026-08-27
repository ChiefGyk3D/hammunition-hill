// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Upcoming passes, already computed.
//
// Unlike the CW and tools panels this one does no arithmetic: SGP4 belongs in
// one place where it can be tested, and that place is the collector. The panel
// reads a list and counts down to it, which is the one thing it must do on its
// own clock -- a pass list that says "in 4 minutes" and means it when the
// snapshot was written five minutes ago would be worse than useless.

import { relativeAge } from "../../lib/format.js";
import { compassPoint } from "../../lib/callsign.js";

function countdown(iso, now) {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  if (seconds < 0) return null;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  // The window is a day, so days should not appear -- but a stale snapshot or a
  // widened window would otherwise render "in 3845h 12m", which is not a
  // number anybody reads. Degrade to something legible instead.
  if (hours < 48) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

// Twenty-four hour, always. A pass at "07:45" is unambiguous; the same pass as
// "07:45 AM" is two characters of noise that wrapped this column onto a second
// line, and the twelve-hour clock is not what anybody logs a contact in.
function clockTime(iso) {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// A pass you can work and a pass that clips a hedge are different events, and
// the difference is elevation. Three bands rather than a gradient, because a
// gradient asks the reader to interpolate a colour.
function grade(elevation) {
  if (elevation >= 45) return "sat-high";
  if (elevation >= 20) return "sat-mid";
  return "sat-low";
}

export function render(root, { data, el }) {
  const snapshot = data.satellites;
  if (!snapshot?.data) {
    root.replaceChildren(el("p", "empty", "waiting for the first pass calculation…"));
    return;
  }
  const payload = snapshot.data;

  if (!payload.available) {
    root.replaceChildren(el("p", "empty", payload.reason || "pass prediction unavailable"));
    return;
  }

  const parts = [];
  const now = Date.now();
  const upcoming = payload.passes || [];

  if (!upcoming.length) {
    parts.push(
      el(
        "p",
        "empty",
        `nothing above ${payload.min_elevation}° from ${payload.grid} ` +
          `in the next ${payload.window_hours} hours`,
      ),
    );
    root.replaceChildren(...parts);
    return;
  }

  const table = el("div", "sat-list");
  for (const item of upcoming) {
    const away = countdown(item.rise, now);
    // A pass whose rise time has gone but whose set time has not is happening
    // now, and saying so is the most useful thing this panel does.
    const overhead = away === null && new Date(item.set).getTime() > now;

    const row = el("div", "sat-row" + (overhead ? " sat-now" : ""));
    row.append(
      el("span", "sat-name", item.name),
      // toFixed, because 14.0 serialises as 14 and a column of "56.7, 14, 9.7"
      // reads as three different kinds of number.
      el("span", `sat-el ${grade(item.max_elevation)}`, `${item.max_elevation.toFixed(1)}°`),
      el("span", "sat-when", overhead ? "now" : away === null ? "—" : `in ${away}`),
      el("span", "sat-clock", `${clockTime(item.rise)}–${clockTime(item.set)}`),
      el(
        "span",
        "sat-track",
        `${compassPoint(item.rise_azimuth)} → ${compassPoint(item.peak_azimuth)} ` +
          `→ ${compassPoint(item.set_azimuth)}`,
      ),
      el("span", "sat-dur", `${Math.round(item.duration_seconds / 60)}m`),
    );
    table.append(row);
  }
  parts.push(table);

  const age = payload.elements_from ? relativeAge(payload.elements_from) : "unknown age";
  parts.push(
    el(
      "p",
      "sat-note",
      `${payload.tracked} satellite${payload.tracked === 1 ? "" : "s"} · ` +
        `above ${payload.min_elevation}° from ${payload.grid} · ` +
        `elements ${age}`,
    ),
  );
  parts.push(
    el(
      "p",
      "sat-note",
      "Computed here from cached elements — nothing was asked of anyone to " +
        "produce this list, and it keeps working with the WAN unplugged.",
    ),
  );

  root.replaceChildren(...parts);
}

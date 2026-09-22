// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Meteor showers, for the operators who work them rather than watch them.
//
// A shower calendar is easy and half useless: knowing the Perseids peak on the
// 12th does not tell you whether to be on 6 m at 4 AM. The two things that do
// are whether the shower is running at all, and **where its radiant is in your
// sky right now** -- which is a computation, needs your grid square, and is
// the reason this panel is worth more than the wall chart it replaces.
//
// Tier 0 throughout. The radiants ship in web/meteors.json as right ascension
// and declination; turning one into a look angle is a sidereal-time
// subtraction in ../../lib/ephemeris.js, mirrored and drift-tested against the
// Python side. Nothing is fetched, so this works on a hilltop with no signal,
// which is where meteor scatter is actually attempted.
//
// Three honest caveats live on the panel rather than in this comment, because
// they change what an operator should do:
//
//   * ZHR is a *visual* rate under a perfect sky. Radio reflections are a
//     different population -- fainter, and biased toward the fast showers --
//     so a big ZHR is a hint, not a forecast.
//   * Sporadic meteors deliver usable pings every day of the year. A shower
//     raises the rate; it does not create it, and the panel says so on the
//     days when nothing is running.
//   * A radiant directly overhead is the *worst* case, not the best. Reflection
//     needs the trail broadside to the path, which wants the radiant low.

import { effectiveStation } from "../../lib/geolocate.js";
import { compassPoint } from "../../lib/callsign.js";
import { celestialSubpoint, lookAngles } from "../../lib/ephemeris.js";

const state = { data: null, loading: false, error: null, showAll: false, rerender: null };

// Elevation band where a radiant is most useful for scatter. Below the horizon
// there is nothing to reflect from; directly overhead the geometry is wrong --
// a trail is a mirror, and it has to lie broadside to the path. Between about
// 15 and 55 degrees is where the useful trails form for typical VHF distances.
const BEST_LOW = 15;
const BEST_HIGH = 55;

/** Day-of-year for a "MM-DD" string in a given year, as a UTC timestamp. */
function dateIn(year, monthDay) {
  const [month, day] = monthDay.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

/**
 * How far through its run a shower is, handling the ones that wrap the year.
 *
 * The Quadrantids start on 28 December and peak on 3 January, so a naive
 * comparison puts the start after the end and reports the shower as never
 * running -- which is how the strongest shower of the year goes missing from a
 * calendar for its entire duration.
 *
 * Exported so tests/test_meteors.py can run it under node against the shipped
 * table. Date arithmetic that wraps a year is exactly the kind of thing that
 * looks right, renders plausibly, and is wrong for one week in twelve.
 */
export function showerWindow(shower, now) {
  const year = now.getUTCFullYear();
  const wraps = dateIn(2000, shower.start) > dateIn(2000, shower.end);

  // Try this year's run and the one that began last year; take whichever
  // contains now, else whichever peak is nearest ahead.
  const candidates = [];
  for (const offset of wraps ? [-1, 0] : [-1, 0, 1]) {
    const start = dateIn(year + offset, shower.start);
    const end = dateIn(year + offset + (wraps ? 1 : 0), shower.end);
    const peakYear = dateIn(2000, shower.peak) < dateIn(2000, shower.start) ? 1 : 0;
    const peak = dateIn(year + offset + (wraps ? peakYear : 0), shower.peak);
    candidates.push({ start, end, peak });
  }

  const at = now.getTime();
  const live = candidates.find((c) => at >= c.start && at <= c.end);
  const chosen =
    live ??
    candidates
      .filter((c) => c.peak >= at)
      .sort((a, b) => a.peak - b.peak)[0] ??
    candidates[candidates.length - 1];

  return {
    ...chosen,
    active: Boolean(live),
    daysToPeak: (chosen.peak - at) / 86400000,
  };
}

/** A one-word read on whether this shower is worth pointing an antenna at. */
export function verdictFor(shower, run, elevation) {
  if (!run.active) return { label: "—", cls: "muted" };
  if (elevation <= 0) return { label: "radiant down", cls: "muted" };
  const nearPeak = Math.abs(run.daysToPeak) <= 1.5;
  const inBand = elevation >= BEST_LOW && elevation <= BEST_HIGH;
  if (nearPeak && inBand) return { label: "prime", cls: "met-prime" };
  if (inBand) return { label: "good geometry", cls: "met-good" };
  if (elevation > BEST_HIGH) return { label: "radiant too high", cls: "met-fair" };
  return { label: "radiant low", cls: "met-fair" };
}

function whenText(run) {
  const days = run.daysToPeak;
  if (Math.abs(days) < 0.5) return "peaks today";
  if (days > 0) return `peaks in ${Math.round(days)}d`;
  return `peaked ${Math.round(-days)}d ago`;
}

export function render(root, { data, el }) {
  state.rerender = () => render(root, { data, el });

  if (!state.data && !state.loading) {
    state.loading = true;
    fetch("./meteors.json")
      .then((r) => r.json())
      .then((payload) => {
        state.data = payload;
      })
      .catch((err) => {
        state.error = err.message;
      })
      .finally(() => {
        state.loading = false;
        state.rerender();
      });
    root.replaceChildren(el("p", "empty", "loading shower table…"));
    return;
  }
  if (state.error) {
    root.replaceChildren(el("p", "error", `shower table: ${state.error}`));
    return;
  }
  if (!state.data) return;

  const station = effectiveStation(data.station?.data ?? {});
  const now = new Date();

  const rows = state.data.showers.map((shower) => {
    const run = showerWindow(shower, now);
    let look = null;
    if (station.located) {
      const point = celestialSubpoint(shower.ra, shower.dec, now);
      look = lookAngles(station.lat, station.lon, point.lat, point.lon);
    }
    return { shower, run, look };
  });

  // Active showers first, then by how soon they peak. An operator opening this
  // panel wants tonight, not an almanac.
  rows.sort((a, b) => {
    if (a.run.active !== b.run.active) return a.run.active ? -1 : 1;
    return Math.abs(a.run.daysToPeak) - Math.abs(b.run.daysToPeak);
  });

  const active = rows.filter((r) => r.run.active);
  const shown = state.showAll ? rows : active.length ? active : rows.slice(0, 3);

  const parts = [];

  const table = el("table", "meteors");
  const head = el("tr");
  for (const label of ["Shower", "Peak", "ZHR", "km/s", "Radiant", "Scatter"]) {
    head.append(el("th", null, label));
  }
  const thead = el("thead");
  thead.append(head);
  table.append(thead);

  const body = el("tbody");
  for (const { shower, run, look } of shown) {
    const row = el("tr");
    if (!run.active) row.classList.add("met-off");

    const name = el("td", "met-name", shower.name);
    if (shower.daytime) {
      name.append(el("span", "met-tag", "DAYTIME"));
    }
    if (shower.note) name.title = shower.note;

    const zhr = shower.zhr > 0 ? String(shower.zhr) : "var";

    row.append(
      name,
      el("td", "met-when", whenText(run)),
      el("td", "met-zhr", zhr),
      el("td", "met-vel", String(shower.velocity_kms)),
      el(
        "td",
        "met-radiant",
        look
          ? `${Math.round(look.azimuth)}° ${compassPoint(look.azimuth)} · ${look.elevation.toFixed(0)}°`
          : "set your grid",
      ),
    );

    const verdict = verdictFor(shower, run, look ? look.elevation : -1);
    row.append(el("td", `met-verdict ${verdict.cls}`, verdict.label));
    body.append(row);
  }
  table.append(body);
  parts.push(table);

  const toggle = el("button", "chip" + (state.showAll ? " on" : ""), "ALL SHOWERS");
  toggle.type = "button";
  toggle.setAttribute("aria-pressed", String(state.showAll));
  toggle.addEventListener("click", () => {
    state.showAll = !state.showAll;
    state.rerender();
  });
  const chips = el("div", "chips");
  chips.append(toggle);
  parts.push(chips);

  if (!active.length) {
    parts.push(
      el(
        "p",
        "empty",
        "no major shower running — sporadics still give usable pings every day, " +
          "best in the hours before dawn",
      ),
    );
  }

  parts.push(
    el(
      "p",
      "count",
      "ZHR is the visual rate under a perfect sky, not what you will hear: " +
        "radio favours the fast showers and the daytime ones nobody can see. " +
        `A radiant between ${BEST_LOW}° and ${BEST_HIGH}° is the useful band — ` +
        "overhead is worse than low, because a trail has to lie broadside to the path.",
    ),
  );

  if (!station.located) {
    parts.push(el("p", "empty", "set [station] grid for radiant look angles"));
  }

  root.replaceChildren(...parts);
}

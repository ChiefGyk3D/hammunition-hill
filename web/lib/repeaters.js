// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The repeaters panel's logic, with no DOM and no storage.
//
// Pure functions over rows the collector already computed (distance, bearing
// and band are the collector's; nothing here asks anyone for anything). Kept
// apart from the panel so tests/test_repeaters_js.py can run it under node
// against a real snapshot, and so the map's repeater layer filters with the
// same code the table does -- two copies of "within N km" would disagree.

export const DEFAULT_FILTERS = Object.freeze({
  band: null,
  mode: null,
  source: null,
  withinKm: null,
});

const COMPASS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];

/** The rows that pass every filter that is set. Never mutates its input. */
export function filterRows(rows, filters = DEFAULT_FILTERS) {
  const { band, mode, source, withinKm } = { ...DEFAULT_FILTERS, ...filters };
  const limit = Number.isFinite(withinKm) && withinKm > 0 ? withinKm : null;
  return rows.filter((row) => {
    if (band && row.band !== band) return false;
    if (mode && row.mode !== mode) return false;
    if (source && row.source !== source && !(row.also ?? []).includes(source)) return false;
    // A distance limit cannot be met by a row with no distance. Showing it
    // anyway would claim a repeater is near on no evidence.
    if (limit !== null && !(typeof row.km === "number" && row.km <= limit)) return false;
    return true;
  });
}

/** What the filter rows offer: only what is present, bands low to high. */
export function facets(rows) {
  const bandOrder = [];
  const modes = new Map();
  const sources = new Set();
  for (const row of rows) {
    if (row.band && !bandOrder.includes(row.band)) bandOrder.push(row.band);
    if (row.mode) modes.set(row.mode, (modes.get(row.mode) ?? 0) + 1);
    if (row.source) sources.add(row.source);
    for (const also of row.also ?? []) sources.add(also);
  }
  return {
    bands: bandOrder.sort((a, b) => bandWeight(a) - bandWeight(b)),
    modes: [...modes.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([m]) => m),
    sources: [...sources].sort(),
  };
}

// Wavelength order, long to short: the order operators read a band list in.
const BANDS = ["2190m", "630m", "160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m",
  "12m", "10m", "6m", "4m", "2m", "1.25m", "70cm", "33cm", "23cm"];

function bandWeight(band) {
  const at = BANDS.indexOf(band);
  return at === -1 ? BANDS.length : at;
}

/** 146940000 -> "146.940". Zero is "no frequency", not 0 MHz. */
export function mhz(hz) {
  if (!hz) return "—";
  return (hz / 1e6).toFixed(3);
}

/** The offset in MHz, signed: "-0.6", "+5". Null is unknown; zero is simplex. */
export function offsetLabel(hz) {
  if (hz === null || hz === undefined) return "—";
  if (hz === 0) return "simplex";
  const value = Number((hz / 1e6).toFixed(3));
  return `${value > 0 ? "+" : ""}${value}`;
}

export function bearingLabel(bearing) {
  if (typeof bearing !== "number") return "—";
  const point = COMPASS[Math.floor((((bearing % 360) + 360) % 360) / 22.5 + 0.5) % 16];
  return `${Math.round(bearing)}° ${point}`;
}

/** Whole kilometres from 100 up, one decimal below: 14.0 km reads as 14, 153.2 as 153. */
export function kmLabel(km) {
  if (typeof km !== "number") return "—";
  return km >= 100 ? `${Math.round(km)} km` : `${km.toFixed(1)} km`;
}

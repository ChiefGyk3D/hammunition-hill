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

// --- the chosen centre ------------------------------------------------------
//
// Distances default to the station's grid square, computed by the collector, so
// the first paint needs no arithmetic. An operator may pick any other point; the
// numbers are then recomputed here, in the browser, from rows already in the
// snapshot. The centre is never sent anywhere: it lives in this browser's
// localStorage and in nothing else. This is the same great-circle and Maidenhead
// maths as geo.py (the collector's copy); the test pins both to the same pairs.

const EARTH_RADIUS_KM = 6371.0088; // IUGG mean radius, as geo.py

export const CENTRE_KEY = "hh.repeaters.centre";
export const CENTRE_EVENT = "hh:repeaters-centre";

/** The centre of a 4- or 6-character Maidenhead square, or null. */
export function parseGrid(text) {
  const grid = String(text ?? "").trim();
  if (!/^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$/.test(grid)) return null;
  const g = grid.toUpperCase();
  let lon = (g.charCodeAt(0) - 65) * 20 - 180 + Number(g[2]) * 2;
  let lat = (g.charCodeAt(1) - 65) * 10 - 90 + Number(g[3]);
  let lonSpan = 2;
  let latSpan = 1;
  if (g.length === 6) {
    lon += (g.charCodeAt(4) - 65) * (2 / 24);
    lat += (g.charCodeAt(5) - 65) * (1 / 24);
    lonSpan = 2 / 24;
    latSpan = 1 / 24;
  }
  return { lat: lat + latSpan / 2, lon: lon + lonSpan / 2, grid: g.length === 6 ? g.slice(0, 4) + g.slice(4).toLowerCase() : g };
}

/** "41.7, -72.7" or "41.7 -72.7" to {lat, lon}, or null when out of range. */
export function parseLatLon(text) {
  const parts = String(text ?? "").trim().split(/\s*,\s*|\s+/);
  if (parts.length !== 2 || parts.some((p) => !/^[-+]?\d+(\.\d+)?$/.test(p))) return null;
  const [lat, lon] = parts.map(Number);
  if (!(lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180)) return null;
  return { lat, lon };
}

const pointLabel = (lat, lon) => `${lat.toFixed(3)}, ${lon.toFixed(3)}`;

/** A centre from a point on the map or a typed pair. */
export function centreFromPoint(lat, lon) {
  return { kind: "point", lat, lon, label: pointLabel(lat, lon) };
}

/**
 * A centre from whatever was typed: a grid square, then a coordinate pair.
 * Null when it is neither. A place NAME is not understood, on purpose: turning
 * a name into a point is a lookup, and nothing here asks anyone anything.
 */
export function parseCentre(text) {
  const grid = parseGrid(text);
  if (grid) return { kind: "grid", lat: grid.lat, lon: grid.lon, label: grid.grid };
  const point = parseLatLon(text);
  return point ? centreFromPoint(point.lat, point.lon) : null;
}

export function distanceKm(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180;
  const dPhi = (lat2 - lat1) * rad;
  const dLambda = (lon2 - lon1) * rad;
  const a =
    Math.sin(dPhi / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLambda / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

export function bearingDeg(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180;
  const dLambda = (lon2 - lon1) * rad;
  const y = Math.sin(dLambda) * Math.cos(lat2 * rad);
  const x =
    Math.cos(lat1 * rad) * Math.sin(lat2 * rad) -
    Math.sin(lat1 * rad) * Math.cos(lat2 * rad) * Math.cos(dLambda);
  return ((Math.atan2(y, x) / rad) + 360) % 360;
}

/** Rows with km and bearing measured from `centre`, nearest first. A copy. */
export function withCentre(rows, centre) {
  return rows
    .map((row) => ({
      ...row,
      km: Math.round(distanceKm(centre.lat, centre.lon, row.lat, row.lon) * 10) / 10,
      bearing: Math.round(bearingDeg(centre.lat, centre.lon, row.lat, row.lon) * 10) / 10,
    }))
    .sort((a, b) => a.km - b.km || String(a.callsign).localeCompare(String(b.callsign)));
}

export const COVERAGE_KM = 250; // the radius assumed when no "within" is set

/**
 * Said when the centre is far from every repeater this machine holds. The data
 * is only the layers imported into Hammunition, so "anywhere" is not
 * "worldwide": an empty area is a gap in what was imported, and the note names
 * the commands that fill it. Null when something is near enough.
 */
export function coverageNote(rows, withinKm) {
  const radius = Number.isFinite(withinKm) && withinKm > 0 ? withinKm : COVERAGE_KM;
  const kms = rows.map((r) => r.km).filter((k) => typeof k === "number");
  const nearest = kms.length ? Math.min(...kms) : null;
  if (nearest !== null && nearest <= radius) return null;
  const how =
    "Repeaters here are only the layers imported into Hammunition, not worldwide data: run " +
    "`hammunition maps repeaters fetch-repeaterbook --state CODE` or " +
    "`hammunition maps repeaters import --from-osm` for this area.";
  return nearest === null
    ? `No repeaters on this machine. ${how}`
    : `The nearest repeater on this machine is ${Math.round(nearest)} km from here, beyond ${radius} km. ${how}`;
}

// --- remembering it ---------------------------------------------------------
// `storage` is localStorage in the browser and a stand-in in tests. Every access
// is guarded: private windows throw, and a forgotten centre is not worth a
// broken panel.

export function loadCentre(storage) {
  try {
    const raw = JSON.parse(storage.getItem(CENTRE_KEY));
    if (raw && Number.isFinite(raw.lat) && Number.isFinite(raw.lon) &&
        Math.abs(raw.lat) <= 90 && Math.abs(raw.lon) <= 180) {
      return {
        kind: raw.kind === "grid" ? "grid" : "point",
        lat: raw.lat,
        lon: raw.lon,
        label: String(raw.label ?? pointLabel(raw.lat, raw.lon)).slice(0, 40),
      };
    }
  } catch {
    // Unreadable or absent: the station is the centre.
  }
  return null;
}

export function saveCentre(storage, centre) {
  try {
    storage.setItem(CENTRE_KEY, JSON.stringify(centre));
  } catch {
    // Not remembered; still in effect for this view.
  }
}

export function clearCentre(storage) {
  try {
    storage.removeItem(CENTRE_KEY);
  } catch {
    // Nothing to clear.
  }
}

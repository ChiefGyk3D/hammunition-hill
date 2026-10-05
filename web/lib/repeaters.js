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

// The engine's mode vocabulary, in its order (Hammunition's repeaters.MODES).
// Digital is everything that is not analog: the shortcut chips select by these.
export const MODES = Object.freeze(
  ["FM", "DMR", "D-STAR", "YSF", "P25", "NXDN", "M17", "TETRA", "ATV"]);
export const ANALOG_MODES = Object.freeze(["FM", "ATV"]);
export const DIGITAL_MODES = Object.freeze(MODES.filter((m) => !ANALOG_MODES.includes(m)));

export const DEFAULT_FILTERS = Object.freeze({
  bands: Object.freeze([]),
  modes: Object.freeze([]),
  source: null,
  withinKm: null,
});

const COMPASS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];

/**
 * The rows that pass every filter that is set. Never mutates its input.
 * Several bands or modes are an OR within themselves (a row on any chosen band,
 * speaking any chosen mode) and an AND with each other and with source and
 * distance. A row whose modes are unknown passes no mode chip: saying it speaks
 * DMR on no evidence is the one thing a mode filter must not do.
 */
export function filterRows(rows, filters = DEFAULT_FILTERS) {
  const { bands, modes, source, withinKm } = { ...DEFAULT_FILTERS, ...filters };
  const limit = Number.isFinite(withinKm) && withinKm > 0 ? withinKm : null;
  const wantBands = Array.isArray(bands) && bands.length ? bands : null;
  const wantModes = Array.isArray(modes) && modes.length ? modes : null;
  return rows.filter((row) => {
    if (wantBands && !wantBands.includes(row.band)) return false;
    if (wantModes && !(row.modes ?? []).some((m) => wantModes.includes(m))) return false;
    if (source && row.source !== source && !(row.also ?? []).includes(source)) return false;
    // A distance limit cannot be met by a row with no distance. Showing it
    // anyway would claim a repeater is near on no evidence.
    if (limit !== null && !(typeof row.km === "number" && row.km <= limit)) return false;
    return true;
  });
}

/**
 * What the filter rows offer: only what is present. Bands low to high, modes in
 * the vocabulary's order, each with how many rows have it (a row on two modes
 * counts under both). A snapshot from an engine without the vocabulary has no
 * modes, so no mode chips.
 */
export function facets(rows) {
  const bandCounts = {};
  const modeCounts = {};
  const sources = new Set();
  for (const row of rows) {
    if (row.band) bandCounts[row.band] = (bandCounts[row.band] ?? 0) + 1;
    for (const mode of row.modes ?? []) modeCounts[mode] = (modeCounts[mode] ?? 0) + 1;
    if (row.source) sources.add(row.source);
    for (const also of row.also ?? []) sources.add(also);
  }
  const bands = Object.keys(bandCounts).sort((a, b) => bandWeight(a) - bandWeight(b));
  const modes = MODES.filter((m) => modeCounts[m]);
  return {
    bands,
    modes,
    sources: [...sources].sort(),
    bandCounts: Object.fromEntries(bands.map((b) => [b, bandCounts[b]])),
    modeCounts: Object.fromEntries(modes.map((m) => [m, modeCounts[m]])),
  };
}

/** The mode chips a "digital" or "analog" shortcut selects, of those on offer. */
export function shortcutModes(kind, offered) {
  const set = kind === "digital" ? DIGITAL_MODES : kind === "analog" ? ANALOG_MODES : [];
  return offered.filter((m) => set.includes(m));
}

/** `list` with `value` added or removed, in a new array. */
export function toggle(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** What the mode column says: the vocabulary's modes, else the source's own words. */
export function modeText(row) {
  if (Array.isArray(row?.modes) && row.modes.length) return row.modes.join(", ");
  return typeof row?.mode === "string" ? row.mode : "";
}

const clean = (v) => (typeof v === "string" && v.trim() ? v.trim() : null);

/**
 * The digital details a source supplied, one plain-words string per mode:
 * "DMR CC 1, Brandmeister", "D-STAR module B", "YSF DG-ID 00". Only what is
 * present: an absent detail is absent, never a dash or a zero.
 */
export function digitalDetails(row) {
  const d = row?.digital;
  if (!d || typeof d !== "object" || Array.isArray(d)) return [];
  const out = [];
  const dmr = [
    clean(d.dmr_color_code) && `CC ${clean(d.dmr_color_code)}`,
    clean(d.dmr_network),
    clean(d.dmr_id) && `ID ${clean(d.dmr_id)}`,
  ].filter(Boolean);
  if (dmr.length) out.push(`DMR ${dmr.join(", ")}`);
  const dstar = [
    clean(d.dstar_module) && `module ${clean(d.dstar_module)}`,
    clean(d.dstar_gateway) && `gateway ${clean(d.dstar_gateway)}`,
  ].filter(Boolean);
  if (dstar.length) out.push(`D-STAR ${dstar.join(", ")}`);
  if (clean(d.ysf_dgid)) out.push(`YSF DG-ID ${clean(d.ysf_dgid)}`);
  if (clean(d.p25_nac)) out.push(`P25 NAC ${clean(d.p25_nac)}`);
  if (clean(d.nxdn_ran)) out.push(`NXDN RAN ${clean(d.nxdn_ran)}`);
  return out;
}

// Wavelength order, long to short: the order operators read a band list in.
const BANDS = ["2190m", "630m", "160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m",
  "12m", "10m", "6m", "4m", "2m", "1.25m", "70cm", "33cm", "23cm", "13cm"];

function bandWeight(band) {
  const at = BANDS.indexOf(band);
  return at === -1 ? BANDS.length : at;
}

// --- remembering the filters ------------------------------------------------
// One object in localStorage, read field by field: a hand-edited or stale value
// costs that field, never the panel. `storage` is localStorage in the browser
// and a stand-in in tests; the panel and the map's RPTR layer both read it, so
// the two never disagree about what is filtered.

export const FILTERS_KEY = "hh.repeaters.filters";
const MAX_CHIPS = 20;

const strings = (value, allowed) =>
  Array.isArray(value)
    ? [...new Set(value.filter((v) => typeof v === "string" && v.length <= 8 &&
        (allowed ? allowed.includes(v) : /^[0-9.]+(m|cm)$/.test(v))))].slice(0, MAX_CHIPS)
    : [];

export function sanitizeFilters(raw) {
  const r = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  return {
    bands: strings(r.bands, null),
    modes: strings(r.modes, MODES),
    source: typeof r.source === "string" && r.source.length > 0 && r.source.length <= 60
      ? r.source : null,
    withinKm: Number.isFinite(r.withinKm) && r.withinKm > 0 && r.withinKm <= 40000
      ? r.withinKm : null,
  };
}

export function loadFilters(storage) {
  try {
    return sanitizeFilters(JSON.parse(storage.getItem(FILTERS_KEY)));
  } catch {
    return sanitizeFilters(null);
  }
}

export function saveFilters(storage, filters) {
  try {
    storage.setItem(FILTERS_KEY, JSON.stringify(sanitizeFilters(filters)));
  } catch {
    // Not remembered; still in effect for this view.
  }
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

// --- the areas the engine has active ----------------------------------------
//
// Hammunition's area of operations (D-082): the operator loads several states
// ahead of an emergency and activates the ones they are in. The collector
// hands over the active areas' rows in `rows` (which the map also reads) and
// the rest in `other_rows`, so a chip here can add an area for this browser
// session without asking anyone for anything. What a chip changes is this
// browser's choice only: it is kept as a difference from the engine's own
// active list, so when the engine's list moves the operator's changes still
// mean "this one too" and "not this one", not a stale copy of the whole list.
// Nothing here ever writes to the engine.

export const AREAS_KEY = "hh.repeaters.areas";

// The centre falls back to the middle of the first active area when the
// station is farther than this from it. A US state is about 300 to 500 km
// across, so a station farther than this from the middle of an area is
// outside it, not beside it, and its own position would rank every repeater
// in the area by its distance from somewhere the operator is not going.
export const AREA_FAR_KM = 300;

const AREA_ID = /^[A-Za-z0-9]{1,8}$/;
const areaIds = (value) =>
  Array.isArray(value)
    ? [...new Set(value.filter((v) => typeof v === "string" && AREA_ID.test(v)))].slice(0, MAX_CHIPS * 5)
    : [];

/** What this session changed: areas added, areas dropped, and "measure from the station". */
export function sanitizeAreaChoice(raw) {
  const r = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  const add = areaIds(r.add);
  return {
    add,
    drop: areaIds(r.drop).filter((a) => !add.includes(a)),
    station: r.station === true,
  };
}

export function loadAreaChoice(storage) {
  try {
    return sanitizeAreaChoice(JSON.parse(storage.getItem(AREAS_KEY)));
  } catch {
    return sanitizeAreaChoice(null);
  }
}

export function saveAreaChoice(storage, choice) {
  try {
    storage.setItem(AREAS_KEY, JSON.stringify(sanitizeAreaChoice(choice)));
  } catch {
    // Not remembered; still in effect for this view.
  }
}

/**
 * The areas of a snapshot with `on` (shown now) and `engine` (active in the
 * engine). Empty when the engine predates areas: there is nothing to choose.
 */
export function areaChips(payload, choice) {
  if (!payload?.has_areas) return [];
  const c = sanitizeAreaChoice(choice);
  return (payload.areas ?? []).map((a) => ({
    area: a.area,
    rows: a.rows ?? 0,
    centre: a.centre ?? null,
    engine: a.active === true,
    on: (a.active === true || c.add.includes(a.area)) && !c.drop.includes(a.area),
  }));
}

/** The choice after the chip for `area` is pressed. A new object. */
export function toggleArea(choice, area, payload) {
  const c = sanitizeAreaChoice(choice);
  const chip = areaChips(payload, c).find((a) => a.area === area);
  if (!chip) return c;
  const add = c.add.filter((a) => a !== area);
  const drop = c.drop.filter((a) => a !== area);
  // Turning it off: an engine-active area is dropped; one this session added is just un-added.
  if (chip.on) return { ...c, add, drop: chip.engine ? [...drop, area] : drop };
  return { ...c, add: chip.engine ? add : [...add, area], drop };
}

/**
 * The rows to show: the active layers' and the other areas' together, minus
 * the rows of any area this session has turned off. A layer that belongs to no
 * area is always shown. Without area support in the engine, `rows` as they are.
 */
export function rowsForAreas(payload, choice) {
  const rows = payload?.rows ?? [];
  if (!payload?.has_areas) return rows;
  const on = new Set(areaChips(payload, choice).filter((a) => a.on).map((a) => a.area));
  const areaOf = new Map((payload.layers ?? []).map((l) => [l.id, l.area ?? null]));
  const shown = (row) => {
    const area = areaOf.get(row.layer) ?? null;
    return area === null || on.has(area);
  };
  return [...rows, ...(payload.other_rows ?? [])].filter(shown);
}

/**
 * The centre to use when the operator has set none: the middle of the first
 * area on, when the station is absent or farther than AREA_FAR_KM from it.
 * `{centre, message}`; centre is null when the station stands.
 */
export function areaCentre(payload, choice) {
  const c = sanitizeAreaChoice(choice);
  if (c.station) return { centre: null, message: "" };
  const first = areaChips(payload, c).find((a) => a.on && a.centre);
  if (!first) return { centre: null, message: "" };
  const station = payload.station;
  const away = station
    ? distanceKm(station.lat, station.lon, first.centre.lat, first.centre.lon)
    : null;
  if (away !== null && away <= AREA_FAR_KM) return { centre: null, message: "" };
  const centre = { kind: "area", lat: first.centre.lat, lon: first.centre.lon, label: first.area };
  const why = away === null
    ? "no station position is set"
    : `the station is ${Math.round(away)} km from it, more than ${AREA_FAR_KM} km`;
  return {
    centre,
    message:
      `Distances are measured from the middle of ${first.area}, the first active area, because ${why}. ` +
      "Set a centre of your own, or press STATION to measure from the station.",
  };
}

/**
 * The rows both the table and the map draw, and the centre they are measured
 * from: the active areas plus this session's additions minus its drops, then
 * measured from the operator's own centre, else the area fallback, else as the
 * collector measured them. One function, so the two views cannot disagree.
 */
export function viewRows(payload, chosen, choice) {
  const source = rowsForAreas(payload, choice);
  const fallback = chosen ? { centre: null, message: "" } : areaCentre(payload, choice);
  const centre = chosen ?? fallback.centre;
  return {
    rows: centre ? withCentre(source, centre) : source,
    centre,
    fallback,
  };
}

/** One plain line when the other areas' rows were cut at the collector's cap, else "". */
export function areaCutNote(payload, cap = 3000) {
  const cut = payload?.has_areas ? Number(payload.other_truncated) || 0 : 0;
  return cut > 0
    ? `The inactive areas were cut at ${cap} rows (${cut} left out); ` +
        "`hammunition maps activate` is the full answer."
    : "";
}

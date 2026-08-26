// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Callsign resolution in the browser, against the prefix table the collector
// publishes. Mirrors prefix.py deliberately -- same normalization, same
// longest-prefix match -- so a callsign resolves the same way whether it came
// off the cluster or was typed into the lookup box.
//
// Doing it here rather than server-side is what keeps lookups instant and keeps
// the collector free of request-driven work.

const PORTABLE_NOISE = new Set(["P", "M", "MM", "AM", "QRP", "A", "LH", "B"]);
const CALL_CHARS = /^[A-Z0-9/]+$/;

/**
 * Strip portable designators down to the part that identifies the entity.
 * W1AW/4 is still the US; DL/W1AW is Germany.
 */
export function baseCall(callsign) {
  const call = (callsign ?? "").trim().toUpperCase();
  if (!call.includes("/")) return call;

  const parts = call.split("/").filter(Boolean);
  if (parts.length <= 1) return parts[0] ?? call;

  const head = parts[0];
  const tail = parts[parts.length - 1];

  if (PORTABLE_NOISE.has(tail) && parts.length === 2) return head;
  if (/^\d+$/.test(tail)) return head;

  const candidates = parts.filter((part) => !PORTABLE_NOISE.has(part));
  if (candidates.length === 0) return head;
  return candidates.reduce((a, b) => (b.length < a.length ? b : a));
}

/** Wrap a published prefix table in a lookup function. */
export function prefixTable(data) {
  const exact = data?.exact ?? {};
  const prefixes = data?.prefixes ?? [];

  return {
    approximate: Boolean(data?.approximate),
    source: data?.source ?? "unknown",
    size: prefixes.length,

    lookup(callsign) {
      const call = baseCall(callsign);
      if (!call || !CALL_CHARS.test(call)) return null;

      const hit = exact[call];
      if (hit) {
        return { name: hit[0], continent: hit[1], lat: hit[2], lon: hit[3], cqZone: hit[4] };
      }
      // Entries arrive longest-first, so the first match is the longest match.
      for (const [prefix, name, continent, lat, lon, cqZone] of prefixes) {
        if (call.startsWith(prefix)) return { name, continent, lat, lon, cqZone, prefix };
      }
      return null;
    },
  };
}

// --- great-circle maths, mirroring geo.py -------------------------------
const EARTH_RADIUS_KM = 6371.0088;
const rad = (deg) => (deg * Math.PI) / 180;
const deg = (r) => (r * 180) / Math.PI;

export function bearingDeg(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1);
  const p2 = rad(lat2);
  const dl = rad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

export function distanceKm(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1);
  const p2 = rad(lat2);
  const dp = rad(lat2 - lat1);
  const dl = rad(lon2 - lon1);
  const a =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

const POINTS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];

export function compassPoint(bearing) {
  return POINTS[Math.round((bearing % 360) / 22.5) % 16];
}

/** Everything the UI shows for one path. */
export function pathTo(from, lat, lon) {
  if (!from || from.lat == null || from.lon == null || lat == null || lon == null) return null;
  const bearing = bearingDeg(from.lat, from.lon, lat, lon);
  const km = distanceKm(from.lat, from.lon, lat, lon);
  return {
    bearing: Math.round(bearing * 10) / 10,
    bearing_long: Math.round(((bearing + 180) % 360) * 10) / 10,
    compass: compassPoint(bearing),
    km: Math.round(km * 10) / 10,
    miles: Math.round((km / 1.609344) * 10) / 10,
  };
}

/** Maidenhead from lat/lon, for showing the entity's approximate square. */
export function latLonToGrid(lat, lon, precision = 6) {
  if (lat == null || lon == null) return null;
  const adjLon = Math.min(lon + 180, 359.999999);
  const adjLat = Math.min(lat + 90, 179.999999);
  const A = (n) => String.fromCharCode(65 + n);

  let grid = A(Math.floor(adjLon / 20)) + A(Math.floor(adjLat / 10));
  if (precision >= 4) {
    grid += String(Math.floor((adjLon % 20) / 2)) + String(Math.floor(adjLat % 10));
  }
  if (precision >= 6) {
    grid += A(Math.floor(((adjLon % 2) / 2) * 24)) + A(Math.floor((adjLat % 1) * 24));
  }
  return grid;
}

/** Maidenhead to lat/lon centre, mirroring geo.grid_to_latlon. */
export function gridToLatLon(grid) {
  const text = String(grid ?? "").trim().toUpperCase();
  if (!/^[A-R]{2}([0-9]{2}([A-X]{2}([0-9]{2})?)?)?$/.test(text)) return null;

  const A = (c) => c.charCodeAt(0) - 65;
  let lon = A(text[0]) * 20 - 180;
  let lat = A(text[1]) * 10 - 90;
  let lonSpan = 20;
  let latSpan = 10;

  if (text.length >= 4) {
    lon += Number(text[2]) * 2;
    lat += Number(text[3]);
    lonSpan = 2;
    latSpan = 1;
  }
  if (text.length >= 6) {
    lon += A(text[4]) * (2 / 24);
    lat += A(text[5]) * (1 / 24);
    lonSpan = 2 / 24;
    latSpan = 1 / 24;
  }
  if (text.length >= 8) {
    lon += Number(text[6]) * (lonSpan / 10);
    lat += Number(text[7]) * (latSpan / 10);
    lonSpan /= 10;
    latSpan /= 10;
  }
  return [lat + latSpan / 2, lon + lonSpan / 2];
}

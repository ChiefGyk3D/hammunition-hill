// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// "Find my grid square" from the browser's location.
//
// hamdash asks for location on first visit. We make it a button instead: the
// dashboard works fine without it, and a prompt on load for something optional
// is the kind of thing people click away without reading.
//
// The coordinates never leave the browser. The grid is computed here, stored
// here, and used here -- the collector still reads its station from config,
// which is why the result comes with a nudge to paste it in.

import { latLonToGrid } from "./callsign.js";
import { recall, remember } from "./format.js";

const KEY = "qth.override";

/**
 * Why geolocation cannot run, or null if it can.
 *
 * The secure-context rule is the one that catches people out: the dashboard
 * works on the shack machine at http://localhost and silently cannot locate
 * you on the tablet at http://192.168.1.50, because browsers only expose this
 * API to secure contexts and plain HTTP on a LAN address is not one.
 */
export function unavailableReason() {
  if (!("geolocation" in navigator)) return "this browser has no geolocation";
  if (!window.isSecureContext) {
    return "needs https or localhost — browsers block location on a plain LAN address";
  }
  return null;
}

/** Ask the browser where we are. Resolves to {lat, lon, grid, accuracy}. */
export function locate({ timeout = 10000 } = {}) {
  const blocked = unavailableReason();
  if (blocked) return Promise.reject(new Error(blocked));

  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy } = position.coords;
        resolve({
          lat: latitude,
          lon: longitude,
          grid: latLonToGrid(latitude, longitude, 6),
          accuracy: Math.round(accuracy),
        });
      },
      (error) => {
        const reasons = {
          1: "permission denied",
          2: "position unavailable",
          3: "timed out",
        };
        reject(new Error(reasons[error.code] ?? error.message));
      },
      { enableHighAccuracy: false, timeout, maximumAge: 600000 },
    );
  });
}

/** A remembered browser-side QTH, or null. Overrides config for this browser. */
export function savedQth() {
  return recall(KEY, null);
}

export function saveQth(fix) {
  remember(KEY, fix);
}

export function clearQth() {
  remember(KEY, null);
}

// A browser-side callsign, the identity twin of the QTH override above and
// with exactly the same boundary: it changes what THIS DISPLAY shows and
// computes, never what the collector sends. Sources that log in with or
// query by a callsign (cluster, RBN, PSK Reporter, WSPR) read config.toml on
// the server, and no browser can reach that -- the absence of a write
// endpoint is the security model, so this stays presentation all the way
// down.
const CALL_KEY = "station.callsign";

export function savedCallsign() {
  return String(recall(CALL_KEY, "") || "");
}

export function saveCallsign(callsign) {
  remember(CALL_KEY, String(callsign || "").toUpperCase());
}

export function clearCallsign() {
  remember(CALL_KEY, "");
}

/**
 * The station to use: a browser override if one is set, otherwise config.
 *
 * Config stays authoritative for the collector -- it is what enriches spots
 * with bearings server-side. The override only affects what this browser draws,
 * which is the right split when one instance serves a shack machine and a
 * tablet in a different room.
 */
export function effectiveStation(configured) {
  const override = savedQth();
  const callsign = savedCallsign();
  let station = configured;
  if (override) {
    station = {
      ...station,
      lat: override.lat,
      lon: override.lon,
      grid: override.grid,
      located: true,
      overridden: true,
    };
  }
  if (callsign) {
    station = { ...station, callsign, callsign_overridden: true };
  }
  return station;
}

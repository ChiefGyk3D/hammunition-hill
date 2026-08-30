// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Watch lists and the notifications they fire.
//
// Everything here is browser-local: the list of calls lives in localStorage,
// the matching runs against snapshots the dashboard already fetched, and the
// alert is a system notification from THIS machine about data already ON this
// machine. No new fetch, no new egress, nothing the collector does not
// already do.
//
// The matching and the band-opening diff are pure functions on purpose: the
// render check imports this module into the page and asserts on them
// directly, which is the only unit-test rig web/ has.

import { baseCall } from "./callsign.js";
import { recall, remember } from "./format.js";

export function watchedCalls() {
  const raw = recall("watch.calls", []);
  return Array.isArray(raw) ? raw.map((c) => String(c).toUpperCase()).filter(Boolean) : [];
}

export function saveWatchedCalls(calls) {
  remember("watch.calls", calls.map((c) => String(c).toUpperCase()).filter(Boolean));
}

export function watchBandOpenings() {
  return recall("watch.bands", false) === true;
}

export function saveWatchBandOpenings(on) {
  remember("watch.bands", on === true);
}

/**
 * Why a system notification cannot happen, or null if it can.
 *
 * The secure-context rule is the same trap geolocation documents: fine on
 * http://localhost, silently unavailable on http://192.168.x.x. Saying so
 * beats a button that does nothing.
 */
export function notifyReason() {
  if (typeof Notification === "undefined") return "this browser has no notifications";
  if (!window.isSecureContext) {
    return "needs https or localhost — browsers block notifications on a plain LAN address";
  }
  if (Notification.permission === "denied") {
    return "notifications are blocked for this site — allow them in the browser";
  }
  return null;
}

/**
 * Which spots deserve an alert right now.
 *
 * Pure: (watch list, spots, what was already alerted, now) in, alerts and the
 * updated seen-map out. A watched "W1AW" matches W1AW and W1AW/3 -- the
 * operator is watching a station, not a suffix -- via the same baseCall the
 * lookup panel uses. One alert per call+band per window, so a run of cluster
 * spots for the same opening is one notification, not twelve.
 */
export function matchSpots(watch, spots, seen, now, windowMs = 30 * 60 * 1000) {
  const wanted = new Set(watch.map((c) => String(c).toUpperCase()));
  const alerts = [];
  const nextSeen = new Map();
  for (const [key, at] of seen) {
    if (now - at < windowMs) nextSeen.set(key, at);
  }
  for (const spot of spots) {
    const call = String(spot.call ?? "").toUpperCase();
    if (!call) continue;
    if (!wanted.has(call) && !wanted.has(baseCall(call))) continue;
    const key = `${call}|${spot.band ?? "?"}`;
    if (nextSeen.has(key)) continue;
    nextSeen.set(key, now);
    alerts.push(spot);
  }
  return { alerts, seen: nextSeen };
}

/**
 * Bands that just opened: rated "good" now, not rated "good" a poll ago.
 * The vocabulary is the propagation snapshot's own -- {band, level, reason}
 * with level good/warn/bad -- not an invented one. Pure, for the test rig.
 */
export function newlyOpen(previousBands, currentBands) {
  const wasOpen = new Set(
    (previousBands ?? []).filter((b) => b.level === "good").map((b) => b.band),
  );
  return (currentBands ?? []).filter((b) => b.level === "good" && !wasOpen.has(b.band));
}

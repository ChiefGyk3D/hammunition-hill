// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// What the ionosphere is actually doing, as opposed to what the model says.
//
// Everywhere else on this dashboard the ionosphere is inferred -- MINIMUF from
// solar flux and K, with an RMS the propagation panel admits to. Here a sounder
// has swept the sky and reported back. Two numbers matter:
//
// * **foF2** is the highest frequency reflected straight up. Nothing above it
//   comes back on a vertical path, and it is the figure the model is trying to
//   predict.
// * **MUF(3000)**, `mufd` in the feed, is the usable maximum for a 3000 km hop
//   off that same layer. It is roughly foF2 times the M(3000)F2 factor, which
//   is why it is three to four times larger and why quoting foF2 at someone
//   planning a DX path understates it badly.
//
// Sorted by distance from the operator, because that is the only ordering that
// answers the question being asked. A sounding from the far side of the world
// is a fact about somewhere else; the one 200 km away is about your path.

import { bearingDeg, distanceKm } from "../../lib/callsign.js";

// The same readout the MUF & Absorption panel uses, deliberately. These two sit
// side by side on Space Weather showing the same two quantities -- one modelled
// from solar indices, one measured by a sounder -- and the comparison only reads
// as a comparison if they are drawn the same way.
function readout(el, label, value, unit, sub) {
  const box = el("div", "readout");
  box.append(el("div", "label", label), el("div", "value", value));
  if (unit) box.querySelector(".value").append(el("span", "unit", ` ${unit}`));
  if (sub) box.append(el("div", "sub", sub));
  return box;
}

// Past this the sounder is no longer over ground your signal crosses on a
// first hop, so the reading stops being about you. Still listed, but the
// headline will not be drawn from it.
const NEAR_KM = 2000;

// How many rows to show. Enough to see the gradient across a region without
// turning the panel into the whole roster.
const ROWS = 6;

function mhz(value) {
  return typeof value === "number" ? `${value.toFixed(1)} MHz` : "—";
}

function figure(value) {
  return typeof value === "number" ? value.toFixed(1) : "—";
}

function age(minutes) {
  if (typeof minutes !== "number") return "";
  if (minutes < 1) return "just now";
  return `${Math.round(minutes)} min ago`;
}

export function render(root, { data, station, el }) {
  const snapshot = data.ionosondes;
  if (!snapshot) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const payload = snapshot.data ?? {};
  const stations = Array.isArray(payload.stations) ? payload.stations : [];

  if (!stations.length) {
    // These are different problems and the operator should be able to tell
    // them apart: an empty roster means the upstream is broken, while a full
    // roster reduced to nothing means every sounder went quiet -- which during
    // a storm is itself information.
    const dropped = payload.dropped ?? 0;
    const roster = payload.roster_size ?? 0;
    root.replaceChildren(
      el(
        "p",
        "empty",
        roster && dropped === roster
          ? `no sounding newer than ${payload.max_age_minutes} minutes — all ${roster} stations stale`
          : "no ionosonde data yet",
      ),
    );
    return;
  }

  const home = station?.located ? { lat: station.lat, lon: station.lon } : null;

  const ranked = stations
    .map((s) => ({
      ...s,
      km: home ? distanceKm(home.lat, home.lon, s.lat, s.lon) : null,
      bearing: home ? bearingDeg(home.lat, home.lon, s.lat, s.lon) : null,
    }))
    .sort((a, b) => {
      if (a.km === null || b.km === null) return (b.fof2 ?? 0) - (a.fof2 ?? 0);
      return a.km - b.km;
    });

  const parts = [];

  // The headline reads off the nearest sounder, and only if it is near enough
  // to be about this operator's paths.
  const nearest = ranked[0];
  if (home && nearest.km !== null && nearest.km <= NEAR_KM) {
    const headline = el("div", "readouts");
    headline.append(
      readout(el, "MUF", figure(nearest.mufd), "MHz", "3000 km hop, measured"),
      readout(el, "foF2", figure(nearest.fof2), "MHz", "critical freq, measured"),
    );
    parts.push(headline);
    parts.push(
      el(
        "p",
        "ion-nearest",
        `nearest sounder: ${nearest.name} — ${Math.round(nearest.km)} km, ${age(nearest.age_minutes)}`,
      ),
    );
  } else if (home) {
    parts.push(
      el(
        "p",
        "ion-nearest",
        `no sounder within ${NEAR_KM} km — the nearest is ${Math.round(nearest.km)} km away, so these are other people's ionosphere`,
      ),
    );
  } else {
    parts.push(el("p", "ion-nearest", "set your grid square to sort these by distance"));
  }

  const table = el("table", "bands ion-table");
  const head = el("tr", "");
  for (const label of ["Station", home ? "Dist" : "", "foF2", "MUF(3000)", "Age"]) {
    head.append(el("th", "", label));
  }
  table.append(head);

  for (const s of ranked.slice(0, ROWS)) {
    const row = el("tr", "");
    const name = el("td", "ion-name", s.name ?? s.code ?? "?");
    if (s.bearing !== null) name.title = `${Math.round(s.bearing)}° from you`;
    row.append(name);
    row.append(el("td", "ion-km", s.km === null ? "" : `${Math.round(s.km)} km`));
    row.append(el("td", "ion-num", mhz(s.fof2)));
    row.append(el("td", "ion-num", mhz(s.mufd)));
    row.append(el("td", "ion-age", age(s.age_minutes)));
    table.append(row);
  }
  parts.push(table);

  // Say what was thrown away. The roster carries readings that are years old
  // with full confidence scores, and silently dropping them would leave the
  // panel looking like the network is smaller than it is.
  const footer = [`${payload.station_count} sounding${payload.station_count === 1 ? "" : "s"}`];
  if (payload.dropped) {
    footer.push(`${payload.dropped} stale or unscaled, dropped`);
  }
  parts.push(el("p", "count", footer.join(" · ")));

  root.replaceChildren(...parts);
}

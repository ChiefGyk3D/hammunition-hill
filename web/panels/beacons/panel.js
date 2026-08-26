// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The NCDXF/IARU beacon schedule.
//
// Eighteen beacons share five frequencies on a fixed three-minute cycle
// synchronised to UTC, so which one is transmitting where is arithmetic on the
// clock. No network, no snapshot, no upstream -- this panel works with the
// antenna connected and nothing else.
//
// It is also the most directly useful thing here. Tune 14.100, see which beacon
// should be on, and whether you hear it tells you more about whether the band
// is open to that part of the world than any prediction. Each beacon sends its
// callsign then four dashes at 100 W, 10 W, 1 W and 100 mW; how far down the
// ladder you can still hear is a signal report you take by ear.
//
// The maths mirrors beacons.py, which is where it is tested.

import { effectiveStation } from "../../lib/geolocate.js";
import { pathTo } from "../../lib/callsign.js";
import { distance } from "../../lib/format.js";

const state = { data: null, loading: false, error: null };

function slotAt(now) {
  const seconds = now.getUTCHours() * 3600 + now.getUTCMinutes() * 60 + now.getUTCSeconds();
  return Math.floor((seconds % 180) / 10);
}

function secondsIntoSlot(now) {
  const seconds = now.getUTCHours() * 3600 + now.getUTCMinutes() * 60 + now.getUTCSeconds();
  return seconds % 10;
}

/** Which beacon is on this band now: slot minus the band index, wrapped. */
function beaconOn(beacons, bandIndex, now) {
  return beacons[(((slotAt(now) - bandIndex) % beacons.length) + beacons.length) % beacons.length];
}

function mhz(khz) {
  return (khz / 1000).toFixed(3);
}

export function render(root, { data, el }) {
  if (!state.data && !state.loading) {
    state.loading = true;
    fetch("./beacons.json")
      .then((r) => r.json())
      .then((payload) => { state.data = payload; })
      .catch((err) => { state.error = err.message; })
      .finally(() => {
        state.loading = false;
        render(root, { data, el });
      });
    root.replaceChildren(el("p", "empty", "loading beacon schedule…"));
    return;
  }
  if (state.error) {
    root.replaceChildren(el("p", "error", `beacon schedule: ${state.error}`));
    return;
  }
  if (!state.data) return;

  const { bands, beacons } = state.data;
  const now = new Date();
  const station = effectiveStation(data.station?.data ?? {});
  const elapsed = secondsIntoSlot(now);

  const table = el("table", "beacons");
  const thead = el("thead");
  const headRow = el("tr");
  for (const label of ["Band", "MHz", "Beacon", "Location", "Brg", "Distance", ""]) {
    headRow.append(el("th", null, label));
  }
  thead.append(headRow);
  table.append(thead);

  const body = el("tbody");
  for (const band of bands) {
    const beacon = beaconOn(beacons, band.index, now);
    const path = pathTo(station, beacon.lat, beacon.lon);
    const row = el("tr");

    row.append(
      el("td", "bx-band", band.name),
      el("td", "bx-freq", mhz(band.khz)),
      el("td", "bx-call", beacon.callsign),
      el("td", "bx-where", beacon.location),
      el("td", "bx-brg", path ? `${Math.round(path.bearing)}°` : "—"),
      el("td", "bx-dist", path ? distance(path) : "—"),
    );

    // Ten seconds per slot, draining. It makes the cycle legible and tells you
    // how long you have left to listen for this one.
    const meter = el("td", "bx-meter");
    const bar = el("div", "bx-bar");
    const fill = el("div", "bx-fill");
    fill.style.width = `${((10 - elapsed) / 10) * 100}%`;
    bar.append(fill);
    meter.append(bar);
    row.append(meter);

    body.append(row);
  }
  table.append(body);

  const parts = [table];
  parts.push(
    el(
      "p",
      "count",
      `slot ${slotAt(now) + 1}/18 · ${10 - elapsed}s left · schedule computed locally, no network`,
    ),
  );
  if (!station.located) {
    parts.push(el("p", "empty", "set [station] grid for bearings and distances"));
  }
  root.replaceChildren(...parts);
}

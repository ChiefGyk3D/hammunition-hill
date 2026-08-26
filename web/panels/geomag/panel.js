// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The disturbance side of space weather: what is going to close a band rather
// than open one.
//
// K-index prefers NOAA SWPC's planetary figure over HamQSL's when both are
// present -- SWPC publishes it more often, and during a storm that matters.

import { gaugeRow } from "../../lib/gauge.js";

const GEOMAG = ["kindex", "solarwind", "noise", "protons"];

export function render(root, { data, el }) {
  const solar = data.hamqsl?.data ?? {};
  const swpc = data.kindex?.data ?? {};

  if (!data.hamqsl && !data.kindex) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const gauges = { ...(solar.gauges ?? {}) };
  if (swpc.gauge) gauges.kindex = swpc.gauge;

  const row = gaugeRow(gauges, GEOMAG, { size: 116 });
  if (!row) {
    root.replaceChildren(el("p", "empty", "no geomagnetic data yet"));
    return;
  }

  const parts = [row];
  if (swpc.storm_level && swpc.storm_level !== "quiet") {
    parts.push(el("p", "count", `NOAA scale: ${swpc.storm_level}`));
  }
  root.replaceChildren(...parts);
}

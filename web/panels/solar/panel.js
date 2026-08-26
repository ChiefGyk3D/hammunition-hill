// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Tier 1: reads snapshots written by the collector. Every value on this panel
// came from this host, not from a third-party banner image.
//
// Dials *and* numbers. A bare figure does not say whether it is good --
// "A-index 4" means nothing until you know 7 is the quiet threshold -- and a
// dial alone loses the precision. Severity comes from severity.py, classified
// server-side where it can be tested.

import { gaugeRow } from "../../lib/gauge.js";

const SOLAR = ["sfi", "sunspots", "xray", "aindex"];

export function render(root, { data, el }) {
  const solar = data.hamqsl?.data ?? {};
  const kp = data.kindex?.data ?? {};
  const flux = data.solarflux?.data ?? {};
  const xray = data.xray?.data ?? {};

  if (!data.hamqsl && !data.kindex) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const parts = [];
  const gauges = solar.gauges ?? {};

  const row = gaugeRow(gauges, SOLAR, { size: 116 });
  if (row) {
    parts.push(row);
  } else {
    // No classified gauges yet: fall back to whatever raw numbers we have
    // rather than showing an empty panel.
    const grid = el("div", "readouts");
    for (const [label, value] of [
      ["SFI", solar.solarflux ?? flux.flux],
      ["A-index", solar.aindex],
      ["K-index", kp.kp !== undefined ? kp.kp.toFixed(1) : solar.kindex],
      ["X-ray", xray.class ?? solar.xray],
    ]) {
      const box = el("div", "readout");
      box.append(el("div", "label", label), el("div", "value", value ?? "—"));
      grid.append(box);
    }
    parts.push(grid);
  }

  if (solar.geomagfield) {
    parts.push(el("p", "count", `geomagnetic field: ${solar.geomagfield.toLowerCase()}`));
  }
  root.replaceChildren(...parts);
}

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Which bands are worth trying, and why not the others.
//
// This panel is deliberate about not overclaiming. It is an indicator built
// from three numbers, not a propagation prediction — VOACAP models a specific
// path with antennas and power; this models "roughly where is the MUF". The
// footer says so, on the panel, because a number with a confident-looking
// decimal point invites more trust than this one has earned.
//
// The value is in the *reasons*: "above the MUF" and "below the LUF —
// D-layer absorption" tell an operator something they can act on, which a
// bare colour cannot.

const LEVEL_ORDER = { good: 0, warn: 1, critical: 2 };

function readout(el, label, value, unit, sub) {
  const box = el("div", "readout");
  box.append(el("div", "label", label), el("div", "value", value));
  if (unit) box.querySelector(".value").append(el("span", "unit", ` ${unit}`));
  if (sub) box.append(el("div", "sub", sub));
  return box;
}

export function render(root, { data, el }) {
  const snapshot = data.propagation;
  if (!snapshot) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }
  const payload = snapshot.data;
  if (!payload) {
    root.replaceChildren(
      el("p", "error", snapshot.error ? `failed: ${snapshot.error}` : "no data"),
    );
    return;
  }

  // The model needs a location and two numbers. When it cannot run, say which
  // one is missing rather than rendering zeroes that look like a reading.
  if (!payload.available) {
    root.replaceChildren(el("p", "empty", payload.reason ?? "not available"));
    return;
  }

  const parts = [];

  const readouts = el("div", "readouts");
  readouts.append(
    readout(el, "MUF", payload.muf_mhz.toFixed(1), "MHz", "3000 km hop"),
    readout(el, "foF2", payload.fof2_mhz.toFixed(1), "MHz", "critical freq"),
    readout(
      el,
      "LUF",
      payload.luf_mhz > 0 ? payload.luf_mhz.toFixed(1) : "—",
      payload.luf_mhz > 0 ? "MHz" : "",
      payload.luf_mhz > 0 ? "absorption floor" : "no D layer",
    ),
    readout(
      el,
      "Sun",
      payload.is_daylight ? `${(90 - payload.solar_zenith_deg).toFixed(0)}°` : "down",
      "",
      payload.is_daylight ? "above horizon" : `${payload.absorption_db.toFixed(0)} dB absorption`,
    ),
  );
  parts.push(readouts);

  const list = el("div", "muf-bands");
  for (const band of payload.bands ?? []) {
    const row = el("div", `muf-band level-${band.level}`);
    row.append(
      el("span", "muf-name", band.band),
      el("span", "muf-freq", `${band.mhz.toFixed(1)}`),
      el("span", "muf-reason", band.reason),
    );
    list.append(row);
  }
  parts.push(list);

  const open = (payload.bands ?? []).filter((b) => b.level === "good");
  const summary = el("p", "count");
  summary.textContent = open.length
    ? `${open.length} bands open: ${open.map((b) => b.band).join(", ")}`
    : "no bands in the clear right now";
  parts.push(summary);

  const caveat = el("p", "tier-note");
  caveat.textContent =
    `An indicator, not a prediction — SFI ${payload.sfi}, K ${payload.k_index}, ` +
    `sun computed for ${payload.grid ?? "your grid"}. Real paths vary; see docs/PROPAGATION.md.`;
  parts.push(caveat);

  root.replaceChildren(...parts);
}

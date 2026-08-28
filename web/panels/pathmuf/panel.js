// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can see one at https://mozilla.org/MPL/2.0/.

// When does the band open to THERE: a 24-hour MUF chart for one path.
//
// The propagation panel answers "which bands work from here, right now".
// This one answers the question an operator plans a day around: "when is
// 20 m open to Japan". Type a grid square (or hit a preset), and MINIMUF 3.5
// -- the public-domain NOSC point-to-point model, see lib/muf.js and
// docs/PROPAGATION.md -- draws the day, computed entirely in this browser
// from the solar flux the collector already fetched.
//
// What the colours honestly mean: MINIMUF predicts the F2-layer MUF and
// nothing else. A band above the MUF is shut; just below it is prime DX;
// well below it the model simply has no opinion about daytime D-layer
// absorption on that path, and the cell says "low" rather than pretending
// green. No sporadic-E, so no 6 m -- an Es opening will beat this chart and
// that is normal.

import { gridToLatLon, pathTo } from "../../lib/callsign.js";
import { recall, remember } from "../../lib/format.js";
import { MAX_PATH_KM, MIN_PATH_KM, pathMuf } from "../../lib/muf.js";

// HF bands the F2 model can speak to. 160 m propagation is absorption- and
// noise-limited, not MUF-limited, and 6 m is sporadic-E: both would be
// colour without meaning here.
const BANDS = [
  ["80m", 3.7], ["60m", 5.35], ["40m", 7.1], ["30m", 10.1], ["20m", 14.2],
  ["17m", 18.1], ["15m", 21.2], ["12m", 24.9], ["10m", 28.4],
];

const PRESETS = [
  ["EU", "JO50"], ["JA", "PM95"], ["VK", "QF56"], ["ZS", "KG43"],
  ["SA", "GG66"], ["W6", "CM87"],
];

const state = { target: recall("pathmuf.target", "PM95") };

function cellClass(mhz, muf) {
  if (mhz > muf) return "pmf-above";
  if (mhz > muf * 0.85) return "pmf-near";
  if (mhz > muf * 0.5) return "pmf-prime";
  return "pmf-low";
}

export function render(root, { data, station, el }) {
  const payload = data.propagation?.data;
  const sfi = payload?.sfi;
  if (sfi == null) {
    root.replaceChildren(
      el("p", "empty", "waiting for solar flux — configure a swpc or hamqsl source"),
    );
    return;
  }
  if (!station?.located) {
    root.replaceChildren(el("p", "empty", "set a [station] grid or lat/lon to draw a path"));
    return;
  }

  const draw = () => {
    const parts = [];

    // Target row: a grid square in, presets for the classic directions.
    const controls = el("div", "pmf-controls");
    const input = el("input", "pmf-input");
    input.value = state.target;
    input.maxLength = 6;
    input.placeholder = "grid (PM95)";
    input.addEventListener("change", () => {
      state.target = input.value.trim().toUpperCase();
      remember("pathmuf.target", state.target);
      draw();
    });
    controls.append(input);
    for (const [label, grid] of PRESETS) {
      const chip = el("button", "chip" + (grid === state.target ? " on" : ""), label);
      chip.type = "button";
      chip.addEventListener("click", () => {
        state.target = grid;
        remember("pathmuf.target", state.target);
        draw();
      });
      controls.append(chip);
    }
    parts.push(controls);

    const target = gridToLatLon(state.target);
    if (!target) {
      parts.push(el("p", "empty", `"${state.target}" is not a grid square`));
      root.replaceChildren(...parts);
      return;
    }
    const [lat, lon] = target;
    const path = pathTo({ lat: station.lat, lon: station.lon }, lat, lon);

    const now = new Date();
    const month = now.getUTCMonth() + 1;
    const day = now.getUTCDate();
    const hourNow = now.getUTCHours() + now.getUTCMinutes() / 60;

    const at = (hour) =>
      pathMuf({
        sfi,
        month,
        day,
        utcHour: hour,
        lat1: station.lat,
        lon1: station.lon,
        lat2: lat,
        lon2: lon,
      });

    const mufNow = at(hourNow);
    if (mufNow == null) {
      const km = Math.round(path.km);
      const which = km < MIN_PATH_KM ? "short" : "long";
      parts.push(
        el(
          "p",
          "empty",
          `${state.target} is ${km} km away — too ${which} for MINIMUF ` +
            `(fitted for ${MIN_PATH_KM}–${MAX_PATH_KM} km). ` +
            (which === "short"
              ? "That close is NVIS or ground wave, a different problem."
              : "Long-path predictions need a real ray tracer."),
        ),
      );
      root.replaceChildren(...parts);
      return;
    }

    parts.push(
      el(
        "p",
        "pmf-path",
        `${state.target} · ${Math.round(path.km)} km · ${Math.round(path.bearing)}° ` +
          `${path.compass} · MUF now ${mufNow.toFixed(1)} MHz`,
      ),
    );

    // The day, one column per UTC hour, one row per band.
    const mufs = [];
    for (let hour = 0; hour < 24; hour += 1) mufs.push(at(hour + 0.5));

    const grid = el("div", "pmf-grid");
    grid.append(el("span", "pmf-corner", "UTC"));
    for (let hour = 0; hour < 24; hour += 1) {
      const head = el("span", "pmf-hour" + (hour === now.getUTCHours() ? " pmf-now" : ""));
      head.textContent = hour % 6 === 0 ? String(hour).padStart(2, "0") : "";
      grid.append(head);
    }
    for (const [name, mhz] of [...BANDS].reverse()) {
      grid.append(el("span", "pmf-band", name));
      for (let hour = 0; hour < 24; hour += 1) {
        const cell = el(
          "span",
          `pmf-cell ${cellClass(mhz, mufs[hour])}` +
            (hour === now.getUTCHours() ? " pmf-now" : ""),
        );
        cell.title = `${name} at ${String(hour).padStart(2, "0")}00Z — MUF ${mufs[
          hour
        ].toFixed(1)} MHz`;
        grid.append(cell);
      }
    }
    parts.push(grid);

    const legend = el("div", "pmf-legend");
    for (const [cls, label] of [
      ["pmf-prime", "open"],
      ["pmf-near", "near MUF"],
      ["pmf-above", "shut"],
      ["pmf-low", "below — day absorption unmodelled"],
    ]) {
      const item = el("span", "pmf-key");
      item.append(el("span", `pmf-cell ${cls}`), el("span", "", label));
      legend.append(item);
    }
    parts.push(legend);

    parts.push(
      el(
        "p",
        "tier-note",
        `MINIMUF 3.5 (NOSC, public domain), F2 layer only, RMS error about 3.8 MHz ` +
          `against measured paths — an indicator, not VOACAP. SFI ${sfi}, computed ` +
          `in this browser. See docs/PROPAGATION.md.`,
      ),
    );

    root.replaceChildren(...parts);
  };

  draw();
}

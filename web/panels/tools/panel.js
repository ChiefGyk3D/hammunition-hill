// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The calculations an operator otherwise opens a browser tab for.
//
// Tier 0 throughout, and deliberately so: the person who needs to know how long
// to cut a 40 m dipole is usually standing in a field holding wire cutters,
// which is exactly when a hosted calculator is no help.
//
// The tables come from the published snapshot; the arithmetic is in
// web/lib/antenna.js, mirrored by src/hammunition_hill/antenna.py and held to
// it by a test. The grid tools reuse the geo helpers the callsign panel already
// uses, which are likewise checked against geo.py.

import { recall, remember } from "../../lib/format.js";
import {
  cutChart,
  electricalLengthM,
  matchedLossDb,
  powerAfterLoss,
  swrFigures,
  totalLineLossDb,
} from "../../lib/antenna.js";
import { compassPoint, gridToLatLon, pathTo } from "../../lib/callsign.js";

const VIEWS = ["antenna", "feedline", "SWR", "grid path"];

let state = null;

function ensureState() {
  if (state) return state;
  state = {
    view: recall("tools-view", "antenna"),
    freq: Number(recall("tools-freq", 14.2)) || 14.2,
    coax: recall("tools-coax", "rg213"),
    lengthM: Number(recall("tools-length", 30)) || 30,
    swr: Number(recall("tools-swr", 2)) || 2,
    from: recall("tools-from", ""),
    to: recall("tools-to", "JO65"),
  };
  return state;
}

function numberField(el, label, value, suffix, onChange) {
  const box = el("label", "tool-field");
  box.append(el("span", "tool-label", suffix ? `${label} (${suffix})` : label));
  const input = document.createElement("input");
  input.type = "text";
  input.inputMode = "decimal";
  input.className = "tool-input";
  input.value = String(value);
  input.spellcheck = false;
  input.addEventListener("change", () => onChange(input.value.trim()));
  box.append(input);
  return box;
}

function textField(el, label, value, placeholder, onChange) {
  const box = el("label", "tool-field");
  box.append(el("span", "tool-label", label));
  const input = document.createElement("input");
  input.type = "text";
  input.className = "tool-input";
  input.value = value;
  input.placeholder = placeholder;
  input.spellcheck = false;
  input.autocapitalize = "characters";
  input.addEventListener("change", () => onChange(input.value.trim().toUpperCase()));
  box.append(input);
  return box;
}

function rows(el, entries) {
  const wrap = el("div", "tool-rows");
  for (const [label, value, note] of entries) {
    const row = el("div", "tool-row");
    row.append(el("span", "tool-row-label", label), el("span", "tool-row-value", value));
    if (note) row.append(el("span", "tool-row-note", note));
    wrap.append(row);
  }
  return wrap;
}

// "∞" rather than a blank or a NaN. A perfect match really does have infinite
// return loss, and saying so is more useful than hiding the row.
function orInfinity(value, digits, unit) {
  return value == null ? "∞" : `${value.toFixed(digits)} ${unit}`;
}

export function render(root, { data, station, el }) {
  const snapshot = data.antenna;
  if (!snapshot?.data) {
    root.replaceChildren(el("p", "empty", "waiting for the reference tables…"));
    return;
  }
  const reference = snapshot.data;
  const s = ensureState();
  // Most paths start from home, so start there -- but only until the operator
  // types something, which is what an empty stored value means.
  if (!s.from && station?.grid) s.from = String(station.grid).toUpperCase();
  const coaxOf = (id) => reference.coax.find((c) => c.id === id) || reference.coax[0];

  const draw = () => {
    const parts = [];

    const tabs = el("div", "cw-tabs");
    for (const view of VIEWS) {
      const button = el("button", "chip" + (view === s.view ? " on" : ""), view);
      button.type = "button";
      button.addEventListener("click", () => {
        s.view = view;
        remember("tools-view", view);
        draw();
      });
      tabs.append(button);
    }
    parts.push(tabs);

    if (s.view !== "grid path") {
      parts.push(
        numberField(el, "frequency", s.freq, "MHz", (v) => {
          const parsed = Number(v);
          if (parsed > 0) {
            s.freq = parsed;
            remember("tools-freq", parsed);
          }
          draw();
        }),
      );
    }

    if (s.view === "antenna") {
      const chart = cutChart(s.freq, reference);
      parts.push(
        rows(
          el,
          chart.map((row) => [row.name, `${row.metres.toFixed(2)} m`, `${row.feet.toFixed(1)} ft`]),
        ),
      );
      parts.push(
        el(
          "p",
          "tool-hint",
          "Starting points, not answers. Height, nearby metal and wire insulation " +
            "move resonance by more than the difference between the formulas people " +
            "argue about. Cut long, measure, trim.",
        ),
      );
    }

    if (s.view === "feedline") {
      const picker = el("div", "cw-tabs cw-subtabs");
      for (const entry of reference.coax) {
        const button = el("button", "chip" + (entry.id === s.coax ? " on" : ""), entry.name);
        button.type = "button";
        button.addEventListener("click", () => {
          s.coax = entry.id;
          remember("tools-coax", entry.id);
          draw();
        });
        picker.append(button);
      }
      parts.push(picker);
      parts.push(
        numberField(el, "run length", s.lengthM, "m", (v) => {
          const parsed = Number(v);
          if (parsed >= 0) {
            s.lengthM = parsed;
            remember("tools-length", parsed);
          }
          draw();
        }),
      );

      const entry = coaxOf(s.coax);
      const matched = matchedLossDb(entry, s.freq, s.lengthM, reference.feet_per_metre);
      const stub = electricalLengthM(s.freq, entry);
      const delivered = powerAfterLoss(100, matched);
      parts.push(
        rows(el, [
          ["matched loss", `${matched.toFixed(2)} dB`, `over ${s.lengthM} m`],
          [
            "of 100 W",
            `${delivered.toFixed(1)} W reaches the antenna`,
            `${(100 - delivered).toFixed(1)} W into the cable`,
          ],
          ["velocity factor", entry.vf.toFixed(2), `${entry.ohms} Ω`],
          ["¼ λ of this cable", `${stub.toFixed(3)} m`, "a matching section is cut to this"],
        ]),
      );
      if (entry.note) parts.push(el("p", "tool-hint", entry.note));
      parts.push(
        el(
          "p",
          "tool-hint",
          "Manufacturer figures for new cable on a bench. Age, water in the braid, " +
            "every connector and a hot roof all push it up. Treat it as a floor.",
        ),
      );
    }

    if (s.view === "SWR") {
      parts.push(
        numberField(el, "SWR", s.swr, "", (v) => {
          const parsed = Number(v);
          if (parsed >= 1) {
            s.swr = parsed;
            remember("tools-swr", parsed);
          }
          draw();
        }),
      );
      const figures = swrFigures(s.swr);
      parts.push(
        rows(el, [
          ["reflected", `${figures.reflected_pct.toFixed(1)} %`, "of forward power"],
          ["return loss", orInfinity(figures.return_loss_db, 2, "dB"), ""],
          ["mismatch loss", orInfinity(figures.mismatch_loss_db, 2, "dB"), "on a lossless line"],
        ]),
      );

      const entry = coaxOf(s.coax);
      const matched = matchedLossDb(entry, s.freq, s.lengthM, reference.feet_per_metre);
      const total = totalLineLossDb(entry, s.freq, s.lengthM, s.swr, reference.feet_per_metre);
      parts.push(
        rows(el, [
          [`through ${s.lengthM} m of ${entry.name}`, `${total.toFixed(2)} dB`, "total"],
          ["the SWR's share", `${(total - matched).toFixed(2)} dB`, `matched loss ${matched.toFixed(2)} dB`],
          [
            "of 100 W",
            `${powerAfterLoss(100, total).toFixed(1)} W reaches the antenna`,
            "",
          ],
        ]),
      );
      parts.push(
        el(
          "p",
          "tool-hint",
          "High SWR is not by itself the problem — high SWR through a lossy line is. " +
            "Change the cable and the length above and watch the same reading cost " +
            "almost nothing, or almost everything.",
        ),
      );
    }

    if (s.view === "grid path") {
      parts.push(
        textField(el, "from", s.from, "your grid", (v) => {
          s.from = v;
          remember("tools-from", v);
          draw();
        }),
      );
      parts.push(
        textField(el, "to", s.to, "e.g. JO65", (v) => {
          s.to = v;
          remember("tools-to", v);
          draw();
        }),
      );

      const from = gridToLatLon(s.from);
      const to = gridToLatLon(s.to);
      if (!from || !to) {
        parts.push(
          el(
            "p",
            "tool-hint",
            "Two Maidenhead squares — a field (JO), a square (JO65) or a subsquare " +
              "(JO65ma). Distance and bearing between any two, not just from here.",
          ),
        );
      } else {
        const leg = pathTo({ lat: from[0], lon: from[1] }, to[0], to[1]);
        parts.push(
          rows(el, [
            ["distance", `${leg.km.toFixed(0)} km`, `${leg.miles.toFixed(0)} mi`],
            ["short path", `${leg.bearing.toFixed(1)}°`, compassPoint(leg.bearing)],
            ["long path", `${leg.bearing_long.toFixed(1)}°`, compassPoint(leg.bearing_long)],
            ["from", `${from[0].toFixed(3)}, ${from[1].toFixed(3)}`, s.from],
            ["to", `${to[0].toFixed(3)}, ${to[1].toFixed(3)}`, s.to],
          ]),
        );
        parts.push(
          el(
            "p",
            "tool-hint",
            "Great-circle over a spherical Earth: within a few kilometres of the " +
              "ellipsoidal answer at any distance a radio path covers, and both are " +
              "far more precise than a grid square is.",
          ),
        );
      }
    }

    root.replaceChildren(...parts);
  };

  draw();
}

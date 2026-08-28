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
import {
  batteryRuntime,
  dbBetweenWatts,
  ohm,
  powerRatioFromDb,
  voltageDrop,
} from "../../lib/electrical.js";
import { compassPoint, gridToLatLon, pathTo } from "../../lib/callsign.js";

const VIEWS = ["antenna", "feedline", "SWR", "ohm", "dB", "wire", "battery", "grid path"];

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
    // The power wheel keeps raw strings: "" means "not given", and exactly
    // two must be given, so emptiness is data here, not absence.
    ohm: { volts: "13.8", amps: "", ohms: "", watts: "100" },
    dbFrom: Number(recall("tools-db-from", 5)) || 5,
    dbTo: Number(recall("tools-db-to", 100)) || 100,
    awg: recall("tools-awg", "12"),
    runM: Number(recall("tools-run", 5)) || 5,
    runA: Number(recall("tools-amps", 20)) || 20,
    battAh: Number(recall("tools-batt-ah", 20)) || 20,
    battChem: recall("tools-batt-chem", "lifepo4"),
    battW: Number(recall("tools-batt-w", 60)) || 60,
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

    if (["antenna", "feedline", "SWR"].includes(s.view)) {
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

    if (s.view === "ohm") {
      const fields = el("div", "tool-grid");
      for (const key of ["volts", "amps", "ohms", "watts"]) {
        fields.append(
          numberField(el, key, s.ohm[key], "", (value) => {
            s.ohm[key] = value;
            draw();
          }),
        );
      }
      parts.push(fields);
      const given = Object.fromEntries(
        Object.entries(s.ohm)
          .filter(([, value]) => value !== "" && !Number.isNaN(Number(value)))
          .map(([key, value]) => [key, Number(value)]),
      );
      const result = ohm({ volts: null, amps: null, ohms: null, watts: null, ...given });
      if (Object.keys(given).length !== 2) {
        parts.push(el("p", "tool-hint", "Give exactly two — clear the rest."));
      } else if (!result) {
        parts.push(el("p", "tool-hint", "No finite answer for that pair."));
      } else {
        parts.push(
          rows(el, [
            ["volts", `${result.volts.toFixed(2)} V`],
            ["amps", `${result.amps === Infinity ? "∞" : result.amps.toFixed(3)} A`],
            ["ohms", `${result.ohms === Infinity ? "∞" : result.ohms.toFixed(2)} Ω`],
            ["watts", `${result.watts.toFixed(1)} W`],
          ]),
        );
      }
    }

    if (s.view === "dB") {
      parts.push(
        numberField(el, "from", s.dbFrom, "W", (value) => {
          const parsed = Number(value);
          if (parsed > 0) {
            s.dbFrom = parsed;
            remember("tools-db-from", parsed);
          }
          draw();
        }),
        numberField(el, "to", s.dbTo, "W", (value) => {
          const parsed = Number(value);
          if (parsed > 0) {
            s.dbTo = parsed;
            remember("tools-db-to", parsed);
          }
          draw();
        }),
      );
      const db = dbBetweenWatts(s.dbFrom, s.dbTo);
      parts.push(
        rows(el, [
          ["difference", `${db >= 0 ? "+" : ""}${db.toFixed(2)} dB`],
          ["ratio", `×${powerRatioFromDb(db).toFixed(2)}`],
          ["in S-units", `≈${(db / 6).toFixed(1)}`, "6 dB per S-unit, by convention"],
        ]),
      );
      parts.push(
        el(
          "p",
          "tool-hint",
          "3 dB is double, 10 dB is ten times. Going from 5 W to 100 W buys 13 dB " +
            "— about two S-units at the far end.",
        ),
      );
    }

    if (s.view === "wire") {
      const table = reference.electrical?.awg_ohms_per_kft || {};
      const picker = el("div", "cw-tabs cw-subtabs");
      for (const gauge of Object.keys(table).sort((a, b) => Number(a) - Number(b))) {
        const button = el("button", "chip" + (gauge === s.awg ? " on" : ""), `AWG ${gauge}`);
        button.type = "button";
        button.addEventListener("click", () => {
          s.awg = gauge;
          remember("tools-awg", gauge);
          draw();
        });
        picker.append(button);
      }
      parts.push(picker);
      parts.push(
        numberField(el, "one-way run", s.runM, "m", (value) => {
          const parsed = Number(value);
          if (parsed >= 0) {
            s.runM = parsed;
            remember("tools-run", parsed);
          }
          draw();
        }),
        numberField(el, "current", s.runA, "A", (value) => {
          const parsed = Number(value);
          if (parsed >= 0) {
            s.runA = parsed;
            remember("tools-amps", parsed);
          }
          draw();
        }),
      );
      const drop = voltageDrop(
        table,
        reference.feet_per_metre,
        Number(s.awg),
        s.runM,
        s.runA,
        13.8,
      );
      if (drop) {
        parts.push(
          rows(el, [
            ["drop", `${drop.drop_volts.toFixed(2)} V`, `${drop.percent.toFixed(1)}% of 13.8`],
            ["at the radio", `${drop.at_load_volts.toFixed(2)} V`],
            ["round trip", `${drop.ohms.toFixed(4)} Ω`, "both conductors counted"],
          ]),
        );
      }
      parts.push(
        el(
          "p",
          "tool-hint",
          "A 100 W HF radio wants ~13.8 V at 20+ A and folds back power below " +
            "≈11.5 V on transmit. The round trip is the resistance: ten metres " +
            "of cable is twenty metres of copper.",
        ),
      );
    }

    if (s.view === "battery") {
      const usable = reference.electrical?.battery_usable || {};
      const picker = el("div", "cw-tabs cw-subtabs");
      const labels = { lifepo4: "LiFePO₄", lead_acid: "lead-acid", agm: "AGM" };
      for (const chem of Object.keys(usable).sort()) {
        const button = el(
          "button",
          "chip" + (chem === s.battChem ? " on" : ""),
          labels[chem] || chem,
        );
        button.type = "button";
        button.addEventListener("click", () => {
          s.battChem = chem;
          remember("tools-batt-chem", chem);
          draw();
        });
        picker.append(button);
      }
      parts.push(picker);
      parts.push(
        numberField(el, "capacity", s.battAh, "Ah", (value) => {
          const parsed = Number(value);
          if (parsed > 0) {
            s.battAh = parsed;
            remember("tools-batt-ah", parsed);
          }
          draw();
        }),
        numberField(el, "load", s.battW, "W", (value) => {
          const parsed = Number(value);
          if (parsed > 0) {
            s.battW = parsed;
            remember("tools-batt-w", parsed);
          }
          draw();
        }),
      );
      const runtime = batteryRuntime(usable, s.battAh, s.battChem, s.battW, 12.8);
      if (runtime) {
        parts.push(
          rows(el, [
            ["runtime", `${runtime.hours.toFixed(1)} h`],
            ["usable energy", `${runtime.usable_watt_hours.toFixed(0)} Wh`,
              `${(runtime.usable_fraction * 100).toFixed(0)}% of nameplate`],
          ]),
        );
      }
      parts.push(
        el(
          "p",
          "tool-hint",
          "Derated by chemistry, not hope: lead-acid past half charge trades " +
            "battery life for minutes; LiFePO₄ holds voltage nearly to the floor. " +
            "A 20/80 duty cycle on SSB stretches these numbers a lot.",
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

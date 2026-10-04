// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Repeaters near the station, from the layers Hammunition already holds.
//
// Tier 0: the collector asked the local engine for its repeater layers and
// worked out distance and bearing from the grid square's centre. This panel
// filters and draws, and can re-measure from any centre the operator picks (a
// grid, coordinates, a map point). Nothing here fetches, so a place NAME is not
// understood: that would be a lookup, and nothing here asks anybody anything.
//
// There is no export button, on purpose. Some of these rows are RepeaterBook's
// (marked personal use by the engine), and its terms keep them on the machine
// that fetched them; the server withholds them from every other host, and a
// file-saving button would be a way around that. tests/test_repeaters.py holds it.

import { relativeAge } from "../../lib/format.js";
import { bandColor } from "../../lib/bandcolors.js";
import {
  CENTRE_EVENT,
  DEFAULT_FILTERS,
  bearingLabel,
  clearCentre,
  coverageNote,
  digitalDetails,
  facets,
  filterRows,
  kmLabel,
  loadCentre,
  loadFilters,
  mhz,
  modeText,
  offsetLabel,
  parseCentre,
  saveCentre,
  saveFilters,
  shortcutModes,
  toggle,
  withCentre,
} from "../../lib/repeaters.js";

const MAX_ROWS = 60;
const KM_STEPS = [25, 50, 100, 250];

// Bands and modes are lists (multi-select); source and distance are single. All
// of it is remembered in this browser as one object, which the map's RPTR layer
// reads too, so the table and the dots never disagree.
const state = { ...DEFAULT_FILTERS };
{
  const store = (() => {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  })();
  if (store) Object.assign(state, loadFilters(store));
}

function persist() {
  try {
    saveFilters(window.localStorage, state);
  } catch {
    // Not remembered; still in effect for this view.
  }
}

// The chosen centre lives in localStorage and nowhere else; the map panel sets
// it too (a click or long press), so both announce a change with an event and
// whichever panel is showing re-renders.
let redraw = null;
let listening = false;
let centreError = "";

function storage() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function announce() {
  window.dispatchEvent(new CustomEvent(CENTRE_EVENT));
}

function centreRow(el, payload, chosen) {
  const row = el("div", "rp-filter");
  row.append(el("span", "rp-filter-label", "CENTRE"));
  row.append(
    el(
      "span",
      "rp-centre",
      chosen
        ? `${chosen.kind === "grid" ? "grid " : "point "}${chosen.label}`
        : payload.grid
          ? `station ${payload.grid}`
          : "no station set",
    ),
  );
  const input = el("input", "cs-input rp-centre-input");
  input.type = "text";
  input.placeholder = "grid FN42 or lat, lon";
  input.setAttribute("aria-label", "Centre for distances: a Maidenhead grid or latitude, longitude");
  input.maxLength = 40;
  const apply = () => {
    const centre = parseCentre(input.value);
    if (!centre) {
      centreError =
        "not a 4- or 6-character grid square or a latitude, longitude pair " +
        "(a place name is not looked up: nothing here asks anyone anything)";
      redraw?.();
      return;
    }
    centreError = "";
    const store = storage();
    if (store) saveCentre(store, centre);
    announce();
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") apply();
  });
  const set = el("button", "chip", "SET");
  set.type = "button";
  set.addEventListener("click", apply);
  const back = el("button", "chip", "STATION");
  back.type = "button";
  back.title = "Measure from the station's own grid square again";
  back.addEventListener("click", () => {
    centreError = "";
    const store = storage();
    if (store) clearCentre(store);
    announce();
  });
  row.append(input, set, back);
  return row;
}

function chip(el, text, on, onClick, title = "") {
  const node = el("button", "chip", text);
  node.type = "button";
  if (on) node.classList.add("on");
  node.setAttribute("aria-pressed", String(on));
  if (title) node.title = title;
  node.addEventListener("click", onClick);
  return node;
}

// One value at a time: source and "within". ALL clears it.
function chipRow(el, label, key, options, rerender, allLabel = "ALL") {
  const row = el("div", "rp-filter");
  row.append(el("span", "rp-filter-label", label));
  const chips = el("div", "chips");
  for (const [option, text] of [[null, allLabel], ...options]) {
    chips.append(
      chip(el, text, state[key] === option, () => {
        state[key] = option;
        persist();
        rerender();
      }),
    );
  }
  row.append(chips);
  return row;
}

// Any number at once: bands and modes, each chip with how many rows have it.
// ALL clears the list. `extra` are shortcut chips placed after the list.
function multiRow(el, label, key, options, counts, rerender, extra = []) {
  const row = el("div", "rp-filter");
  row.append(el("span", "rp-filter-label", label));
  const chips = el("div", "chips");
  chips.append(
    chip(el, "ALL", state[key].length === 0, () => {
      state[key] = [];
      persist();
      rerender();
    }),
  );
  for (const option of options) {
    chips.append(
      chip(
        el,
        `${option} ${counts[option] ?? 0}`,
        state[key].includes(option),
        () => {
          state[key] = toggle(state[key], option);
          persist();
          rerender();
        },
        `${counts[option] ?? 0} repeater${counts[option] === 1 ? "" : "s"}`,
      ),
    );
  }
  for (const [text, modes, title] of extra) {
    const same = modes.length > 0 && modes.length === state[key].length &&
      modes.every((m) => state[key].includes(m));
    chips.append(
      chip(el, text, same, () => {
        state[key] = same ? [] : [...modes];
        persist();
        rerender();
      }, title),
    );
  }
  row.append(chips);
  return row;
}

function sourceBadges(el, row) {
  const wrap = el("span", "rp-src");
  const badge = el("span", "rp-badge", row.layer || row.source);
  badge.title = row.source;
  wrap.append(badge);
  // The other sources that list the same machine: a repeater two independent
  // sources agree on is better evidence than one that appears in a single list.
  for (const other of row.also ?? []) {
    const also = el("span", "rp-badge rp-also", other);
    also.title = `also listed by ${other}`;
    wrap.append(also);
  }
  return wrap;
}

function tableRow(el, row) {
  const line = el("div", "rp-row");
  const callsign = el("span", "rp-call", row.callsign || "—");
  callsign.style.borderLeftColor = bandColor(row.band);
  line.append(
    callsign,
    el("span", "rp-out", mhz(row.output_hz)),
    el("span", "rp-off", offsetLabel(row.offset_hz)),
    el("span", "rp-tone", row.tone || "—"),
    el("span", "rp-mode", modeText(row) || "—"),
    el("span", "rp-place", row.place || ""),
    el("span", "rp-dist", row.km === null || row.km === undefined ? "—" : kmLabel(row.km)),
    el("span", "rp-brg", bearingLabel(row.bearing)),
  );
  line.append(sourceBadges(el, row));
  // What an operator keys in, in plain words, under the row: a colour code, a
  // module, a DG-ID. Nothing is drawn for a detail the source did not supply.
  const details = digitalDetails(row);
  if (details.length) line.append(el("span", "rp-detail", details.join(" · ")));
  return line;
}

function header(el) {
  const line = el("div", "rp-row rp-head");
  const columns = [
    ["rp-call", "CALL"], ["rp-out", "OUT MHz"], ["rp-off", "OFFSET"], ["rp-tone", "TONE"],
    ["rp-mode", "MODE"], ["rp-place", "PLACE"], ["rp-dist", "DIST"], ["rp-brg", "BRG"],
    ["rp-src", "SOURCE"],
  ];
  for (const [cls, text] of columns) line.append(el("span", cls, text));
  return line;
}

export function render(root, { data, el }) {
  const snapshot = data.repeaters;
  if (!snapshot?.data) {
    root.replaceChildren(el("p", "empty", "waiting for the first read of the repeater layers…"));
    return;
  }
  const payload = snapshot.data;
  if (!payload.available) {
    root.replaceChildren(el("p", "empty", payload.reason || "no repeater layers"));
    return;
  }

  const rerender = () => render(root, { data, el });
  redraw = rerender;
  if (!listening) {
    listening = true;
    window.addEventListener(CENTRE_EVENT, () => redraw?.());
  }

  // The station is the default and its numbers are the collector's, so the
  // first paint computes nothing. A chosen centre recomputes every row here.
  const store = storage();
  const chosen = store ? loadCentre(store) : null;
  const rows = chosen ? withCentre(payload.rows ?? [], chosen) : (payload.rows ?? []);
  const measured = Boolean(chosen || payload.station);
  const offered = facets(rows);

  // A saved filter for a band, mode or source this machine no longer has would
  // hide every row with nothing on screen to un-set it. Drop it quietly.
  const kept = {
    bands: state.bands.filter((b) => offered.bands.includes(b)),
    modes: state.modes.filter((m) => offered.modes.includes(m)),
  };
  if (kept.bands.length !== state.bands.length || kept.modes.length !== state.modes.length) {
    state.bands = kept.bands;
    state.modes = kept.modes;
    persist();
  }
  if (state.source && !offered.sources.includes(state.source)) state.source = null;

  const parts = [];

  const filters = el("div", "rp-filters");
  filters.append(centreRow(el, payload, chosen));
  if (centreError) filters.append(el("p", "error", centreError));
  filters.append(multiRow(el, "BAND", "bands", offered.bands, offered.bandCounts, rerender));
  if (payload.has_modes) {
    filters.append(
      multiRow(el, "MODE", "modes", offered.modes, offered.modeCounts, rerender, [
        ["DIGITAL", shortcutModes("digital", offered.modes), "every digital mode on offer"],
        ["ANALOG", shortcutModes("analog", offered.modes), "FM and analog TV"],
      ]),
    );
  } else {
    // An engine that predates the mode vocabulary: the table still works, and
    // the one thing missing says what to do about it.
    const row = el("div", "rp-filter");
    row.append(
      el("span", "rp-filter-label", "MODE"),
      el("span", "rp-note rp-nomodes", "update the engine for mode filters"),
    );
    filters.append(row);
  }
  filters.append(
    chipRow(el, "SOURCE", "source", offered.sources.map((s) => [s, s]), rerender),
  );
  if (measured) {
    filters.append(
      chipRow(el, "WITHIN", "withinKm", KM_STEPS.map((k) => [k, `${k} km`]), rerender, "ANY"),
    );
  }
  parts.push(filters);

  const matching = filterRows(rows, state);
  if (!matching.length) {
    parts.push(el("p", "empty", rows.length ? "no repeater matches those filters" : "no repeaters"));
  } else {
    const list = el("div", "rp-list");
    list.append(header(el));
    for (const row of matching.slice(0, MAX_ROWS)) list.append(tableRow(el, row));
    parts.push(list);
    const shown = Math.min(matching.length, MAX_ROWS);
    parts.push(
      el(
        "p",
        "rp-note",
        `${shown} of ${matching.length} matching · ${rows.length} on this machine` +
          (payload.grid ? ` · from ${payload.grid}` : "") +
          (payload.merged ? ` · ${payload.merged} merged across sources` : ""),
      ),
    );
  }

  // The data is what was imported, not the world. Said when the centre is far
  // from every row, and always when there are none.
  const coverage = measured ? coverageNote(rows, state.withinKm) : null;
  if (coverage) parts.push(el("p", "rp-note rp-coverage", coverage));

  if (payload.truncated) {
    parts.push(
      el("p", "rp-note", `${payload.truncated} farther repeaters were left out to keep this panel light.`),
    );
  }
  if (payload.distance_note && !chosen) parts.push(el("p", "rp-note", payload.distance_note));
  for (const skipped of payload.skipped ?? []) {
    parts.push(el("p", "rp-note", `layer ${skipped.layer} left out: ${skipped.reason}`));
  }

  // Credits are printed where the data is shown, one per source present.
  for (const credit of payload.credits ?? []) parts.push(el("p", "rp-credit", credit));

  // Said once, next to the credit. The two cases are different statements:
  // the machine's own page is told what it may not do; another host is told
  // something is held back rather than shown a short list as the whole one.
  if (payload.has_personal_use) {
    parts.push(
      el(
        "p",
        "rp-note",
        "RepeaterBook data is for this machine's own use: it is shown here, never served to " +
          "another computer, and never exported.",
      ),
    );
  } else if (payload.withheld) {
    parts.push(
      el(
        "p",
        "rp-note",
        `${payload.withheld} repeater${payload.withheld === 1 ? "" : "s"} from a source whose ` +
          "terms keep them on the machine this dashboard runs on are not shown to you.",
      ),
    );
  }

  parts.push(
    el(
      "p",
      "rp-note",
      `read from the local engine ${relativeAge(snapshot.fetched_at)} · ` +
        "nothing was fetched from anyone to show this.",
    ),
  );
  root.replaceChildren(...parts);
}

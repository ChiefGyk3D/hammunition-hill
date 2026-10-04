// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Repeaters near the station, from the layers Hammunition already holds.
//
// Tier 0: the collector asked the local engine for its repeater layers and
// worked out distance and bearing from the grid square's centre. This panel
// only filters and draws. Nothing here fetches, and there is deliberately no
// "near X" search -- a search box would be a way to ask somebody where a place
// is, and nothing here asks anybody anything.
//
// There is no export button, on purpose. Some of these rows are RepeaterBook's
// (marked personal use by the engine), and its terms keep them on the machine
// that fetched them; the server withholds them from every other host, and a
// file-saving button would be a way around that. tests/test_repeaters.py holds it.

import { recall, relativeAge, remember } from "../../lib/format.js";
import { bandColor } from "../../lib/bandcolors.js";
import {
  DEFAULT_FILTERS,
  bearingLabel,
  facets,
  filterRows,
  kmLabel,
  mhz,
  offsetLabel,
} from "../../lib/repeaters.js";

const MAX_ROWS = 60;
const KM_STEPS = [25, 50, 100, 250];

const state = {
  band: recall("repeaters.band", DEFAULT_FILTERS.band),
  mode: recall("repeaters.mode", DEFAULT_FILTERS.mode),
  source: recall("repeaters.source", DEFAULT_FILTERS.source),
  withinKm: recall("repeaters.withinKm", DEFAULT_FILTERS.withinKm),
};

function chipRow(el, label, key, options, rerender, allLabel = "ALL") {
  const row = el("div", "rp-filter");
  row.append(el("span", "rp-filter-label", label));
  const chips = el("div", "chips");
  for (const [option, text] of [[null, allLabel], ...options]) {
    const chip = el("button", "chip", text);
    chip.type = "button";
    const on = state[key] === option;
    if (on) chip.classList.add("on");
    chip.setAttribute("aria-pressed", String(on));
    chip.addEventListener("click", () => {
      state[key] = option;
      remember(`repeaters.${key}`, option);
      rerender();
    });
    chips.append(chip);
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
    el("span", "rp-mode", row.mode || "—"),
    el("span", "rp-place", row.place || ""),
    el("span", "rp-dist", row.km === null || row.km === undefined ? "—" : kmLabel(row.km)),
    el("span", "rp-brg", bearingLabel(row.bearing)),
  );
  line.append(sourceBadges(el, row));
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
  const rows = payload.rows ?? [];
  const offered = facets(rows);

  // A saved filter for a band, mode or source this machine no longer has would
  // hide every row with nothing on screen to un-set it. Drop it quietly.
  if (state.band && !offered.bands.includes(state.band)) state.band = null;
  if (state.mode && !offered.modes.includes(state.mode)) state.mode = null;
  if (state.source && !offered.sources.includes(state.source)) state.source = null;

  const parts = [];

  const filters = el("div", "rp-filters");
  filters.append(
    chipRow(el, "BAND", "band", offered.bands.map((b) => [b, b]), rerender),
    chipRow(el, "MODE", "mode", offered.modes.map((m) => [m, m]), rerender),
    chipRow(el, "SOURCE", "source", offered.sources.map((s) => [s, s]), rerender),
  );
  if (payload.station) {
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

  if (payload.truncated) {
    parts.push(
      el("p", "rp-note", `${payload.truncated} farther repeaters were left out to keep this panel light.`),
    );
  }
  if (payload.distance_note) parts.push(el("p", "rp-note", payload.distance_note));
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

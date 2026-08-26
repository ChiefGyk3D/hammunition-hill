// The flagship panel.
//
// Filtering happens here, in the browser, over the full spot array the snapshot
// already contains. The server is never asked what you filtered for -- it does
// not have an endpoint that could answer, and that is the point.
//
// Needed-slot colouring comes from the operator's own log, read off this disk by
// the collector. No hosted dashboard can do this without asking you to upload
// your log first.

import { distance, filterRow, khz, neededClass, recall, remember } from "../../lib/format.js";

const MODE_GROUPS = {
  CW: ["CW"],
  PHONE: ["SSB", "USB", "LSB", "AM", "FM"],
  DIGITAL: ["FT8", "FT4", "JS8", "RTTY", "PSK31", "PSK", "JT65", "JT9", "Q65", "MSK144", "OLIVIA"],
};

const CONTINENTS = [["NA", "NA"], ["SA", "SA"], ["EU", "EU"], ["AS", "AS"], ["AF", "AF"], ["OC", "OC"]];
const MAX_ROWS = 60;

const state = {
  band: recall("spots.band", null),
  mode: recall("spots.mode", null),
  continent: recall("spots.continent", null),
  neededOnly: recall("spots.neededOnly", false),
  selected: null,
};

function matches(spot) {
  if (state.band && spot.band !== state.band) return false;
  if (state.continent && spot.continent !== state.continent) return false;
  if (state.mode) {
    const accepted = MODE_GROUPS[state.mode] ?? [state.mode];
    if (!spot.mode || !accepted.includes(spot.mode)) return false;
  }
  if (state.neededOnly && !neededClass(spot.needed)) return false;
  return true;
}

/**
 * Collapse repeat spots of the same station on the same band.
 *
 * A busy cluster shows one DX station spotted by a dozen skimmers within a
 * minute. All of those are the same operating opportunity, and showing them
 * separately pushes everything else off the screen. We keep the newest, and
 * carry the count -- how many people are spotting a station is itself a signal
 * about how workable it is.
 */
function collapse(spots) {
  const seen = new Map();
  for (const spot of spots) {
    const key = `${spot.call}|${spot.band ?? "?"}`;
    const existing = seen.get(key);
    if (existing) {
      existing.reports += 1;
    } else {
      seen.set(key, { ...spot, reports: 1 });
    }
  }
  return [...seen.values()];
}

function bandsPresent(spots) {
  const seen = new Map();
  for (const spot of spots) {
    if (spot.band && !seen.has(spot.band)) seen.set(spot.band, spot.band_sort ?? 99);
  }
  return [...seen.entries()].sort((a, b) => a[1] - b[1]).map(([band]) => [band, band]);
}

function detail(el, spot) {
  const box = el("div", "detail");
  const rows = [
    ["Entity", spot.entity ?? "unknown"],
    ["Continent", spot.continent ?? "—"],
    ["Frequency", `${khz(spot.khz)} kHz`],
    ["Band / mode", `${spot.band ?? "?"} ${spot.mode ?? "?"}${spot.mode_inferred ? " (inferred)" : ""}`],
    ["Spotter", spot.spotter ?? "—"],
  ];

  if (spot.path) {
    rows.push(
      ["Short path", `${spot.path.bearing}° ${spot.path.compass}`],
      ["Long path", `${spot.path.bearing_long}°`],
      ["Distance", distance(spot.path)],
    );
  }
  if (spot.comment) rows.push(["Comment", spot.comment]);
  if (spot.entity_approximate) {
    rows.push(["Note", "entity from the built-in prefix table (approximate)"]);
  }

  for (const [label, value] of rows) {
    const row = el("div", "detail-row");
    row.append(el("span", "detail-label", label), el("span", "detail-value", value));
    box.append(row);
  }
  return box;
}

function spotRow(el, spot, onSelect) {
  const row = el("tr", "spot-row");
  const need = neededClass(spot.needed);
  if (need) row.classList.add(need.cls);
  if (state.selected === spot.call) row.classList.add("selected");

  const callCell = el("td", "spot-call");
  callCell.append(el("span", null, spot.call));
  if (need) callCell.append(el("span", `need-badge ${need.cls}`, need.label));
  if (spot.reports > 1) callCell.append(el("span", "spot-reports", `\u00d7${spot.reports}`));

  const bearing = el("td", "spot-bearing", spot.path ? `${Math.round(spot.path.bearing)}°` : "—");

  row.append(
    callCell,
    el("td", "spot-freq", khz(spot.khz)),
    el("td", "spot-band", spot.band ?? "—"),
    el("td", `spot-mode${spot.mode_inferred ? " inferred" : ""}`, spot.mode ?? "—"),
    el("td", "spot-entity", spot.entity ?? "—"),
    bearing,
    el("td", "spot-time", spot.time ?? ""),
  );

  row.tabIndex = 0;
  const select = () => onSelect(state.selected === spot.call ? null : spot.call);
  row.addEventListener("click", select);
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      select();
    }
  });
  return row;
}

export function render(root, { data, el }) {
  const payload = data.cluster?.data;
  if (!payload) {
    root.replaceChildren(el("p", "empty", "waiting for the cluster connection…"));
    return;
  }

  const all = collapse(payload.spots ?? []);
  const rerender = () => render(root, { data, el });
  const parts = [];

  // --- filters ---
  const filters = el("div", "filters");
  filters.append(
    filterRow(el, {
      key: "spots.band",
      options: bandsPresent(all),
      value: state.band,
      onChange: (value) => { state.band = value; rerender(); },
    }),
    filterRow(el, {
      key: "spots.mode",
      options: Object.keys(MODE_GROUPS).map((m) => [m, m]),
      value: state.mode,
      onChange: (value) => { state.mode = value; rerender(); },
    }),
    filterRow(el, {
      key: "spots.continent",
      options: CONTINENTS,
      value: state.continent,
      onChange: (value) => { state.continent = value; rerender(); },
    }),
  );

  if (payload.has_log) {
    const toggle = el("button", "chip needed-toggle", "NEEDED ONLY");
    toggle.type = "button";
    if (state.neededOnly) toggle.classList.add("on");
    toggle.setAttribute("aria-pressed", String(state.neededOnly));
    toggle.addEventListener("click", () => {
      state.neededOnly = !state.neededOnly;
      remember("spots.neededOnly", state.neededOnly);
      rerender();
    });
    filters.append(toggle);
  }
  parts.push(filters);

  // --- table ---
  const shown = all.filter(matches);
  if (shown.length === 0) {
    parts.push(el("p", "empty", all.length ? "no spots match these filters" : "no spots yet"));
    root.replaceChildren(...parts);
    return;
  }

  const table = el("table", "spots");
  const thead = el("thead");
  const headRow = el("tr");
  for (const label of ["Call", "kHz", "Band", "Mode", "Entity", "Brg", "UTC"]) {
    headRow.append(el("th", null, label));
  }
  thead.append(headRow);
  table.append(thead);

  const tbody = el("tbody");
  const onSelect = (call) => { state.selected = call; rerender(); };
  for (const spot of shown.slice(0, MAX_ROWS)) {
    tbody.append(spotRow(el, spot, onSelect));
    if (state.selected === spot.call) {
      const detailRow = el("tr", "detail-host");
      const cell = el("td");
      cell.colSpan = 7;
      cell.append(detail(el, spot));
      detailRow.append(cell);
      tbody.append(detailRow);
    }
  }
  table.append(tbody);

  const scroller = el("div", "scroll");
  scroller.append(table);
  parts.push(scroller);

  const total = payload.count ?? all.length;
  const summary = shown.length === all.length
    ? `${all.length} stations from ${total} spots`
    : `${shown.length} of ${all.length} stations`;
  parts.push(el("p", "count", payload.has_log ? summary : `${summary} · no log loaded`));

  root.replaceChildren(...parts);
}

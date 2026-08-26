// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Callsign lookup, resolved locally.
//
// Every lookup runs against the prefix table the collector published, in this
// browser, with no request. That is what keeps it instant and what keeps the
// collector free of request-driven work -- the property the whole architecture
// rests on. It also means the callsign you typed never leaves your machine.
//
// The trade-off is honest and worth knowing: this gives you the entity, the
// heading, the distance, and whether you have worked that entity. It does not
// give you a name and address, because that needs a third-party service and a
// request per lookup. See docs/ARCHITECTURE.md for why that is a deliberate
// line rather than a missing feature.

import { distance, recall, remember } from "../../lib/format.js";
import { latLonToGrid, pathTo, prefixTable } from "../../lib/callsign.js";

const state = { query: recall("callsign.last", ""), table: null };

function field(el, label, value, extra) {
  const row = el("div", "detail-row");
  row.append(el("span", "detail-label", label), el("span", "detail-value", value));
  if (extra) row.append(el("span", "cs-extra", extra));
  return row;
}

function result(el, call, table, station, worked) {
  const entity = table.lookup(call);
  if (!entity) {
    return [el("p", "empty", `no entity matches ${call.toUpperCase()}`)];
  }

  const parts = [];
  const head = el("div", "cs-result");
  head.append(el("span", "cs-call", call.toUpperCase()), el("span", "cs-entity", entity.name));

  if (worked) {
    const isWorked = worked.entities.includes(entity.name);
    const isConfirmed = worked.confirmed.includes(entity.name);
    const label = isConfirmed ? "CONFIRMED" : isWorked ? "WORKED" : "NEW ONE";
    const cls = isConfirmed ? "cs-confirmed" : isWorked ? "cs-worked" : "cs-new";
    head.append(el("span", `need-badge ${cls}`, label));
  }
  parts.push(head);

  const detail = el("div", "detail");
  detail.append(field(el, "Continent", entity.continent ?? "—"));
  if (entity.cqZone) detail.append(field(el, "CQ zone", String(entity.cqZone)));
  if (entity.prefix) detail.append(field(el, "Matched", entity.prefix));

  const grid = latLonToGrid(entity.lat, entity.lon, 4);
  if (grid) detail.append(field(el, "Grid", grid, "entity centre"));

  const path = pathTo(station, entity.lat, entity.lon);
  if (path) {
    detail.append(
      field(el, "Short path", `${path.bearing}° ${path.compass}`),
      field(el, "Long path", `${path.bearing_long}°`),
      field(el, "Distance", distance(path)),
    );
  } else {
    detail.append(field(el, "Path", "set [station] grid in config for headings"));
  }

  if (table.approximate) {
    detail.append(field(el, "Note", "built-in prefix table — approximate"));
  }
  parts.push(detail);
  return parts;
}

export function render(root, { data, el }) {
  const prefixes = data.prefixes?.data;
  if (!prefixes) {
    root.replaceChildren(el("p", "empty", "prefix table not published yet"));
    return;
  }
  if (!state.table) state.table = prefixTable(prefixes);

  const station = data.station?.data ?? {};
  const worked = data.log?.data?.worked ?? null;

  const parts = [];

  const form = el("div", "cs-form");
  const input = el("input", "cs-input");
  input.type = "text";
  input.placeholder = "callsign, e.g. JA1XYZ or DL/W1AW";
  input.value = state.query;
  input.spellcheck = false;
  input.autocomplete = "off";
  input.setAttribute("aria-label", "Callsign to look up");
  input.addEventListener("input", (event) => {
    state.query = event.target.value;
    remember("callsign.last", state.query);
    render(root, { data, el });
    // Re-rendering replaces the node, so restore focus and caret.
    const next = root.querySelector(".cs-input");
    if (next) {
      next.focus();
      next.setSelectionRange(next.value.length, next.value.length);
    }
  });
  form.append(input);
  parts.push(form);

  const query = state.query.trim();
  if (query.length >= 2) {
    parts.push(...result(el, query, state.table, station, worked));
  } else {
    parts.push(el("p", "empty", "type a callsign — resolved locally, nothing is sent anywhere"));
  }

  const foot = el("p", "count", `${state.table.size} prefixes · ${state.table.source}`);
  parts.push(foot);

  root.replaceChildren(...parts);
}

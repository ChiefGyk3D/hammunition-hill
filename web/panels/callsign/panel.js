// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Callsign lookup, resolved locally.
//
// When the server's query endpoint is switched on (query_endpoint = true), the
// panel also asks it -- GET /lookup/<call> against the local index, same
// machine, still nothing leaving it. The endpoint is off by default and probed
// once: a 404 means "not there", and the panel stays purely client-side
// exactly as before. Debounced, because the endpoint is rate limited and a
// keystroke is not a question.
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
import { gridToLatLon, latLonToGrid, pathTo, prefixTable } from "../../lib/callsign.js";
import { effectiveStation } from "../../lib/geolocate.js";

const state = { query: recall("callsign.last", ""), table: null , endpoint: undefined, endpointResult: null, timer: 0 };

function field(el, label, value, extra) {
  const row = el("div", "detail-row");
  row.append(el("span", "detail-label", label), el("span", "detail-value", value));
  if (extra) row.append(el("span", "cs-extra", extra));
  return row;
}

function ageText(hours) {
  if (!Number.isFinite(hours)) return "cached";
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

function result(el, call, table, station, worked, lookups) {
  const entity = table.lookup(call);
  const detail = lookups?.results?.[call.toUpperCase()] ?? null;

  if (!entity && !detail) {
    return [el("p", "empty", `no entity matches ${call.toUpperCase()}`)];
  }

  const parts = [];
  const head = el("div", "cs-result");
  head.append(
    el("span", "cs-call", call.toUpperCase()),
    el("span", "cs-entity", entity?.name ?? detail?.country ?? ""),
  );

  if (worked && entity) {
    const isWorked = worked.entities.includes(entity.name);
    const isConfirmed = worked.confirmed.includes(entity.name);
    const label = isConfirmed ? "CONFIRMED" : isWorked ? "WORKED" : "NEW ONE";
    const cls = isConfirmed ? "cs-confirmed" : isWorked ? "cs-worked" : "cs-new";
    head.append(el("span", `need-badge ${cls}`, label));
  }
  parts.push(head);

  const rows = el("div", "detail");

  // Provider data first when we have it -- a real name and a real grid beat an
  // entity centroid, and that is the whole point of enabling a provider.
  if (detail) {
    if (detail.name) rows.append(field(el, "Name", detail.name));
    if (detail.grid) rows.append(field(el, "Grid", detail.grid, "reported"));
    if (detail.state) rows.append(field(el, "Location", detail.state));
    if (detail.license_class) rows.append(field(el, "Class", detail.license_class));
    if (detail.expires) rows.append(field(el, "Expires", detail.expires));
  }

  if (entity) rows.append(field(el, "Continent", entity.continent ?? "—"));
  if (entity?.cqZone) rows.append(field(el, "CQ zone", String(entity.cqZone)));
  if (entity?.prefix) rows.append(field(el, "Matched", entity.prefix));

  // Prefer the reported grid over the entity centroid for the path.
  let lat = entity?.lat;
  let lon = entity?.lon;
  let pathNote = "entity centre";
  if (detail?.grid) {
    const fromGrid = gridToLatLon(detail.grid);
    if (fromGrid) {
      [lat, lon] = fromGrid;
      pathNote = "from reported grid";
    }
  }

  if (!detail?.grid && entity) {
    const grid = latLonToGrid(entity.lat, entity.lon, 4);
    if (grid) rows.append(field(el, "Grid", grid, "entity centre"));
  }

  const path = pathTo(station, lat, lon);
  if (path) {
    rows.append(
      field(el, "Short path", `${path.bearing}° ${path.compass}`, pathNote),
      field(el, "Long path", `${path.bearing_long}°`),
      field(el, "Distance", distance(path)),
    );
  } else {
    rows.append(field(el, "Path", "set [station] grid in config for headings"));
  }

  if (!detail && table.approximate) {
    rows.append(field(el, "Note", "built-in prefix table — approximate"));
  }
  if (detail) {
    // Age is shown only when the entry is past its refresh window. A stale
    // record beats a blank one in a field with no signal -- but it has to say
    // so, or the panel is quietly asserting something it does not know.
    const age = detail.stale
      ? `${detail.source} · ${ageText(detail.age_hours)} old`
      : detail.source;
    const row = field(el, "Source", age);
    if (detail.stale) row.classList.add("stale-detail");
    rows.append(row);
  }
  parts.push(rows);
  return parts;
}


// Ask the query endpoint, if this server has one. Probed lazily: the first
// query discovers whether it exists (404 = no, remembered), and every later
// keystroke is debounced 300 ms so typing a call does not spend the server's
// rate budget one letter at a time.
function queryEndpoint(query, redraw) {
  if (state.endpoint === false) return;
  const call = query.toUpperCase();
  if (state.endpointResult?.for === call) return;
  clearTimeout(state.timer);
  state.timer = setTimeout(async () => {
    try {
      const response = await fetch(`./lookup/${encodeURIComponent(call)}`, { cache: "no-store" });
      if (response.status === 404) {
        state.endpoint = false;
        return;
      }
      state.endpoint = true;
      if (!response.ok) return;
      const payload = await response.json();
      state.endpointResult = { ...payload, for: call };
      redraw();
    } catch {
      /* endpoint unreachable: the panel already works without it */
    }
  }, 300);
}

export function render(root, { data, el }) {
  const prefixes = data.prefixes?.data;
  if (!prefixes) {
    root.replaceChildren(el("p", "empty", "prefix table not published yet"));
    return;
  }
  if (!state.table) state.table = prefixTable(prefixes);

  // GPS-aware: a browser-side fix (FIND MY GRID on the map) moves the
  // origin these bearings and distances are measured from. "How far was
  // that" means from where you are, not from where config says home is.
  const station = effectiveStation(data.station?.data ?? {});
  const worked = data.log?.data?.worked ?? null;
  const lookups = data.lookups?.data ?? null;

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
    parts.push(...result(el, query, state.table, station, worked, lookups));
    queryEndpoint(query, () => render(root, { data, el }));
    const hit = state.endpointResult;
    if (hit && hit.for === query.toUpperCase() && hit.found && hit.record) {
      const rows = el("div", "cs-rows");
      const record = hit.record;
      if (record.name) rows.append(field(el, "Licensee", record.name));
      if (record.operator_class) rows.append(field(el, "Class", record.operator_class));
      if (record.city || record.state) {
        rows.append(field(el, "QTH", [record.city, record.state].filter(Boolean).join(", ")));
      }
      if (record.expires) rows.append(field(el, "Expires", record.expires));
      rows.append(field(el, "Source", `${hit.source} · query endpoint`));
      parts.push(rows);
    }
  } else {
    parts.push(el("p", "empty", "type a callsign — resolved locally, nothing is sent anywhere"));
  }

  // Name the whole chain, not just its head: "resolved via fcc_uls" when qrz is
  // also configured tells you less than nothing about why a call did not
  // resolve. And say plainly when the network half is unreachable, because at a
  // park that is the normal state and it explains what you are seeing.
  const chain = lookups?.providers?.length
    ? lookups.providers.map((p) => p.name).join(" → ")
    : lookups?.provider;
  const offline = lookups?.network_down ? " · network down, offline sources only" : "";
  const stale = lookups?.stale_served ? ` · ${lookups.stale_served} stale` : "";
  const detail = lookups
    ? ` · ${lookups.resolved} resolved via ${chain}${stale}${offline}`
    : " · no lookup provider";
  const foot = el("p", "count", `${state.table.size} prefixes${detail}`);
  parts.push(foot);

  root.replaceChildren(...parts);
}

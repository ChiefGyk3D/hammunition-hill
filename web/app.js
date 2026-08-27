// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Hammunition Hill - panel host.
//
// The browser only ever talks to this origin. Snapshots are polled as static
// JSON files; there is no API to call and no query to construct. Panels get
// their data handed to them and render into a container they do not own.

const GRID = document.getElementById("grid");
const STATUS = document.getElementById("status");
const STATION_EL = document.getElementById("station");
const TABS = document.getElementById("tabs");

// Snapshot poll interval. Files are small and local, so this is cheap; the
// collector's own upstream intervals are what actually rate-limit anything.
const POLL_MS = 10_000;

/** @type {Map<string, object>} latest snapshot per source id */
const snapshots = new Map();
/** @type {Array<{manifest: object, module: object, root: HTMLElement}>} */
const panels = [];
/** @type {Map<string, {manifest: object, module: object}>} loaded panel modules */
const loaded = new Map();

import { recall, remember } from "./lib/format.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text; // never innerHTML
  return node;
};

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function relativeAge(iso) {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function buildTabs(dashboards, active, onPick) {
  const bar = el("nav", "tabs");
  bar.setAttribute("aria-label", "Dashboards");
  for (const dash of dashboards) {
    const tab = el("button", "tab", dash.name);
    tab.type = "button";
    if (dash.id === active) tab.classList.add("on");
    tab.setAttribute("aria-current", dash.id === active ? "page" : "false");
    tab.addEventListener("click", () => onPick(dash.id));
    bar.append(tab);
  }
  return bar;
}

function buildFrame(manifest) {
  const panel = el("section", "panel");
  panel.dataset.panel = manifest.id;
  // A panel may ask for more grid columns; the CSS caps it at what fits.
  if (manifest.span > 1) panel.style.setProperty("--span", String(manifest.span));

  const head = el("div", "panel-head");
  head.append(
    el("span", "panel-title", manifest.name),
    el("span", `tier tier-${manifest.tier}`, `T${manifest.tier}`),
  );
  const age = el("span", "panel-age", "");
  head.append(age);

  const body = el("div", "panel-body");
  panel.append(head, body);
  GRID.append(panel);
  return { body, age };
}

/**
 * Freshness is shown, never hidden. A stale panel and a blank panel are
 * different problems, and with the WAN down that distinction is the whole
 * point of keeping the last good snapshot.
 */
function updateAge(entry) {
  const relevant = entry.manifest.sources
    .map((id) => snapshots.get(id))
    .filter(Boolean);
  if (relevant.length === 0) {
    entry.age.textContent = entry.manifest.tier === 0 ? "" : "no data";
    entry.age.className = "panel-age";
    return;
  }

  const oldest = relevant.reduce((a, b) =>
    Date.parse(a.fetched_at) < Date.parse(b.fetched_at) ? a : b,
  );
  const failed = relevant.find((s) => s.error);

  // A stale window of 0 means "this does not age", not "this is already stale".
  //
  // Some snapshots are published config rather than fetched data -- the tile
  // list, the prefix table, the station. Their timestamp is when the collector
  // started, which is not a freshness claim about anything, and running the
  // usual comparison against 0 painted the imagery panel permanently amber for
  // a file that was exactly as correct as the day it was written. Showing no
  // age at all is the honest answer: there is nothing here to be stale.
  const ageless = relevant.every((s) => s.stale_after_seconds === 0);
  if (ageless && !failed) {
    entry.age.textContent = "";
    entry.age.className = "panel-age";
    return;
  }

  const isStale =
    (Date.now() - Date.parse(oldest.fetched_at)) / 1000 >
    (oldest.stale_after_seconds || Infinity);

  entry.age.textContent = failed
    ? `${relativeAge(oldest.fetched_at)} · fetch failed`
    : relativeAge(oldest.fetched_at);
  entry.age.className =
    "panel-age" + (failed ? " failed" : isStale ? " stale" : "");
}

function renderPanel(entry, station) {
  const data = {};
  for (const id of entry.manifest.sources) data[id] = snapshots.get(id) ?? null;
  try {
    entry.module.render(entry.body, { data, station, el });
  } catch (err) {
    entry.body.replaceChildren(el("p", "error", `panel error: ${err.message}`));
  }
  updateAge(entry);
}

async function poll(station) {
  const wanted = new Set(panels.flatMap((p) => p.manifest.sources));
  const results = await Promise.allSettled(
    [...wanted].map(async (id) => [id, await getJSON(`./data/${id}.json`)]),
  );

  let missing = 0;
  for (const result of results) {
    if (result.status === "fulfilled") {
      const [id, snapshot] = result.value;
      snapshots.set(id, snapshot);
    } else {
      missing += 1;
    }
  }

  for (const entry of panels) renderPanel(entry, station);

  STATUS.textContent = missing
    ? `${wanted.size - missing}/${wanted.size} sources · collector may still be starting`
    : `${wanted.size} sources · updated ${new Date().toLocaleTimeString()}`;
}

async function main() {
  let dashboards = [];
  let station = {};

  try {
    const index = await getJSON("./panels/index.json");
    dashboards = index.dashboards ?? [];
    // A flat `enabled` list still works: it becomes one unnamed dashboard.
    if (dashboards.length === 0 && index.enabled) {
      dashboards = [{ id: "all", name: "Dashboard", panels: index.enabled }];
    }
  } catch (err) {
    STATUS.textContent = "could not load panel index";
    GRID.append(el("p", "error", `panels/index.json: ${err.message}`));
    return;
  }

  try {
    station = (await getJSON("./data/station.json")).data ?? {};
  } catch {
    // Not fatal: tier 0 panels degrade to UTC-only without a grid square.
    station = {};
  }

  STATION_EL.textContent = [station.callsign, station.grid]
    .filter(Boolean)
    .join(" \u00b7 ");

  // Load every panel module once, up front. They are small and local, and
  // loading on tab switch would make the first click on each tab feel slow.
  for (const dash of dashboards) {
    for (const id of dash.panels) {
      if (loaded.has(id)) continue;
      try {
        const manifest = await getJSON(`./panels/${id}/panel.json`);
        const module = await import(`./panels/${id}/panel.js`);
        loaded.set(id, { manifest, module });
      } catch (err) {
        console.error(`panel ${id} failed to load`, err);
        loaded.set(id, { error: err.message });
      }
    }
  }

  let active = recall("dashboard", dashboards[0]?.id);
  if (!dashboards.some((d) => d.id === active)) active = dashboards[0]?.id;

  // `fetchNow` exists only for the first call, which is immediately followed by
  // an awaited poll. Every other call is a tab click and must fetch.
  const show = (id, { fetchNow = true } = {}) => {
    active = id;
    remember("dashboard", id);
    panels.length = 0;
    GRID.replaceChildren();

    const dash = dashboards.find((d) => d.id === id);
    for (const panelId of dash?.panels ?? []) {
      const entry = loaded.get(panelId);
      if (!entry) continue;
      if (entry.error) {
        GRID.append(el("p", "error", `panel ${panelId}: ${entry.error}`));
        continue;
      }
      const { body, age } = buildFrame(entry.manifest);
      panels.push({ manifest: entry.manifest, module: entry.module, body, age });
    }

    TABS.replaceChildren(buildTabs(dashboards, active, show));
    for (const entry of panels) renderPanel(entry, station);

    // poll() only fetches what the *visible* dashboard's panels ask for, so
    // switching to a tab for the first time finds an empty cache and every
    // panel on it paints its "waiting…" placeholder. Without this line they
    // stay that way until the next interval -- up to ten seconds of staring at
    // data that is already on disk, one metre away.
    if (fetchNow) poll(station);
  };

  show(active, { fetchNow: false });

  await poll(station);
  setInterval(() => poll(station), POLL_MS);

  // Tier 0 panels tick on their own clock, independent of any fetch.
  setInterval(() => {
    for (const entry of panels) {
      if (entry.manifest.tier === 0) renderPanel(entry, station);
    }
  }, 1000);
}

main();

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

// --- personal layout ---------------------------------------------------
// The shipped arrangement lives in panels/index.json; the operator's own
// lives in this browser. That split is deliberate: the server stays a static
// file server with no write path, and each display keeps its own layout --
// the shack TV, the phone in the field and the laptop are different rooms
// with different jobs, so "per browser" is a feature, not a limitation.
//
// The stored order is reconciled against the shipped list on every read:
// panels added to a dashboard since the layout was saved are appended rather
// than lost, and panels that no longer exist drop out silently.
function layoutFor(dash) {
  const stored = recall(`layout.${dash.id}`, null) || {};
  const shipped = dash.panels;
  const order = (Array.isArray(stored.order) ? stored.order : []).filter((id) =>
    shipped.includes(id),
  );
  for (const id of shipped) if (!order.includes(id)) order.push(id);
  const hidden = (Array.isArray(stored.hidden) ? stored.hidden : []).filter((id) =>
    shipped.includes(id),
  );
  return { order, hidden };
}

function saveLayout(dash, layout) {
  remember(`layout.${dash.id}`, { order: layout.order, hidden: layout.hidden });
}

function resetLayout(dash) {
  try {
    localStorage.removeItem(`hh.layout.${dash.id}`);
  } catch {
    /* storage unavailable: nothing was saved either */
  }
}

let editing = false;
// The panel id being dragged in customize mode, module-level because the
// dragover fires on the panel under the pointer, not the one that started.
let dragged = null;

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
  const customize = el("button", "tab tab-edit" + (editing ? " on" : ""), editing ? "done" : "customize");
  customize.type = "button";
  customize.setAttribute("aria-pressed", String(editing));
  customize.addEventListener("click", () => {
    editing = !editing;
    onPick(active);
  });
  bar.append(customize);
  return bar;
}

// Panels pack like masonry: the grid's rows are a fine 8px lattice and each
// panel spans as many as its natural height needs. CSS grid alone cannot do
// this -- a row is as tall as the tallest panel in it, so a short panel
// beside a tall one strands the whole difference as dead space. On the
// Operating dashboard that was ~1300px of nothing under the logbook, beside
// the band plan.
//
// Placement is computed here too, not left to the browser. The first version
// used `grid-auto-flow: dense` and let auto-placement fill the holes, and
// that broke the customize mode it shipped alongside: dense placement ignores
// DOM order, so on the stock Home dashboard the reception panel drew *above*
// the reverse beacon that preceded it, and the reorder arrows appeared to do
// nothing -- the browser put the moved panel right back where it had been.
// An arrangement feature the layout algorithm is free to override is not an
// arrangement feature.
//
// So: each panel, in DOM order, lands in the contiguous run of columns whose
// occupied depth is shallowest (leftmost on a tie). Depths only grow, and
// each item takes the global minimum at its turn, so landing rows are
// monotonic in DOM order -- a later panel can sit *beside* an earlier one
// but never above it. That is the property the arrows need: "move later"
// always reads later. It also bottom-balances the columns, which dense flow
// never promised: dense fills interior holes but happily leaves one column
// two panels deeper than its neighbour.
//
// The lattice is measured from the grid, not assumed: the row unit and the
// gap are the stylesheet's to change per breakpoint, and an earlier version
// hardcoded a 12px gap while the phone breakpoint used 8 -- every span came
// out short by the difference, and each panel was painted over by the next.
// N spanned tracks cover N*row + (N-1)*gap, so N must satisfy
// N >= (height + gap) / (row + gap).
function repack() {
  const style = getComputedStyle(GRID);
  const cols = style.gridTemplateColumns.split(" ").length;
  const row = parseFloat(style.gridAutoRows) || 8;
  const gap = parseFloat(style.rowGap) || 12;
  const depth = new Array(cols).fill(1);

  for (const item of GRID.children) {
    if (!(item instanceof HTMLElement)) continue;
    const want = item.classList.contains("edit-bar")
      ? cols
      : Math.min(Number(item.style.getPropertyValue("--span")) || 1, cols);
    // Natural content height: align-items: start means placement never
    // stretches an item, so measuring here cannot feed back into itself.
    //
    // offsetHeight, NOT getBoundingClientRect().height. The TV tiers apply
    // body{zoom}, and the two measure in different spaces: rects come back
    // zoomed while the lattice values above (8px, 12px) and offsetHeight do
    // not. Measured on a 3840px viewport at zoom 1.9: offsetHeight 172,
    // rect 326.7. Dividing a zoomed height by unzoomed tracks handed every
    // panel 1.9x the rows it needed, and the wall display -- the layout's
    // whole reason for the zoom tiers -- rendered each panel trailing a
    // void nearly its own height.
    const height = item.offsetHeight;
    const rows = Math.max(1, Math.ceil((height + gap) / (row + gap)));

    let bestStart = 0;
    let bestRow = Infinity;
    for (let start = 0; start + want <= cols; start++) {
      let landing = 0;
      for (let c = start; c < start + want; c++) landing = Math.max(landing, depth[c]);
      if (landing < bestRow) {
        bestRow = landing;
        bestStart = start;
      }
    }
    item.style.gridColumn = `${bestStart + 1} / span ${want}`;
    item.style.gridRow = `${bestRow} / span ${rows}`;
    for (let c = bestStart; c < bestStart + want; c++) depth[c] = bestRow + rows;
  }
}

// One observer for every panel, but one repack per burst of changes: content
// resizing anywhere can shift every landing row below it, so the whole grid
// is recomputed, coalesced through rAF so a dashboard full of first renders
// costs one pass. The callback runs after layout and before paint, so the
// placement is settled before anything is shown.
let repackQueued = false;
const sizer = new ResizeObserver(() => {
  if (repackQueued) return;
  repackQueued = true;
  requestAnimationFrame(() => {
    repackQueued = false;
    repack();
  });
});

// A breakpoint change alters the lattice and the column count without
// resizing any panel whose content happens to reflow to the same height, so
// repack directly rather than trusting the observer to have a reason to fire.
window.addEventListener("resize", repack);

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
  sizer.observe(panel);
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
    const layout = dash ? layoutFor(dash) : { order: [], hidden: [] };

    if (editing && dash) {
      const bar = el("div", "edit-bar");
      bar.append(
        el(
          "span",
          "edit-hint",
          "Drag panels where you want them, or use the arrows. Changes live in this " +
            "browser only — each display keeps its own. Everything else is config.toml " +
            "on the server; there is no settings page, by design.",
        ),
      );
      if (layout.hidden.length) {
        for (const hiddenId of layout.hidden) {
          const restore = el("button", "chip", `+ ${loaded.get(hiddenId)?.manifest?.name ?? hiddenId}`);
          restore.type = "button";
          restore.addEventListener("click", () => {
            layout.hidden = layout.hidden.filter((x) => x !== hiddenId);
            saveLayout(dash, layout);
            show(id);
          });
          bar.append(restore);
        }
      }
      const reset = el("button", "chip edit-reset", "reset layout");
      reset.type = "button";
      reset.addEventListener("click", () => {
        resetLayout(dash);
        show(id);
      });
      bar.append(reset);
      GRID.append(bar);
      // The bar is a grid child, so it needs a row span like any panel. Without
      // one it takes a single 8px track while standing about four tall, and the
      // first row of panels is placed 8px down and paints over it -- the hint
      // and the reset button end up half-hidden behind the first panel. Same
      // failure the span arithmetic above was written for, one element short.
      sizer.observe(bar);
    }

    for (const panelId of layout.order) {
      if (layout.hidden.includes(panelId)) continue;
      const entry = loaded.get(panelId);
      if (!entry) continue;
      if (entry.error) {
        GRID.append(el("p", "error", `panel ${panelId}: ${entry.error}`));
        continue;
      }
      const { body, age } = buildFrame(entry.manifest);
      panels.push({ manifest: entry.manifest, module: entry.module, body, age });

      if (editing && dash) {
        const frame = body.closest(".panel");
        const controls = el("span", "edit-controls");
        const visible = layout.order.filter((x) => !layout.hidden.includes(x));
        const position = visible.indexOf(panelId);
        const move = (delta) => {
          const neighbour = visible[position + delta];
          if (!neighbour) return;
          const a = layout.order.indexOf(panelId);
          const b = layout.order.indexOf(neighbour);
          [layout.order[a], layout.order[b]] = [layout.order[b], layout.order[a]];
          saveLayout(dash, layout);
          show(id);
        };
        const earlier = el("button", "edit-btn", "◀");
        earlier.type = "button";
        earlier.title = "Move earlier";
        earlier.disabled = position === 0;
        earlier.addEventListener("click", () => move(-1));
        const later = el("button", "edit-btn", "▶");
        later.type = "button";
        later.title = "Move later";
        later.disabled = position === visible.length - 1;
        later.addEventListener("click", () => move(1));
        const hide = el("button", "edit-btn", "✕");
        hide.type = "button";
        hide.title = "Hide this panel";
        hide.addEventListener("click", () => {
          layout.hidden.push(panelId);
          saveLayout(dash, layout);
          show(id);
        });
        controls.append(earlier, later, hide);
        frame?.querySelector(".panel-head")?.append(controls);

        // Drag a panel where you want it. The arrows shipped first and were
        // technically sufficient, and the operator's actual words were "I
        // can't move things around" -- twice. Grabbing the thing you want to
        // move is the gesture people try before they hunt for buttons, so it
        // has to be the gesture that works. HTML5 DnD, no library: the drop
        // reorders layout.order and re-shows, exactly what an arrow does.
        if (frame) {
          frame.draggable = true;
          frame.addEventListener("dragstart", (event) => {
            dragged = panelId;
            frame.classList.add("dragging");
            event.dataTransfer.effectAllowed = "move";
            // Some browsers refuse to start a drag with no payload.
            event.dataTransfer.setData("text/plain", panelId);
          });
          frame.addEventListener("dragend", () => {
            dragged = null;
            for (const p of GRID.querySelectorAll(".panel")) {
              p.classList.remove("dragging", "drop-target");
            }
          });
          frame.addEventListener("dragover", (event) => {
            if (!dragged || dragged === panelId) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            frame.classList.add("drop-target");
          });
          frame.addEventListener("dragleave", () => frame.classList.remove("drop-target"));
          frame.addEventListener("drop", (event) => {
            if (!dragged || dragged === panelId) return;
            event.preventDefault();
            const from = layout.order.indexOf(dragged);
            layout.order.splice(from, 1);
            // Dropping on the upper half lands before the target, lower half
            // after -- the same reading-order the packer lays out.
            const rect = frame.getBoundingClientRect();
            const after = event.clientY > rect.top + rect.height / 2 ? 1 : 0;
            layout.order.splice(layout.order.indexOf(panelId) + after, 0, dragged);
            saveLayout(dash, layout);
            show(id);
          });
        }
      }
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

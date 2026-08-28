// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Tier 2. Read this before adding tiles.
//
// Every other panel on this dashboard is fed by the collector: one machine
// fetches on a fixed schedule and every viewer reads the same local file. These
// tiles are the exception. The browser fetches them itself, which means the
// upstream sees each viewer's IP, their User-Agent, and -- because <img> is not
// a CORS request -- any cookie that host has already set in that browser.
//
// That is the price, and it buys something real: a radar mosaic that updates
// every two minutes is not something a collector can usefully cache, and
// proxying it would turn a static file server into an image relay with an
// outbound fetch per viewer. So the trade is deliberate rather than accidental,
// the panel labels it on the face of every tile, and the operator opts in one
// line of config at a time.
//
// What we can still control, we do: no frames (an image cannot run script, a
// frame from the same host can, so imagery hosts reach img-src and nothing
// else), no referrer, and no path from a tile back into anything the collector
// fetches.

import { recall, remember } from "../../lib/format.js";

// Images are kept alive across renders. The host re-renders every poll; without
// this, every tile would re-download every ten seconds and each open dashboard
// would be hammering a government radar server on the operator's behalf.
/** @type {Map<string, {figure: HTMLElement, img: HTMLImageElement, refresh: () => void, loadedAt: number}>} */
const tiles = new Map();

function bust(url, enabled) {
  if (!enabled) return url;
  // Radar and satellite endpoints serve the same URL with new content, so a
  // cached response is not just stale, it is wrong. Some servers are strict
  // about unknown parameters, which is why `cache_bust = false` exists.
  try {
    const parsed = new URL(url);
    parsed.searchParams.set("_hh", String(Math.floor(Date.now() / 1000)));
    return parsed.toString();
  } catch {
    return url; // Config validated it; if URL disagrees, send it unchanged.
  }
}

function build(el, tile) {
  const figure = el("figure", "tile");

  const img = new Image();
  img.alt = tile.name;
  img.loading = "lazy";
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.className = "tile-img";

  const status = el("figcaption", "tile-cap");
  const name = el("span", "tile-name", tile.name);
  status.append(name);
  if (tile.credit) status.append(el("span", "tile-credit", tile.credit));
  if (tile.mode === "opaque") {
    // The label is the panel's honesty about tiers, per tile: this one is
    // fetched by the collector, so the upstream never sees the viewer.
    status.append(el("span", "tile-credit", "via collector"));
  }
  const state = el("span", "tile-state", "loading…");
  status.append(state);

  img.addEventListener("load", () => {
    state.textContent = new Date().toLocaleTimeString();
    state.className = "tile-state";
    figure.classList.remove("tile-failed");
  });
  img.addEventListener("error", () => {
    // The two likely causes are worth naming: an operator who added a tile
    // without the collector restarting sees a CSP block, and an operator with
    // the WAN down sees a network failure. Both look identical to a broken
    // image icon, so say what to check instead of showing one.
    state.textContent = "unavailable — check the host is reachable and restart to refresh the CSP";
    state.className = "tile-state failed";
    figure.classList.add("tile-failed");
  });

  // Clicking reloads that one tile now, for the operator watching a storm come
  // in who does not want to wait out the interval.
  figure.append(img, status);
  figure.tabIndex = 0;
  figure.title = `${tile.name} — click to refresh now (auto every ${tile.refresh}s)`;
  const refresh = () => {
    state.textContent = "loading…";
    if (tile.mode === "opaque") {
      // The collector fetched this one; the browser reads the sidecar for the
      // image's current name (the extension follows the bytes, so an upstream
      // switching PNG to GIF changes it) and loads same-origin. The upstream
      // never sees this viewer.
      fetch(`./data/tiles/${tile.id}.json`, { cache: "no-store" })
        .then((response) => (response.ok ? response.json() : null))
        .then((meta) => {
          if (meta?.src) {
            img.src = `./${meta.src}?_hh=${Date.now()}`;
            if (meta.error) {
              state.textContent = `stale — ${meta.error}`;
              state.className = "tile-state failed";
            }
          } else {
            state.textContent = "waiting for the collector's first fetch…";
          }
        })
        .catch(() => {
          state.textContent = "waiting for the collector's first fetch…";
        });
    } else {
      img.src = bust(tile.url, tile.cache_bust);
    }
    const entry = tiles.get(tile.id);
    if (entry) entry.loadedAt = Date.now();
  };
  figure.addEventListener("click", refresh);
  figure.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      refresh();
    }
  });

  return { figure, img, refresh };
}

export function render(root, { data, el }) {
  const payload = data.imagery?.data;
  if (!payload) {
    root.replaceChildren(el("p", "empty", "waiting for the collector to publish the tile list…"));
    return;
  }

  const all = payload.tiles ?? [];
  if (all.length === 0) {
    const note = el("p", "empty");
    note.textContent =
      "No imagery configured. Add [[imagery]] entries to config.toml — see docs/IMAGERY.md.";
    root.replaceChildren(note);
    return;
  }

  const groups = payload.groups ?? [];
  // With one group there is nothing to choose between, so the filter row would
  // be a control that does nothing.
  const showFilter = groups.length > 1;
  let active = recall("imagery-group", "all");
  if (active !== "all" && !groups.includes(active)) active = "all";

  const draw = () => {
    const parts = [];

    if (showFilter) {
      const bar = el("div", "tile-groups");
      for (const group of ["all", ...groups]) {
        const button = el("button", "chip" + (group === active ? " on" : ""), group);
        button.type = "button";
        button.addEventListener("click", () => {
          active = group;
          remember("imagery-group", group);
          draw();
        });
        bar.append(button);
      }
      parts.push(bar);
    }

    const wall = el("div", "tile-wall");
    const now = Date.now();
    for (const tile of all) {
      if (active !== "all" && tile.group !== active) continue;

      let entry = tiles.get(tile.id);
      if (!entry) {
        const built = build(el, tile);
        entry = { figure: built.figure, img: built.img, refresh: built.refresh, loadedAt: 0 };
        tiles.set(tile.id, entry);
      }
      // Each tile keeps its own clock. A lightning map on five minutes and a
      // satellite loop on thirty should not be forced onto a shared interval
      // just because they happen to share a panel.
      if (now - entry.loadedAt >= tile.refresh * 1000) entry.refresh();
      wall.append(entry.figure);
    }
    parts.push(wall);

    const note = el("p", "tier-note");
    note.textContent =
      `${all.length} tile${all.length === 1 ? "" : "s"} loaded by this browser directly from ` +
      `${(payload.hosts ?? []).length} external host${(payload.hosts ?? []).length === 1 ? "" : "s"}. ` +
      `They see your IP.`;
    parts.push(note);

    root.replaceChildren(...parts);
  };

  draw();
}

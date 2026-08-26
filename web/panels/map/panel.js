// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The map.
//
// A globe rather than a flat projection because the thing operators most want
// to see -- the path to a station -- is a great circle, and great circles look
// wrong on Mercator. Connecticut to Japan goes over the pole, and only a sphere
// shows that honestly.
//
// Drawn on a 2D canvas with no WebGL and no library. Coastlines are a 60 KB
// Natural Earth outline bundled with the dashboard, so the map works with the
// WAN unplugged -- the greyline is computed from the clock, not fetched.

import { recall, remember } from "../../lib/format.js";
import { gridToLatLon } from "../../lib/callsign.js";
import { subsolarPoint, terminatorRing } from "../../lib/solar.js";
import { clearQth, effectiveStation, locate, saveQth, unavailableReason } from "../../lib/geolocate.js";
import {
  drawGraticule,
  drawLabel,
  drawMarker,
  drawSphere,
  drawTerminator,
  drawWorld,
  greatCircle,
  project,
  strokePath,
  unproject,
} from "../../lib/globe.js";

const BAND_COLORS = {
  "160m": "#e05c5c", "80m": "#e08a3c", "60m": "#e0c23c", "40m": "#5cc45c",
  "30m": "#3cc4a8", "20m": "#3ca0e0", "17m": "#8a7ce0", "15m": "#e07cc4",
  "12m": "#e05c9c", "10m": "#e0603c", "6m": "#e0a83c", "2m": "#9aa4b0",
  "70cm": "#7a8490",
};
const DEFAULT_COLOR = "#8f98a4";

const state = {
  lat0: null,
  lon0: null,
  zoom: recall("map.zoom", 1),
  layers: recall("map.layers", {
    greyline: true, spots: true, arcs: true, parks: true, graticule: true, labels: true,
  }),
  world: null,
  loading: false,
  selected: null,
  canvas: null,
  dragging: null,
  station: {},
  data: null,
};

function css(name, fallback) {
  const value = getComputedStyle(document.body).getPropertyValue(name).trim();
  return value || fallback;
}

function bandColor(band) {
  return BAND_COLORS[band] ?? DEFAULT_COLOR;
}

/** Where a spot is, preferring anything better than an entity centroid. */
function spotLocation(spot) {
  if (spot.lat != null && spot.lon != null) return { lat: spot.lat, lon: spot.lon };
  if (spot.grid) {
    const fromGrid = gridToLatLon(spot.grid);
    if (fromGrid) return { lat: fromGrid[0], lon: fromGrid[1] };
  }
  // Spots carry a path from the collector; recover the far end from it only if
  // we have nothing better. Entity coordinates come through the enricher.
  if (spot.entity_lat != null && spot.entity_lon != null) {
    return { lat: spot.entity_lat, lon: spot.entity_lon };
  }
  return null;
}

function collectPoints(data) {
  const spots = [];

  for (const spot of data.cluster?.data?.spots ?? []) {
    const at = spotLocation(spot);
    if (at) spots.push({ ...spot, at, kind: "dx" });
  }
  for (const [key, program] of [["pota", "POTA"], ["sota", "SOTA"]]) {
    for (const spot of data[key]?.data?.spots ?? []) {
      const at = spotLocation(spot);
      if (at) spots.push({ ...spot, at, kind: "park", program });
    }
  }
  return spots;
}

function draw(canvas, data, station) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const view = {
    lat0: state.lat0 ?? 20,
    lon0: state.lon0 ?? 0,
    radius: (Math.min(width, height) / 2 - 8) * state.zoom,
    cx: width / 2,
    cy: height / 2,
  };

  const ink = css("--ink", "#e3e7ed");
  const muted = css("--muted", "#8f98a4");
  const rule = css("--rule", "#28313c");
  const accent = css("--accent", "#3bc6d0");
  const panel = css("--panel", "#151a21");

  // The day side is lifted above the page background so the night shade has
  // something to be darker *than*. Shading toward the page colour on a
  // near-black panel is invisible, which is exactly what happened first time.
  drawSphere(ctx, view, { fill: "#1b2530", stroke: rule });

  if (state.layers.graticule) drawGraticule(ctx, view, "rgba(255,255,255,0.09)");
  if (state.world) {
    drawWorld(ctx, state.world.rings, view, { stroke: "#5d6b7a", fill: "#243141" });
  }

  if (state.layers.greyline) {
    const sun = subsolarPoint(new Date());
    drawTerminator(ctx, terminatorRing(sun), sun, view, {
      shade: "rgba(0, 0, 0, 0.62)",
      line: "#e8b04a",
    });
  }

  const home = station?.located ? { lat: station.lat, lon: station.lon } : null;
  const points = collectPoints(data);

  if (state.layers.arcs && home) {
    for (const spot of points) {
      if (spot.kind !== "dx") continue;
      ctx.strokeStyle = bandColor(spot.band);
      ctx.globalAlpha = spot === state.selected ? 0.95 : 0.32;
      ctx.lineWidth = spot === state.selected ? 1.8 : 0.8;
      strokePath(ctx, greatCircle(home, spot.at), view);
    }
    ctx.globalAlpha = 1;
  }

  const drawn = [];
  if (state.layers.spots) {
    for (const spot of points) {
      if (spot.kind === "park" && !state.layers.parks) continue;
      const at = drawMarker(ctx, spot.at.lat, spot.at.lon, view, {
        color: spot.kind === "park" ? css("--good", "#4fbf7e") : bandColor(spot.band),
        radius: spot === state.selected ? 4.5 : 2.6,
        ring: spot === state.selected ? accent : null,
      });
      if (at) drawn.push({ spot, at });
    }
  }

  if (home) {
    drawMarker(ctx, home.lat, home.lon, view, { color: accent, radius: 4, ring: ink });
  }

  // Labels only for the selected spot: hamdash labels everything, which is
  // dense and legible on a large screen but unreadable in a dashboard tile.
  if (state.layers.labels && state.selected) {
    const hit = drawn.find((d) => d.spot === state.selected);
    if (hit) {
      const spot = hit.spot;
      const text = `${spot.call} ${spot.khz ? (spot.khz / 1000).toFixed(3) : ""}`.trim();
      drawLabel(ctx, text, hit.at, {
        color: ink,
        background: panel,
        font: '11px ui-monospace, "IBM Plex Mono", monospace',
      });
    }
  }

  state.drawn = drawn;
  return points.length;
}

function layerRow(el, onToggle) {
  const row = el("div", "chips");
  const labels = {
    greyline: "GREYLINE", spots: "SPOTS", arcs: "ARCS",
    parks: "PARKS", graticule: "GRID", labels: "LABEL",
  };
  for (const [key, label] of Object.entries(labels)) {
    const chip = el("button", "chip", label);
    chip.type = "button";
    if (state.layers[key]) chip.classList.add("on");
    chip.setAttribute("aria-pressed", String(Boolean(state.layers[key])));
    chip.addEventListener("click", () => {
      state.layers[key] = !state.layers[key];
      remember("map.layers", state.layers);
      onToggle();
    });
    row.append(chip);
  }
  return row;
}

export function render(root, { data, el }) {
  if (!state.world && !state.loading) {
    state.loading = true;
    fetch("./world.json")
      .then((r) => r.json())
      .then((world) => {
        state.world = world;
      })
      .catch((err) => {
        state.error = err.message;
      })
      .finally(() => {
        state.loading = false;
        render(root, { data, el });
      });
  }

  const station = effectiveStation(data.station?.data ?? {});
  if (state.lat0 === null && station.located) {
    state.lat0 = station.lat;
    state.lon0 = station.lon;
  }

  // Rebuild only the chrome; the canvas is kept so a redraw does not flicker
  // and so a drag in progress is not interrupted by the one-second tick.
  state.station = station;
  state.data = data;
  if (!state.canvas) {
    const canvas = el("canvas", "globe");
    canvas.height = 380;
    state.canvas = canvas;
    attachControls(canvas);
  }

  const redrawNow = () => draw(state.canvas, data, state.station);
  const parts = [layerRow(el, redrawNow)];

  const holder = el("div", "globe-holder");
  holder.append(state.canvas);

  const zoomBox = el("div", "globe-zoom");
  for (const [label, factor] of [["+", 1.25], ["−", 0.8]]) {
    const button = el("button", "chip", label);
    button.type = "button";
    button.addEventListener("click", () => {
      state.zoom = Math.max(0.6, Math.min(4, state.zoom * factor));
      remember("map.zoom", state.zoom);
      draw(state.canvas, data, station);
    });
    zoomBox.append(button);
  }
  if (station.located) {
    const home = el("button", "chip", "QTH");
    home.type = "button";
    home.title = "Centre on your station";
    home.addEventListener("click", () => {
      state.lat0 = station.lat;
      state.lon0 = station.lon;
      redrawNow();
    });
    zoomBox.append(home);
  }
  holder.append(zoomBox);
  parts.push(holder);

  if (state.error) parts.push(el("p", "error", `world outline: ${state.error}`));

  const locateRow = el("div", "chips");
  const blocked = unavailableReason();
  const findChip = el("button", "chip", "FIND MY GRID");
  findChip.type = "button";
  if (blocked) {
    findChip.disabled = true;
    findChip.title = blocked;
  }
  findChip.addEventListener("click", async () => {
    findChip.textContent = "LOCATING…";
    try {
      const fix = await locate();
      saveQth(fix);
      state.locateMessage = {
        text: `${fix.grid} — ±${fix.accuracy} m. Put this in config.toml [station] grid so the collector uses it too.`,
        ok: true,
      };
      state.lat0 = fix.lat;
      state.lon0 = fix.lon;
    } catch (err) {
      state.locateMessage = { text: `could not locate: ${err.message}`, ok: false };
    }
    render(root, { data, el });
  });
  locateRow.append(findChip);

  if (station.overridden) {
    const clearChip = el("button", "chip", "USE CONFIG QTH");
    clearChip.type = "button";
    clearChip.addEventListener("click", () => {
      clearQth();
      state.locateMessage = null;
      render(root, { data, el });
    });
    locateRow.append(clearChip);
  }
  parts.push(locateRow);

  if (blocked) {
    parts.push(el("p", "empty", `location unavailable: ${blocked}`));
  } else if (state.locateMessage) {
    parts.push(
      el("p", state.locateMessage.ok ? "count" : "error", state.locateMessage.text),
    );
  }

  const count = collectPoints(data).length;
  const sel = state.selected;
  parts.push(
    el(
      "p",
      "count",
      sel
        ? `${sel.call} · ${sel.entity ?? "?"} · ${sel.band ?? ""} ${sel.mode ?? ""}`.trim()
        : `${count} stations plotted · drag to rotate`,
    ),
  );

  root.replaceChildren(...parts);
  redrawNow();
}

function attachControls(canvas) {
  // Reads the latest data through state, so a redraw during a drag uses
  // whatever the last poll delivered rather than a stale closure.
  const redraw = () => draw(canvas, state.data ?? {}, state.station);

  canvas.addEventListener("pointerdown", (event) => {
    canvas.setPointerCapture(event.pointerId);
    state.dragging = { x: event.offsetX, y: event.offsetY, moved: false };
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!state.dragging) return;
    const dx = event.offsetX - state.dragging.x;
    const dy = event.offsetY - state.dragging.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) state.dragging.moved = true;

    const scale = 0.35 / state.zoom;
    state.lon0 = (((state.lon0 ?? 0) - dx * scale + 540) % 360) - 180;
    state.lat0 = Math.max(-89, Math.min(89, (state.lat0 ?? 0) + dy * scale));
    state.dragging.x = event.offsetX;
    state.dragging.y = event.offsetY;
    redraw();
  });

  const release = (event) => {
    if (state.dragging && !state.dragging.moved) {
      // A click, not a drag: select the nearest plotted station.
      const hit = nearest(event.offsetX, event.offsetY);
      state.selected = hit && hit !== state.selected ? hit : null;
      redraw();
    }
    state.dragging = null;
    if (canvas.hasPointerCapture?.(event.pointerId)) {
      canvas.releasePointerCapture(event.pointerId);
    }
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", () => { state.dragging = null; });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    state.zoom = Math.max(0.6, Math.min(4, state.zoom * (event.deltaY < 0 ? 1.1 : 0.9)));
    remember("map.zoom", state.zoom);
    redraw();
  }, { passive: false });
}

function nearest(x, y) {
  let best = null;
  let bestDistance = 14;
  for (const { spot, at } of state.drawn ?? []) {
    const distance = Math.hypot(at.x - x, at.y - y);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = spot;
    }
  }
  return best;
}

export { project, unproject };

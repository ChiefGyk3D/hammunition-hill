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
import { gridToLatLon, latLonToGrid, pathTo } from "../../lib/callsign.js";
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
import { bandColor } from "../../lib/bandcolors.js";

const state = {
  lat0: null,
  lon0: null,
  zoom: recall("map.zoom", 1),
  // "globe" or "flat". The globe stays the default -- great circles are the
  // point of this panel -- but a flat map answers "what is everywhere at
  // once" without rotating, which is what a wall display wants.
  mode: recall("map.mode", "globe"),
  layers: recall("map.layers", {
    greyline: true, aurora: true, spots: true, arcs: true,
    parks: true, graticule: true, labels: true,
  }),
  // The plotted path's far end, a Maidenhead grid. Persisted: an operator
  // planning a sked wants the same target tomorrow.
  target: recall("map.target", ""),
  plotting: false,
  world: null,
  loading: false,
  selected: null,
  canvas: null,
  dragging: null,
  station: {},
  data: null,
  view: null,
  rerender: null,
};

function css(name, fallback) {
  const value = getComputedStyle(document.body).getPropertyValue(name).trim();
  return value || fallback;
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

  // Flat keeps the 2:1 equirectangular aspect, fitted to whichever canvas
  // edge binds. halfW doubles as strokePath's wrap-jump threshold.
  const flatHalfH = Math.min((width / 2 - 8) / 2, height / 2 - 8) * state.zoom;
  const view =
    state.mode === "flat"
      ? {
          flat: true,
          lat0: Math.max(-60, Math.min(60, state.lat0 ?? 0)),
          lon0: state.lon0 ?? 0,
          halfW: flatHalfH * 2,
          halfH: flatHalfH,
          radius: flatHalfH * 2,
          cx: width / 2,
          cy: height / 2,
        }
      : {
          lat0: state.lat0 ?? 20,
          lon0: state.lon0 ?? 0,
          radius: (Math.min(width, height) / 2 - 8) * state.zoom,
          cx: width / 2,
          cy: height / 2,
        };
  state.view = view;

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

  // Aurora sits under the spots: it is context, not the subject. Drawn as a
  // sequential ramp in one hue -- probability is a magnitude, not a status, so
  // it must not borrow the reserved good/warn/critical colours.
  if (state.layers.aurora) {
    const aurora = data.aurora?.data;
    if (aurora) {
      for (const [lon, lat, probability] of aurora.cells ?? []) {
        const p = project(lat, lon, view);
        if (!p.visible) continue;
        ctx.globalAlpha = Math.min(0.55, 0.06 + (probability / 100) * 0.6);
        ctx.fillStyle = accent;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.2, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // The equatorward edge is the line that matters: HF paths crossing it
      // degrade, and VHF sometimes opens along it.
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1.2;
      ctx.globalAlpha = 0.85;
      for (const oval of [aurora.north_oval, aurora.south_oval]) {
        if (oval?.length) {
          strokePath(ctx, oval.map(([lon, lat]) => ({ lat, lon })), view);
        }
      }
      ctx.globalAlpha = 1;
    }
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

  // The plotted path: brighter and dashed, so it reads as the operator's own
  // line of inquiry rather than one more spot arc.
  const target = state.target ? gridToLatLon(state.target) : null;
  if (home && target) {
    const far = { lat: target[0], lon: target[1] };
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.setLineDash([7, 5]);
    strokePath(ctx, greatCircle(home, far, 128), view);
    ctx.setLineDash([]);
    drawMarker(ctx, far.lat, far.lon, view, { color: accent, radius: 4, ring: ink });
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
    greyline: "GREYLINE", aurora: "AURORA", spots: "SPOTS", arcs: "ARCS",
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
  state.rerender = () => render(root, { data, el });

  // One row of view controls, one row of layer toggles, all the same chip the
  // rest of the dashboard uses. The first version scattered three styles of
  // control around the panel and the operator noticed.
  const viewRow = el("div", "chips");
  for (const [label, mode] of [["3D", "globe"], ["2D", "flat"]]) {
    const chip = el("button", "chip" + (state.mode === mode ? " on" : ""), label);
    chip.type = "button";
    chip.setAttribute("aria-pressed", String(state.mode === mode));
    chip.addEventListener("click", () => {
      if (state.mode === mode) return;
      state.mode = mode;
      // The globe's rotation latitude means nothing to a flat map -- carrying
      // it over shoved the whole world down the canvas and left a blank band
      // where the Arctic should be. Centre the equator; panning still works.
      if (mode === "flat") state.lat0 = 0;
      remember("map.mode", mode);
      state.rerender();
    });
    viewRow.append(chip);
  }
  const plotChip = el("button", "chip" + (state.plotting ? " on" : ""), "PLOT PATH");
  plotChip.type = "button";
  plotChip.title = "Draw a great circle from your station to a grid square";
  plotChip.setAttribute("aria-pressed", String(state.plotting));
  plotChip.addEventListener("click", () => {
    state.plotting = !state.plotting;
    state.rerender();
  });
  viewRow.append(plotChip);

  const parts = [viewRow, layerRow(el, redrawNow)];

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
      // Flat centres your longitude only: latitude-centring a world map on a
      // mid-latitude QTH just pushes a pole off the canvas.
      state.lat0 = state.mode === "flat" ? 0 : station.lat;
      state.lon0 = station.lon;
      redrawNow();
    });
    zoomBox.append(home);
  }
  holder.append(zoomBox);
  parts.push(holder);

  if (state.error) parts.push(el("p", "error", `world outline: ${state.error}`));

  // The path plotter's input, shown while the tool is armed. Typing a grid
  // and clicking the map are the same action spelled two ways.
  if (state.plotting) {
    const plotRow = el("div", "chips");
    const input = el("input", "pmf-input");
    input.value = state.target;
    input.maxLength = 6;
    input.placeholder = "grid (PM95)";
    input.addEventListener("change", () => {
      const typed = input.value.trim().toUpperCase();
      if (typed && !gridToLatLon(typed)) {
        state.locateMessage = { text: `${typed} is not a grid square`, ok: false };
      } else {
        state.target = typed;
        remember("map.target", typed);
        state.locateMessage = null;
      }
      state.rerender();
    });
    plotRow.append(input);
    if (state.target) {
      const clear = el("button", "chip", "CLEAR");
      clear.type = "button";
      clear.addEventListener("click", () => {
        state.target = "";
        remember("map.target", "");
        state.rerender();
      });
      plotRow.append(clear);
    }
    plotRow.append(el("span", "count", "…or click the map to drop the far end"));
    parts.push(plotRow);
  }

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
  viewRow.append(findChip);

  if (station.overridden) {
    const clearChip = el("button", "chip", "USE CONFIG QTH");
    clearChip.type = "button";
    clearChip.addEventListener("click", () => {
      clearQth();
      state.locateMessage = null;
      render(root, { data, el });
    });
    viewRow.append(clearChip);
  }

  if (blocked) {
    parts.push(el("p", "empty", `location unavailable: ${blocked}`));
  } else if (state.locateMessage) {
    parts.push(
      el("p", state.locateMessage.ok ? "count" : "error", state.locateMessage.text),
    );
  }

  const home = station.located ? { lat: station.lat, lon: station.lon } : null;

  // The plotted path's numbers: both units (miles because US-first, km because
  // every distance record and contest exchange uses them), both bearings
  // (long path is a real choice on HF, not trivia).
  const targetAt = state.target ? gridToLatLon(state.target) : null;
  if (targetAt && home) {
    const p = pathTo(home, targetAt[0], targetAt[1]);
    parts.push(
      el(
        "p",
        "count",
        `${station.grid ? String(station.grid).toUpperCase() : "QTH"} → ${state.target} · ` +
          `${Math.round(p.km)} km / ${Math.round(p.miles)} mi · ` +
          `short ${Math.round(p.bearing)}° ${p.compass} · long ${Math.round(p.bearing_long)}°`,
      ),
    );
  } else if (targetAt && !home) {
    parts.push(
      el("p", "empty", "path plotted once your station has a grid — set [station] grid or FIND MY GRID"),
    );
  }

  const count = collectPoints(data).length;
  const aurora = data.aurora?.data;
  const sel = state.selected;
  // A selected spot answers "how far was that" right where the question is
  // asked, from wherever the station actually is -- a GPS fix included.
  const selPath = sel && home ? pathTo(home, sel.at.lat, sel.at.lon) : null;
  parts.push(
    el(
      "p",
      "count",
      sel
        ? [
            `${sel.call} · ${sel.entity ?? "?"} · ${sel.band ?? ""} ${sel.mode ?? ""}`.trim(),
            selPath
              ? `${Math.round(selPath.km)} km / ${Math.round(selPath.miles)} mi · ` +
                `${Math.round(selPath.bearing)}° ${selPath.compass}`
              : "",
          ]
            .filter(Boolean)
            .join(" · ")
        : `${count} stations plotted${
            aurora?.peak_probability ? ` · aurora peak ${aurora.peak_probability}%` : ""
          } · ${state.mode === "flat" ? "drag to pan" : "drag to rotate"}`,
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

    // Flat pans at the map's own scale (degrees per pixel comes from the
    // view), so the world moves with the pointer instead of at globe speed.
    const view = state.view;
    const scaleX = view?.flat ? 180 / view.halfW : 0.35 / state.zoom;
    const scaleY = view?.flat ? 90 / view.halfH : 0.35 / state.zoom;
    const latCap = view?.flat ? 60 : 89;
    state.lon0 = (((state.lon0 ?? 0) - dx * scaleX + 540) % 360) - 180;
    state.lat0 = Math.max(-latCap, Math.min(latCap, (state.lat0 ?? 0) + dy * scaleY));
    state.dragging.x = event.offsetX;
    state.dragging.y = event.offsetY;
    redraw();
  });

  const release = (event) => {
    if (state.dragging && !state.dragging.moved) {
      if (state.plotting && state.view) {
        // The plot tool is armed: a click drops the path's far end, at
        // 4-character precision -- a click is not a 6-character gesture.
        const at = unproject(event.offsetX, event.offsetY, state.view);
        if (at) {
          state.target = latLonToGrid(at.lat, at.lon, 4);
          remember("map.target", state.target);
          state.dragging = null;
          state.rerender?.();
          return;
        }
      }
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

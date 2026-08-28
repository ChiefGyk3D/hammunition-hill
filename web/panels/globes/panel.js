// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can see one at https://mozilla.org/MPL/2.0/.

// One globe per band.
//
// The big map answers "where is this station"; this panel answers "which bands
// are open, and to where" -- the question an operator actually starts with.
// All the spots on one sphere blend into confetti; the same spots split one
// band per sphere read as propagation. This is the display hamdash built its
// front page around, drawn here from your own data: cluster spots, WSJT-X
// decodes, and -- with the pskreporter/wspr sources configured -- the
// stations reporting that they heard you.
//
// "However many make sense": a globe appears when its band has activity in the
// spot window and disappears when the band goes quiet, in wavelength order.
// A fixed six would show dead spheres at 3 AM and hide a 6 m opening at noon.
//
// Every sphere carries the greyline, because HF openings follow the dark --
// a cluster of dots hugging the terminator on 40 m IS the story.

import { gridToLatLon } from "../../lib/callsign.js";
import { subsolarPoint, terminatorRing } from "../../lib/solar.js";
import {
  drawMarker,
  drawSphere,
  drawTerminator,
  drawWorld,
  project,
} from "../../lib/globe.js";

import { BAND_COLORS, BAND_ORDER } from "../../lib/bandcolors.js";

const state = { world: null, loading: false, canvases: new Map() };

function spotLocation(spot) {
  if (spot.lat != null && spot.lon != null) return { lat: spot.lat, lon: spot.lon };
  if (spot.grid) {
    const fromGrid = gridToLatLon(spot.grid);
    if (fromGrid) return { lat: fromGrid[0], lon: fromGrid[1] };
  }
  if (spot.entity_lat != null && spot.entity_lon != null) {
    return { lat: spot.entity_lat, lon: spot.entity_lon };
  }
  return null;
}

/** Spots with a location, grouped by band, wavelength order. */
function byBand(data) {
  const bands = new Map();
  const add = (spot) => {
    if (!spot.band || !BAND_COLORS[spot.band]) return;
    const at = spotLocation(spot);
    if (!at) return;
    if (!bands.has(spot.band)) bands.set(spot.band, []);
    bands.get(spot.band).push({ ...spot, at });
  };
  for (const spot of data.cluster?.data?.spots ?? []) add(spot);
  for (const decode of data.wsjtx?.data?.spots ?? []) add(decode);
  // Reception reports point the other way -- stations that heard YOU -- and
  // that is exactly what belongs on a propagation sphere: a dot for every
  // place your signal actually reached.
  for (const report of data.pskreporter?.data?.spots ?? []) add(report);
  for (const report of data.wspr?.data?.spots ?? []) add(report);
  return [...bands.entries()].sort(
    (a, b) => BAND_ORDER.indexOf(a[0]) - BAND_ORDER.indexOf(b[0]),
  );
}

function css(name, fallback) {
  const value = getComputedStyle(document.body).getPropertyValue(name).trim();
  return value || fallback;
}

function drawBandGlobe(canvas, spots, color, home, sun, terminator) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  // Centred on home: these spheres answer "open FROM HERE", and a globe
  // centred anywhere else answers a question nobody at this station asked.
  // The library's field is `radius`, and nothing warns when it is absent: an
  // arc with an undefined radius is an empty path, so a view built with `r`
  // renders seven perfectly blank spheres and no error anywhere.
  const view = {
    lat0: home?.lat ?? 30,
    lon0: home?.lon ?? -40,
    cx: width / 2,
    cy: height / 2,
    radius: Math.min(width, height) / 2 - 2,
  };

  drawSphere(ctx, view, { fill: "#1b2530", stroke: css("--rule", "#28313c") });
  if (state.world) {
    drawWorld(ctx, state.world.rings, view, { stroke: "#4a5866", fill: "#243141" });
  }
  drawTerminator(ctx, terminator, sun, view, {
    shade: "rgba(0, 0, 0, 0.62)",
    line: "rgba(232, 176, 74, 0.55)",
  });

  for (const spot of spots) {
    const p = project(spot.at.lat, spot.at.lon, view);
    // project always answers; the far side of the sphere answers with
    // visible: false, and drawing those paints the night side's spots onto
    // the rim of the disc.
    if (!p.visible) continue;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2.4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }

  if (home) drawMarker(ctx, home.lat, home.lon, view, { color: "#e3e7ed", radius: 2.5 });
}

export function render(root, { data, station, el }) {
  if (!state.world && !state.loading) {
    state.loading = true;
    fetch("./world.json")
      .then((response) => (response.ok ? response.json() : null))
      .then((world) => {
        state.world = world;
        render(root, { data, station, el });
      })
      .catch(() => {});
  }

  const bands = byBand(data);
  if (bands.length === 0) {
    root.replaceChildren(
      el(
        "p",
        "empty",
        "no band activity yet — globes appear as spots arrive from the cluster, " +
          "WSJT-X, PSK Reporter, or WSPR",
      ),
    );
    return;
  }

  const home = station?.located ? { lat: station.lat, lon: station.lon } : null;
  const sun = subsolarPoint(new Date());
  const terminator = terminatorRing(sun);

  const grid = el("div", "globes-grid");
  for (const [band, spots] of bands) {
    const cell = el("figure", "globe-cell");
    const canvas = state.canvases.get(band) ?? document.createElement("canvas");
    canvas.className = "globe-canvas";
    state.canvases.set(band, canvas);
    cell.append(canvas);

    const cap = el("figcaption", "globe-cap");
    const name = el("span", "globe-band", band);
    name.style.color = BAND_COLORS[band];
    cap.append(name, el("span", "globe-count", `${spots.length}`));
    cell.append(cap);
    grid.append(cell);
  }
  root.replaceChildren(grid);

  // Draw after the canvases have layout: clientWidth is 0 until they are in
  // the document, and a sphere drawn into a 0x0 canvas is a very small globe.
  for (const [band, spots] of bands) {
    drawBandGlobe(state.canvases.get(band), spots, BAND_COLORS[band], home, sun, terminator);
  }
}

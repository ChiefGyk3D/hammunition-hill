// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Sunrise, sunset, moonrise, moonset -- and the two windows they define.
//
// Tier 0, and not incidentally: every number here comes out of the clock and
// the grid square. There is no source, no snapshot, and nothing to go stale,
// which is exactly the behaviour you want from the panel that tells a portable
// operator how much daylight is left to take the antenna down in.
//
// Two windows, because they are the two an operator plans around:
//
//   * The **greyline**, the band either side of sunrise and sunset where 160
//     and 80 do things they do at no other hour. The useful edges are civil
//     twilight -- six degrees down -- rather than the instant the disc touches
//     the horizon, so both are shown.
//   * The **moon window**, from moonrise to moonset, which is the entire
//     opportunity for an EME contact and the reason anyone points a big yagi
//     at the sky at four in the morning.
//
// The maths lives in ../../lib/ephemeris.js and is mirrored by
// src/hammunition_hill/ephemeris.py, with a drift test pinning the two
// together. What that maths is *not* good for is stated on the panel: the
// low-precision lunar series is half a moon-width out, which is fine for
// planning a window and not fine for pointing a dish open-loop.

import { effectiveStation } from "../../lib/geolocate.js";
import { compassPoint } from "../../lib/callsign.js";
import {
  greylineWindow,
  moonEvents,
  moonLookAngles,
  moonPosition,
  sunElevationAt,
  sunEvents,
} from "../../lib/ephemeris.js";

const two = (n) => String(n).padStart(2, "0");

// The crossing times are recomputed only when the day or the station changes.
//
// Each of the three event searches walks 36 hours in ten-minute steps with a
// bisection at every crossing -- for the moon that is several hundred full
// lunar position evaluations. Redoing all three on every tick buys nothing,
// because sunrise does not move between ticks.
//
// The panel's own cadence is "minute" for the same reason, and the render
// check measured the difference: at "second" it put an idle Operating tab at
// 540 DOM nodes per five seconds against a bound of 900, where the rest of the
// dashboard sits at 310. Nothing on this panel shows seconds, so the extra 59
// rebuilds a minute were pure churn. The look angles are *not* cached, because
// those genuinely do change.
const cache = { key: null, events: null };

function crossings(lat, lon, dayStart) {
  const key = `${lat},${lon},${dayStart.getTime()}`;
  if (cache.key !== key) {
    // A 36-hour span, not 24: started at local midnight it still contains the
    // *next* crossing of each kind when the panel is read late in the evening,
    // which a 24-hour window does not.
    const options = { hours: 36 };
    cache.key = key;
    cache.events = {
      sun: sunEvents(lat, lon, dayStart, options),
      twilight: greylineWindow(lat, lon, dayStart, options),
      moon: moonEvents(lat, lon, dayStart, options),
    };
  }
  return cache.events;
}

/** A crossing time, or the honest reason there is not one. */
function stamp(moment) {
  if (!moment) return "—";
  return `${two(moment.getUTCHours())}:${two(moment.getUTCMinutes())}Z`;
}

/**
 * The same crossing in local time, or nothing when that is the same clock.
 *
 * Plenty of shack machines run on UTC. Printing "13:03Z 13:03 local" on one of
 * them is not extra information, it is the same number twice, and a panel that
 * says everything twice teaches people to stop reading it.
 */
function localStamp(moment) {
  if (!moment || moment.getTimezoneOffset() === 0) return "";
  return ` ${two(moment.getHours())}:${two(moment.getMinutes())} local`;
}

/** "3h 12m" for a duration in milliseconds. Negative reads as elapsed. */
function span(ms) {
  const minutes = Math.round(Math.abs(ms) / 60000);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours}h ${two(minutes % 60)}m` : `${minutes}m`;
}

function row(el, label, value, className) {
  const line = el("div", "detail-row");
  line.append(el("span", "detail-label", label), el("span", className ?? "detail-value", value));
  return line;
}

/**
 * The moon's lit limb, drawn as a disc.
 *
 * A terminator on a sphere seen from Earth is an ellipse, so the lit shape is
 * a half-disc plus a half-ellipse whose width is cos(phase angle) times the
 * radius. Waxing lights the right limb in the northern hemisphere; below the
 * equator the whole thing appears turned over, which is why the panel takes
 * the observer's latitude rather than assuming Kansas.
 */
function drawMoon(canvas, moon, southern) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const size = 54;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  canvas.style.width = `${size}px`;
  canvas.style.height = `${size}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);

  const r = size / 2 - 3;
  const cx = size / 2;
  const cy = size / 2;

  const ink = getComputedStyle(document.body).getPropertyValue("--ink").trim() || "#e3e7ed";
  const rule = getComputedStyle(document.body).getPropertyValue("--rule").trim() || "#28313c";

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = rule;
  ctx.fill();

  // Fraction lit maps to the terminator ellipse's semi-minor axis, signed:
  // positive bulges away from the lit limb (gibbous), negative toward it
  // (crescent).
  const k = Math.max(0, Math.min(1, moon.illumination));
  const width = r * (2 * k - 1);
  const litOnRight = moon.waxing !== Boolean(southern);

  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.clip();

  // The lit limb is half the outer circle; the terminator closing it is half an
  // ellipse of the same height. Which way that half-ellipse bulges is the only
  // thing that distinguishes a crescent from a gibbous, and it depends on the
  // sign of `width` alone -- not on which limb is lit, because swapping the
  // limb swaps the start and end angles too and the two changes cancel. That
  // cancellation is why the first version of this line had an XOR in it and
  // drew a correct waxing moon beside a backwards waning one.
  ctx.beginPath();
  const start = litOnRight ? -Math.PI / 2 : Math.PI / 2;
  ctx.arc(cx, cy, r, start, start + Math.PI);
  ctx.ellipse(cx, cy, Math.abs(width), r, 0, start + Math.PI, start, width < 0);
  ctx.closePath();
  ctx.fillStyle = ink;
  ctx.fill();
  ctx.restore();

  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.strokeStyle = rule;
  ctx.lineWidth = 1;
  ctx.stroke();
}

export function render(root, { data, el }) {
  const station = effectiveStation(data.station?.data ?? {});
  if (!station.located) {
    root.replaceChildren(
      el("p", "empty", "set [station] grid in config.toml, or use FIND MY GRID on the map"),
    );
    return;
  }

  const now = new Date();
  const { lat, lon } = station;

  // The window starts at the previous local midnight rather than at "now", so
  // a sunrise that has already happened today still reads as today's -- which
  // is what an operator glancing at the panel in the afternoon expects.
  const dayStart = new Date(now);
  dayStart.setHours(0, 0, 0, 0);

  const { sun, twilight, moon: moonWindow } = crossings(lat, lon, dayStart);

  const moon = moonPosition(now);
  const moonNow = moonLookAngles(lat, lon, moon);
  const sunNow = sunElevationAt(lat, lon, now);

  const parts = [];

  // --- the sun -----------------------------------------------------------
  const sunBlock = el("div", "sm-block");
  sunBlock.append(el("div", "sm-heading", "SUN"));
  const sunRows = el("div", "detail");

  if (sun.alwaysUp) {
    sunRows.append(row(el, "Today", "midnight sun — never sets"));
  } else if (sun.alwaysDown) {
    sunRows.append(row(el, "Today", "polar night — never rises"));
  } else {
    sunRows.append(
      row(el, "Rise", `${stamp(sun.rise)}${localStamp(sun.rise)}`),
      row(el, "Set", `${stamp(sun.set)}${localStamp(sun.set)}`),
    );
    if (sun.rise && sun.set) {
      const daylight = sun.set > sun.rise ? sun.set - sun.rise : sun.set - sun.rise + 86400000;
      sunRows.append(row(el, "Daylight", span(daylight)));
    }
  }
  sunRows.append(
    row(el, "Transit", `${stamp(sun.transit)} at ${sun.transitElevation.toFixed(0)}°`),
    row(
      el,
      "Now",
      sunNow >= 0
        ? `up, ${sunNow.toFixed(1)}° above the horizon`
        : `down, ${Math.abs(sunNow).toFixed(1)}° below`,
      sunNow >= 0 ? "detail-value" : "detail-value muted",
    ),
  );

  // The greyline band, which is the reason this panel is on the operating
  // dashboard rather than only being a clock.
  if (twilight.rise || twilight.set) {
    sunRows.append(
      row(el, "Dawn grey", `${stamp(twilight.rise)} – ${stamp(sun.rise)}`),
      row(el, "Dusk grey", `${stamp(sun.set)} – ${stamp(twilight.set)}`),
    );
  }
  sunBlock.append(sunRows);
  parts.push(sunBlock);

  // --- the moon ----------------------------------------------------------
  const moonBlock = el("div", "sm-block");
  moonBlock.append(el("div", "sm-heading", "MOON"));

  const face = el("div", "sm-face");
  const canvas = el("canvas", "sm-moon");
  canvas.setAttribute("role", "img");
  canvas.setAttribute(
    "aria-label",
    `${moon.phaseName}, ${Math.round(moon.illumination * 100)} percent illuminated`,
  );
  drawMoon(canvas, moon, lat < 0);
  face.append(canvas);

  const phaseText = el("div", "sm-phase");
  phaseText.append(
    el("div", "sm-phase-name", moon.phaseName),
    el(
      "div",
      "sm-phase-detail",
      `${Math.round(moon.illumination * 100)}% lit · day ${moon.ageDays.toFixed(1)} of 29.5`,
    ),
    el(
      "div",
      "sm-phase-detail",
      `${Math.round(moon.distanceKm).toLocaleString()} km · ${moon.waxing ? "waxing" : "waning"}`,
    ),
  );
  face.append(phaseText);
  moonBlock.append(face);

  const moonRows = el("div", "detail");
  if (moonWindow.alwaysUp) {
    moonRows.append(row(el, "Window", "up all day at this latitude"));
  } else if (moonWindow.alwaysDown) {
    moonRows.append(row(el, "Window", "below the horizon all day"));
  } else {
    moonRows.append(
      row(el, "Rise", `${stamp(moonWindow.rise)}${localStamp(moonWindow.rise)}`),
      row(el, "Set", `${stamp(moonWindow.set)}${localStamp(moonWindow.set)}`),
    );
  }
  moonRows.append(
    row(
      el,
      "Transit",
      `${stamp(moonWindow.transit)} at ${moonWindow.transitElevation.toFixed(0)}°`,
    ),
  );

  // Where to point, right now. Azimuth first because that is the one a rotator
  // takes; elevation second because on most stations it is fixed and the
  // answer is really "wait".
  const up = moonNow.elevation > 0;
  moonRows.append(
    row(
      el,
      "Look angle",
      up
        ? `${Math.round(moonNow.azimuth)}° ${compassPoint(moonNow.azimuth)} · el ${moonNow.elevation.toFixed(1)}°`
        : `below the horizon (${moonNow.elevation.toFixed(1)}°)`,
      up ? "detail-value" : "detail-value muted",
    ),
  );

  // How long is left, or how long until it starts. The single most useful line
  // on the panel for anyone actually working EME.
  const next = up ? moonWindow.set : moonWindow.rise;
  if (next && !moonWindow.alwaysUp && !moonWindow.alwaysDown) {
    const delta = next - now;
    if (delta > 0) {
      moonRows.append(
        row(el, "EME window", up ? `${span(delta)} left` : `opens in ${span(delta)}`),
      );
    }
  }
  moonBlock.append(moonRows);
  parts.push(moonBlock);

  parts.push(
    el(
      "p",
      "count",
      "computed here from the clock and your grid — no network. Lunar positions " +
        "are the low-precision series, good to about half a moon-width: fine for " +
        "planning a window, not for pointing a dish open-loop.",
    ),
  );

  root.replaceChildren(...parts);
}

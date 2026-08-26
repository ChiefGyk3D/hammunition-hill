// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// An orthographic globe on a 2D canvas.
//
// No WebGL, no library, no texture assets. The whole thing is a projection
// function and some paths, which keeps the "read the source your machine is
// serving" promise intact and keeps the bundle at one 60 KB coastline file.
//
// A vector globe also suits this dashboard better than satellite imagery would:
// it is an instrument, not a photograph, and thin coastlines read at a glance
// against a dark panel where a textured earth does not.
//
// Great-circle paths are the reason this is a globe rather than a flat map. On
// a Mercator projection the short path from Connecticut to Japan looks like it
// goes the wrong way; on a sphere it is obviously over the pole.

const DEG = Math.PI / 180;

/**
 * Orthographic projection.
 * @returns {{x: number, y: number, visible: boolean, cosc: number}}
 */
export function project(lat, lon, view) {
  const { lat0, lon0, radius, cx, cy } = view;
  const p = lat * DEG;
  const l = (lon - lon0) * DEG;
  const p0 = lat0 * DEG;

  const sinP = Math.sin(p);
  const cosP = Math.cos(p);
  const sinP0 = Math.sin(p0);
  const cosP0 = Math.cos(p0);
  const cosL = Math.cos(l);

  // cos of the angular distance from the view centre. Negative is the far side.
  const cosc = sinP0 * sinP + cosP0 * cosP * cosL;

  return {
    x: cx + radius * cosP * Math.sin(l),
    y: cy - radius * (cosP0 * sinP - sinP0 * cosP * cosL),
    visible: cosc >= 0,
    cosc,
  };
}

/** Screen point back to lat/lon, or null if the click missed the globe. */
export function unproject(x, y, view) {
  const { lat0, lon0, radius, cx, cy } = view;
  const dx = x - cx;
  const dy = cy - y;
  const rho = Math.hypot(dx, dy);
  if (rho > radius) return null;

  const c = Math.asin(Math.min(1, rho / radius));
  const sinC = Math.sin(c);
  const cosC = Math.cos(c);
  const p0 = lat0 * DEG;

  const lat = rho === 0
    ? lat0
    : Math.asin(cosC * Math.sin(p0) + (dy * sinC * Math.cos(p0)) / rho) / DEG;
  const lon =
    lon0 +
    Math.atan2(dx * sinC, rho * Math.cos(p0) * cosC - dy * Math.sin(p0) * sinC) / DEG;

  return { lat, lon: (((lon + 540) % 360) - 180) };
}

/** Points along the great circle between two coordinates. */
export function greatCircle(from, to, steps = 64) {
  const p1 = from.lat * DEG;
  const l1 = from.lon * DEG;
  const p2 = to.lat * DEG;
  const l2 = to.lon * DEG;

  const d =
    2 *
    Math.asin(
      Math.sqrt(
        Math.sin((p2 - p1) / 2) ** 2 +
          Math.cos(p1) * Math.cos(p2) * Math.sin((l2 - l1) / 2) ** 2,
      ),
    );
  if (d === 0) return [from, to];

  const points = [];
  for (let i = 0; i <= steps; i += 1) {
    const f = i / steps;
    const a = Math.sin((1 - f) * d) / Math.sin(d);
    const b = Math.sin(f * d) / Math.sin(d);
    const x = a * Math.cos(p1) * Math.cos(l1) + b * Math.cos(p2) * Math.cos(l2);
    const y = a * Math.cos(p1) * Math.sin(l1) + b * Math.cos(p2) * Math.sin(l2);
    const z = a * Math.sin(p1) + b * Math.sin(p2);
    points.push({
      lat: Math.atan2(z, Math.hypot(x, y)) / DEG,
      lon: Math.atan2(y, x) / DEG,
    });
  }
  return points;
}

/**
 * Stroke a lat/lon path, breaking it wherever it goes around the limb.
 *
 * Without the break, a path disappearing over the horizon draws a straight line
 * across the face of the globe, which looks like a bug because it is one.
 */
export function strokePath(ctx, points, view, { close = false } = {}) {
  let drawing = false;
  ctx.beginPath();
  for (const point of points) {
    const p = project(point.lat, point.lon, view);
    if (!p.visible) {
      drawing = false;
      continue;
    }
    if (drawing) {
      ctx.lineTo(p.x, p.y);
    } else {
      ctx.moveTo(p.x, p.y);
      drawing = true;
    }
  }
  if (close && drawing) ctx.closePath();
  ctx.stroke();
}

/** The globe disc. */
export function drawSphere(ctx, view, { fill, stroke }) {
  ctx.beginPath();
  ctx.arc(view.cx, view.cy, view.radius, 0, Math.PI * 2);
  if (fill) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

/** Parallels and meridians every 30 degrees. */
export function drawGraticule(ctx, view, color, step = 30) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 0.5;

  for (let lat = -60; lat <= 60; lat += step) {
    const ring = [];
    for (let lon = -180; lon <= 180; lon += 3) ring.push({ lat, lon });
    strokePath(ctx, ring, view);
  }
  for (let lon = -180; lon < 180; lon += step) {
    const ring = [];
    for (let lat = -90; lat <= 90; lat += 3) ring.push({ lat, lon });
    strokePath(ctx, ring, view);
  }
}

/** Coastlines, from the bundled Natural Earth outline. */
export function drawWorld(ctx, rings, view, { stroke, fill }) {
  for (const ring of rings) {
    const points = ring.map(([lon, lat]) => ({ lat, lon }));
    if (fill) {
      // Only fill rings entirely on the near side; a clipped ring would fill
      // the wrong shape, and at globe scale the difference is not worth the
      // machinery to do it properly.
      if (points.every((p) => project(p.lat, p.lon, view).visible)) {
        ctx.beginPath();
        points.forEach((p, i) => {
          const s = project(p.lat, p.lon, view);
          if (i === 0) ctx.moveTo(s.x, s.y);
          else ctx.lineTo(s.x, s.y);
        });
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.fill();
      }
    }
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 0.7;
    strokePath(ctx, points, view);
  }
}

/**
 * Shade the night side and draw the greyline.
 *
 * The terminator is a great circle, so in orthographic projection it crosses
 * the disc as an arc entering and leaving the limb. We stroke that arc as the
 * greyline itself, then fill the night side by closing the arc along the rim --
 * choosing the rim direction that contains the antisolar point.
 */
export function drawTerminator(ctx, ring, subsolar, view, { shade, line }) {
  const projected = ring.map((p) => ({ ...p, s: project(p.lat, p.lon, view) }));
  const visible = projected.filter((p) => p.s.visible);

  // Whole disc is one or the other when the terminator is entirely behind.
  if (visible.length === 0) {
    const centre = project(view.lat0, view.lon0, view);
    const centreIsNight =
      Math.sin(view.lat0 * DEG) * Math.sin(subsolar.lat * DEG) +
        Math.cos(view.lat0 * DEG) *
          Math.cos(subsolar.lat * DEG) *
          Math.cos((view.lon0 - subsolar.lon) * DEG) <
      0;
    if (centreIsNight && shade) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(centre.x, centre.y, view.radius, 0, Math.PI * 2);
      ctx.fillStyle = shade;
      ctx.fill();
      ctx.restore();
    }
    return;
  }

  // Fill: clip to the disc, then close the terminator arc through the
  // antisolar side. Closing through a point far outside the disc is enough,
  // because the clip discards everything beyond the rim anyway.
  if (shade) {
    const anti = project(-subsolar.lat, subsolar.lon + 180, view);
    ctx.save();
    ctx.beginPath();
    ctx.arc(view.cx, view.cy, view.radius, 0, Math.PI * 2);
    ctx.clip();

    ctx.beginPath();
    let started = false;
    for (const p of projected) {
      if (!p.s.visible) continue;
      if (started) ctx.lineTo(p.s.x, p.s.y);
      else {
        ctx.moveTo(p.s.x, p.s.y);
        started = true;
      }
    }
    // Push the closing vertex well past the rim, on the night side.
    const dx = anti.x - view.cx;
    const dy = anti.y - view.cy;
    const norm = Math.hypot(dx, dy) || 1;
    const far = 3 * view.radius;
    ctx.lineTo(view.cx + (dx / norm) * far, view.cy + (dy / norm) * far);
    ctx.closePath();
    ctx.fillStyle = shade;
    ctx.fill();
    ctx.restore();
  }

  if (line) {
    ctx.strokeStyle = line;
    ctx.lineWidth = 1.6;
    strokePath(ctx, ring, view);
  }
}

/** A dot at a coordinate, if it is on the near side. */
export function drawMarker(ctx, lat, lon, view, { color, radius = 3, ring = null }) {
  const p = project(lat, lon, view);
  if (!p.visible) return null;

  if (ring) {
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius + 2.5, 0, Math.PI * 2);
    ctx.strokeStyle = ring;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  return p;
}

/** A label with a readable backing, positioned clear of its marker. */
export function drawLabel(ctx, text, at, { color, background, font }) {
  ctx.font = font;
  const width = ctx.measureText(text).width;
  const padX = 4;
  const height = 13;
  const x = at.x + 7;
  const y = at.y - height / 2;

  ctx.fillStyle = background;
  ctx.fillRect(x, y, width + padX * 2, height);
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + padX, y + height / 2 + 0.5);
}

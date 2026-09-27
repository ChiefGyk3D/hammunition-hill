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

const wrapLon = (lon) => (((lon + 540) % 360) - 180);

/**
 * How far two consecutive screen points may jump before the path is broken.
 *
 * Only the projections that fold the world onto itself need this. On the globe
 * a path that leaves the near side simply stops being visible and the limb
 * test handles it; on the flat map and in azimuthal equidistant nothing is
 * ever hidden, so a segment crossing the seam has to be cut by distance
 * instead. Returns null where no cut is wanted.
 */
function wrapThreshold(view) {
  if (view.flat) return view.halfW;
  // Azimuthal equidistant's seam is the antipode, which projects onto the
  // whole rim at once: a path crossing it leaves one edge and reappears
  // opposite. A jump of more than the disc's radius cannot be a real step --
  // the coarsest path drawn here steps three degrees, which is under two per
  // cent of it.
  if (view.azimuthal) return view.radius;
  return null;
}

/**
 * How far a step moved, in whichever direction the projection's seam lies.
 *
 * The flat map's seam is vertical, so only horizontal movement can cross it --
 * measuring the diagonal there would break a path that merely climbed steeply.
 * The azimuthal seam is the rim, which a crossing leaves and re-enters at any
 * angle, so there it is the straight-line distance that matters.
 */
function jump(from, to, view) {
  return view.flat ? Math.abs(to.x - from.x) : Math.hypot(to.x - from.x, to.y - from.y);
}

/**
 * Orthographic projection -- equirectangular when the view says `flat`,
 * azimuthal equidistant when it says `azimuthal`.
 *
 * One dispatch point, so every draw function below works on all three without
 * knowing which it is drawing. A flat view carries `halfW`/`halfH` (half the
 * map's world width and height in pixels, 2:1) alongside the same lat0/lon0
 * centre; the two disc projections carry `radius`.
 *
 * Azimuthal equidistant is the projection HamClock made the default and the
 * one most worth having on a ham radio map: every bearing from the centre is a
 * straight line out of it, and distance along that line is linear all the way
 * to the antipode on the rim. Point the beam at the screen angle and you are
 * pointing it right. The cost is that everything except direction and distance
 * *from your own station* is distorted, which is why it is a mode rather than
 * the default here.
 * @returns {{x: number, y: number, visible: boolean, cosc: number}}
 */
export function project(lat, lon, view) {
  if (view.flat) {
    return {
      x: view.cx + (wrapLon(lon - view.lon0) / 180) * view.halfW,
      y: view.cy - ((lat - view.lat0) / 90) * view.halfH,
      visible: true,
      cosc: 1,
    };
  }
  if (view.azimuthal) {
    const p = lat * DEG;
    const l = (lon - view.lon0) * DEG;
    const p0 = view.lat0 * DEG;

    const cosc = Math.sin(p0) * Math.sin(p) + Math.cos(p0) * Math.cos(p) * Math.cos(l);
    const c = Math.acos(Math.max(-1, Math.min(1, cosc)));

    // Bearing from the centre, then step out along it. Doing it this way
    // rather than through the textbook c/sin(c) scale factor keeps the
    // antipode finite: there sin(c) is zero and the closed form divides by it.
    const theta = Math.atan2(
      Math.cos(p) * Math.sin(l),
      Math.cos(p0) * Math.sin(p) - Math.sin(p0) * Math.cos(p) * Math.cos(l),
    );
    const r = (view.radius * c) / Math.PI;
    return {
      x: view.cx + r * Math.sin(theta),
      y: view.cy - r * Math.cos(theta),
      visible: true,
      cosc,
    };
  }
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

/** Screen point back to lat/lon, or null if the click missed the map. */
export function unproject(x, y, view) {
  if (view.flat) {
    const lat = view.lat0 + ((view.cy - y) / view.halfH) * 90;
    const lon = wrapLon(view.lon0 + ((x - view.cx) / view.halfW) * 180);
    if (Math.abs(lat) > 90 || Math.abs(x - view.cx) > view.halfW) return null;
    return { lat, lon };
  }
  if (view.azimuthal) {
    const dx = x - view.cx;
    const dy = view.cy - y;
    const rho = Math.hypot(dx, dy);
    if (rho > view.radius) return null;

    // Straight back out: screen radius is angular distance, screen angle is
    // bearing. Then it is the standard destination-point formula.
    const c = (rho / view.radius) * Math.PI;
    const theta = Math.atan2(dx, dy);
    const p0 = view.lat0 * DEG;

    const lat = Math.asin(
      Math.sin(p0) * Math.cos(c) + Math.cos(p0) * Math.sin(c) * Math.cos(theta),
    );
    const lon =
      view.lon0 * DEG +
      Math.atan2(
        Math.sin(theta) * Math.sin(c) * Math.cos(p0),
        Math.cos(c) - Math.sin(p0) * Math.sin(lat),
      );
    return { lat: lat / DEG, lon: (((lon / DEG + 540) % 360) - 180) };
  }
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
  let previous = null;
  const threshold = wrapThreshold(view);
  ctx.beginPath();
  for (const point of points) {
    const p = project(point.lat, point.lon, view);
    if (!p.visible) {
      drawing = false;
      continue;
    }
    // On the flat map and in azimuthal equidistant nothing is ever behind the
    // sphere, so the seam is where paths break instead: a segment that crosses
    // it jumps most of the drawing in one step, and stroking that slashes a
    // straight line across the whole map.
    if (threshold !== null && previous !== null && jump(previous, p, view) > threshold) {
      drawing = false;
    }
    previous = p;
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

/** The world's edge in flat mode: left/right at the wrap, top/bottom at the poles. */
export function mapRect(view) {
  const top = project(90, view.lon0, view);
  const bottom = project(-90, view.lon0, view);
  return {
    x: view.cx - view.halfW,
    y: top.y,
    w: view.halfW * 2,
    h: bottom.y - top.y,
  };
}

/** The globe disc -- or the map rectangle when the view is flat. */
export function drawSphere(ctx, view, { fill, stroke }) {
  ctx.beginPath();
  if (view.flat) {
    const r = mapRect(view);
    ctx.rect(r.x, r.y, r.w, r.h);
  } else {
    ctx.arc(view.cx, view.cy, view.radius, 0, Math.PI * 2);
  }
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
      // machinery to do it properly. The flat map has the same problem at the
      // wrap edge -- a landmass straddling the antimeridian projects onto both
      // sides of the map, and filling that zigzag paints a band across the
      // whole world -- so those rings are outline-only too.
      const threshold = wrapThreshold(view);
      const wraps =
        threshold !== null &&
        points.some((p, i) => {
          if (i === 0) return false;
          const a = project(points[i - 1].lat, points[i - 1].lon, view);
          const b = project(p.lat, p.lon, view);
          return jump(a, b, view) > threshold;
        });
      if (!wraps && points.every((p) => project(p.lat, p.lon, view).visible)) {
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
 * The terminator on the flat map, as one latitude per longitude.
 *
 * Solved, not traced. The terminator is the great circle a quarter turn from
 * the subsolar point, so a point is on it when
 *
 *     sin(lat) sin(dec) + cos(lat) cos(dec) cos(lon - lonSun) = 0
 *
 * which rearranges to `tan(lat) = -cos(lon - lonSun) / tan(dec)`: a latitude
 * for every longitude, single-valued by construction.
 *
 * That last part is why it is solved rather than traced. The previous version
 * projected the terminator ring and sorted the points by screen x, which
 * assumes the curve is a function of x -- and near an equinox it is not: the
 * terminator runs through both poles, so at the March 2026 equinox 361 ring
 * points land on 18 distinct columns, against 344 at the solstice.
 *
 * It is worth being exact about what that cost, because it is less than it
 * sounds: the sorted points all still lie *on* the terminator, so the polygon
 * still traced it and the shading was right. Measured against
 * `solarElevation` over a 65,000-point grid at declinations from 0.06 to 23.4
 * degrees, the old path mis-shaded 0.00% of it, and rendered side by side the
 * two differ only in sub-pixel placement of the line. This is a fragility
 * removed, not a bug fixed -- correctness rested on the accident that
 * disordering points within a column cancels out in the fill, which is not a
 * property anyone should have to re-derive to change this function.
 *
 * Longitude is walked from the left edge of the map to the right rather than
 * wrapped through `project`, because `wrapLon` sends both ends of the span to
 * the same edge and the path would double back.
 *
 * At dec exactly 0 the formula divides by zero, which is the honest answer:
 * the terminator is two vertical meridians and no longer a function of
 * longitude at all. `Math.atan(+-Infinity)` is +-90 degrees, so every column
 * lands on one pole or the other and closing to a pole draws exactly that
 * vertical band -- the only thing needing a guard is `cos = 0` at the two
 * meridians themselves, where 0/0 would be NaN.
 *
 * @returns {{points: {lon: number, lat: number, x: number, y: number}[],
 *            nightPole: number}} `nightPole` is the latitude (+-90) of the
 *   pole in darkness: the one opposite the sun.
 */
export function flatTerminator(subsolar, view, steps = 360) {
  const dec = subsolar.lat * DEG;
  const tanDec = Math.tan(dec);
  // Only a true zero is a problem, and only for the two columns where the
  // numerator vanishes too. Nudging by an amount far below a pixel keeps one
  // code path instead of a special case that would rarely run and never be
  // looked at again.
  const t = tanDec === 0 ? 1e-12 : tanDec;

  const r = mapRect(view);
  const points = [];
  for (let i = 0; i <= steps; i += 1) {
    const f = i / steps;
    const lon = view.lon0 - 180 + f * 360;
    const lat = Math.atan(-Math.cos((lon - subsolar.lon) * DEG) / t) / DEG;
    points.push({
      lon,
      lat,
      x: r.x + f * r.w,
      y: view.cy - ((lat - view.lat0) / 90) * view.halfH,
    });
  }

  return { points, nightPole: subsolar.lat > 0 ? -90 : 90 };
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
  if (view.azimuthal) {
    // Solved rather than traced. A ray out of the centre at a fixed bearing is
    // half a great circle, and two distinct great circles meet at exactly one
    // antipodal pair -- so that half contains exactly one crossing of the
    // terminator. One crossing per bearing means the terminator is a closed
    // curve in polar form around the centre, which is both cheap to compute
    // and free of the rim-following special cases the orthographic branch
    // below needs.
    //
    // Along the ray, a point is A*cos(c) + B*sin(c) away from the plane of the
    // terminator, where A is how far the centre is from it and B depends only
    // on the bearing. Setting that to zero gives the crossing directly.
    const p0 = view.lat0 * DEG;
    const ps = subsolar.lat * DEG;
    const dl = (subsolar.lon - view.lon0) * DEG;

    const towardSun = Math.sin(p0) * Math.sin(ps) + Math.cos(p0) * Math.cos(ps) * Math.cos(dl);
    const north = Math.cos(p0) * Math.sin(ps) - Math.sin(p0) * Math.cos(ps) * Math.cos(dl);
    const east = Math.cos(ps) * Math.sin(dl);

    const curve = [];
    for (let degrees = 0; degrees <= 360; degrees += 1) {
      const theta = degrees * DEG;
      const along = Math.cos(theta) * north + Math.sin(theta) * east;
      let c = Math.atan2(-towardSun, along);
      if (c < 0) c += Math.PI;
      const r = (view.radius * c) / Math.PI;
      curve.push({ x: view.cx + r * Math.sin(theta), y: view.cy - r * Math.cos(theta) });
    }

    const trace = () => {
      ctx.beginPath();
      curve.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.closePath();
    };

    if (shade) {
      ctx.save();
      ctx.beginPath();
      if (towardSun < 0) {
        // Centre is in darkness: night is the inside of the curve.
        curve.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
        ctx.closePath();
      } else {
        // Centre is in daylight: night is everything between the curve and the
        // rim, drawn as the disc with the curve punched out of it.
        ctx.arc(view.cx, view.cy, view.radius, 0, Math.PI * 2);
        ctx.moveTo(curve[0].x, curve[0].y);
        curve.forEach((p, i) => i && ctx.lineTo(p.x, p.y));
        ctx.closePath();
      }
      ctx.fillStyle = shade;
      ctx.fill("evenodd");
      ctx.restore();
    }
    if (line) {
      ctx.strokeStyle = line;
      ctx.lineWidth = 1.6;
      trace();
      ctx.stroke();
    }
    return;
  }
  if (view.flat) {
    // On the flat map the terminator is one open curve spanning every
    // longitude, solved per column by `flatTerminator` above rather than
    // traced from `ring` -- see there for why sorting the ring by x is fragile
    // near an equinox. Night closes along the edge holding the pole in
    // darkness: when the sun is north of the equator, night wraps the south.
    //
    // `ring` is still the argument the other two projections draw from, so it
    // stays in the signature; this branch simply does not need it.
    const { points, nightPole } = flatTerminator(subsolar, view);
    const r = mapRect(view);
    const poleY = nightPole < 0 ? r.y + r.h : r.y;
    if (shade) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(r.x, r.y, r.w, r.h);
      ctx.clip();
      ctx.beginPath();
      points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.lineTo(r.x + r.w, poleY);
      ctx.lineTo(r.x, poleY);
      ctx.closePath();
      ctx.fillStyle = shade;
      ctx.fill();
      ctx.restore();
    }
    if (line) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(r.x, r.y, r.w, r.h);
      ctx.clip();
      ctx.strokeStyle = line;
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.stroke();
      ctx.restore();
    }
    return;
  }
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

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// A dial: severity at a glance, with the number still there.
//
// This renderer is deliberately dumb. Every judgement -- what counts as a
// storm, where the needle sits, which band is which -- is made server-side in
// severity.py, where it can be tested. Here we only draw what we are handed.
//
// Two rules from the visualization guidance shape this:
//
//   Colour never carries the meaning alone. Every dial shows a text severity
//   label as well as a coloured band, so it works in greyscale, in print, and
//   for a colour-blind reader.
//
//   Three severity levels, not four. Four status colours cannot be told apart
//   reliably -- the amber/orange pair measures below the normal-vision
//   separation floor before you even consider colour blindness.

const SVG_NS = "http://www.w3.org/2000/svg";

// The dial sweeps 270 degrees, from lower-left round to lower-right, leaving
// the bottom open for the label. Angles are measured clockwise from 12 o'clock.
const START_ANGLE = -135;
const SWEEP = 270;

function node(name, attrs = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function polar(cx, cy, radius, degrees) {
  const rad = ((degrees - 90) * Math.PI) / 180;
  return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) };
}

/** An arc path between two fractions of the sweep. */
function arcPath(cx, cy, radius, from, to) {
  const a1 = START_ANGLE + from * SWEEP;
  const a2 = START_ANGLE + to * SWEEP;
  const p1 = polar(cx, cy, radius, a1);
  const p2 = polar(cx, cy, radius, a2);
  const large = a2 - a1 > 180 ? 1 : 0;
  return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${radius} ${radius} 0 ${large} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
}

/**
 * Build one dial.
 *
 * @param {object} gauge - a classified metric from severity.py
 * @param {object} opts  - {size}
 * @returns {SVGElement}
 */
export function gauge(gauge, { size = 116 } = {}) {
  const cx = size / 2;
  const cy = size / 2;
  const radius = size / 2 - 11;

  const svg = node("svg", {
    viewBox: `0 0 ${size} ${size + 20}`,
    class: `gauge gauge-${gauge.level}`,
    role: "img",
    "aria-label":
      `${gauge.name}: ${gauge.display}${gauge.unit ? " " + gauge.unit : ""}, ${gauge.label}`,
  });

  // Track first, so the coloured bands sit on something when a band is short.
  svg.append(
    node("path", {
      d: arcPath(cx, cy, radius, 0, 1),
      class: "gauge-track",
      fill: "none",
      "stroke-width": 7,
      "stroke-linecap": "round",
    }),
  );

  for (const band of gauge.bands ?? []) {
    svg.append(
      node("path", {
        d: arcPath(cx, cy, radius, band.from, band.to),
        class: `gauge-band level-${band.level}`,
        fill: "none",
        "stroke-width": 7,
      }),
    );
  }

  // Needle. Drawn from a little inside the centre so the hub reads as a hub.
  const angle = START_ANGLE + gauge.position * SWEEP;
  const tip = polar(cx, cy, radius - 4, angle);
  const tail = polar(cx, cy, -6, angle);
  svg.append(
    node("line", {
      x1: tail.x.toFixed(2), y1: tail.y.toFixed(2),
      x2: tip.x.toFixed(2), y2: tip.y.toFixed(2),
      class: "gauge-needle",
      "stroke-width": 1.8,
      "stroke-linecap": "round",
    }),
  );
  svg.append(node("circle", { cx, cy, r: 2.6, class: "gauge-hub" }));

  const value = node("text", {
    x: cx, y: cy + 20, class: "gauge-value", "text-anchor": "middle",
  });
  value.textContent = gauge.display ?? "—";
  svg.append(value);

  if (gauge.unit) {
    const unit = node("text", {
      x: cx, y: cy + 31, class: "gauge-unit", "text-anchor": "middle",
    });
    unit.textContent = gauge.unit;
    svg.append(unit);
  }

  const name = node("text", {
    x: cx, y: size + 4, class: "gauge-name", "text-anchor": "middle",
  });
  name.textContent = gauge.name;
  svg.append(name);

  // The label is what makes this readable without colour.
  const label = node("text", {
    x: cx, y: size + 15, class: `gauge-label level-${gauge.level}`, "text-anchor": "middle",
  });
  label.textContent = gauge.label;
  svg.append(label);

  return svg;
}

/** A row of dials. Returns a container, or null if there is nothing to draw. */
export function gaugeRow(gauges, order, opts) {
  const present = order.map((id) => gauges?.[id]).filter(Boolean);
  if (present.length === 0) return null;

  const row = document.createElement("div");
  row.className = "gauge-row";
  for (const g of present) row.append(gauge(g, opts));
  return row;
}

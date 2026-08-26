// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Tier 0: privileges by licence class.
//
// The plan is a static JSON file that ships with the dashboard, so this panel
// works with the internet unplugged -- which is exactly when you might need to
// check a band edge. Data lives in web/bandplans/ and is hand-editable;
// tests/test_bandplan.py validates the structure so an edit cannot silently
// produce a segment outside its band or a class that does not exist.
//
// It is reference material, not authority. The footer says so, because someone
// might be about to key a transmitter near an edge.

import { recall, remember } from "../../lib/format.js";

const state = {
  planId: recall("bandplan.plan", null),
  klass: recall("bandplan.class", null),
  plan: null,
  index: null,
  loading: false,
};

function mhz(khz) {
  // Band edges read as MHz on every chart an operator has ever seen.
  const value = khz / 1000;
  return Number.isInteger(value * 1000) ? value.toFixed(3) : String(value);
}

function segmentRange(segment) {
  const [low, high] = segment.khz;
  return low === high ? `${mhz(low)}` : `${mhz(low)} – ${mhz(high)}`;
}

function chipRow(el, { items, active, onPick }) {
  const row = el("div", "chips");
  for (const item of items) {
    const chip = el("button", "chip", item.label);
    chip.type = "button";
    // Novice and Advanced are closed to new issue; a dashed chip says so
    // without spending a whole line of the panel on it.
    if (item.grandfathered) {
      chip.classList.add("grandfathered");
      chip.title = "Closed to new issue — existing holders keep their privileges";
    }
    if (item.id === active) chip.classList.add("on");
    chip.setAttribute("aria-pressed", String(item.id === active));
    chip.addEventListener("click", () => onPick(item.id));
    row.append(chip);
  }
  return row;
}

function bandRow(el, band, klass) {
  const allowed = band.segments.filter((segment) => segment.classes.includes(klass));

  const row = el("div", "bp-band");
  if (allowed.length === 0) row.classList.add("bp-none");

  const head = el("div", "bp-head");
  head.append(
    el("span", "bp-name", band.band),
    el("span", "bp-range", `${mhz(band.khz[0])} – ${mhz(band.khz[1])} MHz`),
  );
  row.append(head);

  if (allowed.length === 0) {
    row.append(el("div", "bp-privilege bp-denied", "no privileges"));
    return row;
  }

  for (const segment of allowed) {
    const line = el("div", "bp-privilege");
    line.append(
      el("span", "bp-seg", segmentRange(segment)),
      el("span", "bp-modes", segment.modes.join(" · ")),
    );
    if (segment.note) line.append(el("span", "bp-note", segment.note));
    row.append(line);
  }

  if (band.note) row.append(el("div", "bp-bandnote", band.note));
  return row;
}

export function render(root, { el }) {
  // Load once, then re-render from memory -- this panel ticks every second
  // along with the other tier 0 panels and must not refetch on each tick.
  if (!state.plan && !state.loading) {
    state.loading = true;
    (async () => {
      try {
        const index = await (await fetch("./bandplans/index.json")).json();
        state.index = index;
        const wanted =
          index.available.find((entry) => entry.id === state.planId) ??
          index.available.find((entry) => entry.id === index.default) ??
          index.available[0];
        state.plan = await (await fetch(`./bandplans/${wanted.file}`)).json();
        state.planId = state.plan.id;
      } catch (err) {
        state.error = err.message;
      } finally {
        state.loading = false;
        render(root, { el });
      }
    })();
    root.replaceChildren(el("p", "empty", "loading band plan…"));
    return;
  }

  if (state.error) {
    root.replaceChildren(el("p", "error", `band plan: ${state.error}`));
    return;
  }
  if (!state.plan) return;

  const plan = state.plan;
  const classes = plan.classes;
  const active = classes.some((c) => c.id === state.klass)
    ? state.klass
    : classes[classes.length - 1].id;

  const parts = [];

  const controls = el("div", "filters");
  controls.append(
    chipRow(el, {
      items: classes.map((c) => ({
        id: c.id,
        label: c.name,
        grandfathered: c.grandfathered,
      })),
      active,
      onPick: (id) => {
        state.klass = id;
        remember("bandplan.class", id);
        render(root, { el });
      },
    }),
  );

  // Only offer a country selector once there is more than one to choose from.
  if ((state.index?.available.length ?? 0) > 1) {
    controls.append(
      chipRow(el, {
        items: state.index.available.map((entry) => ({ id: entry.id, label: entry.name })),
        active: state.planId,
        onPick: (id) => {
          remember("bandplan.plan", id);
          state.planId = id;
          state.plan = null;
          render(root, { el });
        },
      }),
    );
  }
  parts.push(controls);

  const grid = el("div", "bp-grid");
  for (const band of plan.bands) grid.append(bandRow(el, band, active));
  parts.push(grid);

  const footer = el("p", "bp-footer");
  footer.append(
    el("span", null, `${plan.name} · ${plan.authority} · revised ${plan.revised}`),
  );
  if (plan.grandfathered) footer.append(el("span", null, plan.grandfathered));
  footer.append(el("span", "bp-disclaimer", plan.note));
  parts.push(footer);

  root.replaceChildren(...parts);
}

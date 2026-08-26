// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// NOAA's own reading, alongside ours.
//
// The dials elsewhere say what the numbers mean by our interpretation. This
// panel says what the Space Weather Prediction Center is actually calling it --
// the official R, S and G scale numbers, and the alerts they have issued.
//
// Both are worth having. Our thresholds are a defensible reading; NOAA's are
// the ones every other operator is working from.

const SCALE_NAMES = {
  R: "Radio blackout",
  S: "Radiation storm",
  G: "Geomagnetic storm",
};

const MAX_ALERTS = 4;

function scaleTile(el, letter, entry) {
  const tile = el("div", `scale-tile level-${entry.level}`);
  tile.append(
    el("div", "scale-badge", entry.label),
    el("div", "scale-name", SCALE_NAMES[letter] ?? letter),
    el("div", "scale-text", entry.text),
  );
  return tile;
}

export function render(root, { data, el }) {
  const scales = data.scales?.data?.scales;
  const alerts = data.alerts?.data?.alerts ?? [];
  const aurora = data.aurora?.data;

  if (!scales && alerts.length === 0 && !aurora) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const parts = [];

  if (scales) {
    const row = el("div", "scale-row");
    for (const letter of ["R", "S", "G"]) {
      if (scales[letter]) row.append(scaleTile(el, letter, scales[letter]));
    }
    parts.push(row);
  }

  if (aurora) {
    const line = el("p", "count");
    line.textContent =
      `aurora peak ${aurora.peak_probability}%` +
      (aurora.forecast_at ? ` · forecast ${aurora.forecast_at}` : "");
    parts.push(line);
  }

  if (alerts.length) {
    const list = el("ul", "alerts");
    for (const alert of alerts.slice(0, MAX_ALERTS)) {
      const item = el("li");
      item.append(el("span", "alert-head", alert.headline));
      if (alert.issued) item.append(el("span", "alert-when", alert.issued));
      list.append(item);
    }
    parts.push(list);
    if (alerts.length > MAX_ALERTS) {
      parts.push(el("p", "count", `${MAX_ALERTS} of ${alerts.length} alerts`));
    }
  } else if (data.alerts) {
    parts.push(el("p", "empty", "no active SWPC alerts"));
  }

  root.replaceChildren(...parts);
}

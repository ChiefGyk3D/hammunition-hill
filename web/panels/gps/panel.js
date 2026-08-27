// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Where you are, and whether your clock is right.
//
// Tier 0: the position comes off a receiver attached to this machine and is
// never sent anywhere. What it *is* sent to is everyone on your LAN, via the
// snapshot — which is why the collector truncates to a Maidenhead locator
// before publishing and this panel shows the precision on its face.
//
// The clock reading is the other half. FT8 stops decoding somewhere around two
// seconds of error, and a laptop that has been off the network for a day can
// drift further than that without anything saying so.

function line(el, label, value, className) {
  const row = el("div", "detail-row");
  row.append(el("span", "detail-label", label), el("span", className ?? "detail-value", value));
  return row;
}

export function render(root, { data, el }) {
  const snapshot = data.gps;
  if (!snapshot) {
    root.replaceChildren(el("p", "empty", "no GPS source configured"));
    return;
  }
  const payload = snapshot.data;
  if (!payload) {
    root.replaceChildren(
      el("p", "error", snapshot.error ? `failed: ${snapshot.error}` : "no data"),
    );
    return;
  }

  if (!payload.has_fix) {
    root.replaceChildren(el("p", "empty", payload.reason ?? "no fix"));
    return;
  }

  const parts = [];

  const grid = el("div", "gps-grid", payload.grid);
  if (payload.stale) grid.classList.add("stale");
  parts.push(grid);

  const rows = el("div", "detail");
  rows.append(
    line(el, "Fix", `${payload.quality}${payload.satellites ? ` · ${payload.satellites} sats` : ""}`),
    line(el, "Source", payload.source),
    line(el, "Precision", `${payload.precision} chars`),
  );

  // Coordinates appear only if the operator turned them on. When they are
  // absent that is the setting working, so say so rather than leaving a gap
  // that reads like a missing feature.
  if (payload.lat !== undefined) {
    rows.append(line(el, "Position", `${payload.lat}, ${payload.lon}`));
  } else {
    rows.append(line(el, "Position", "grid only — not published", "detail-value muted"));
  }

  if (payload.clock_offset_seconds !== null && payload.clock_offset_seconds !== undefined) {
    const offset = payload.clock_offset_seconds;
    const sign = offset > 0 ? "slow" : "fast";
    rows.append(
      line(
        el,
        "Clock",
        payload.clock_ok
          ? `${Math.abs(offset).toFixed(1)}s — within tolerance`
          : `${Math.abs(offset).toFixed(1)}s ${sign} — too far for FT8`,
        payload.clock_ok ? "detail-value" : "detail-value clock-bad",
      ),
    );
  }

  if (payload.stale) {
    rows.append(line(el, "Warning", "fix is old — receiver may have lost the sky", "detail-value clock-bad"));
  }

  parts.push(rows);
  root.replaceChildren(...parts);
}

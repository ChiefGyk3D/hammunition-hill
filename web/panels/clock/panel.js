// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Tier 0: computed entirely in the browser. No network, no snapshot, no
// dependency on anything being reachable.

const two = (n) => String(n).padStart(2, "0");
const utcStamp = (d) => `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())}`;

export function render(root, { station, el }) {
  const now = new Date();

  const label = el("div", "clock-label", "UTC");
  const main = el("div", "clock-main", utcStamp(now));
  const local = el(
    "div",
    "clock-local",
    `${now.toLocaleTimeString(undefined, { hour12: false })} local · ${now.toISOString().slice(0, 10)}`,
  );

  const parts = [label, main, local];
  if (station.grid) {
    parts.push(el("div", "clock-local", `grid ${station.grid}`));
  }
  root.replaceChildren(...parts);
}

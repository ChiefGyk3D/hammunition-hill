// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// What the log index knows. This is the panel that tells an operator whether
// "needed" colouring can be trusted -- if the prefix table is the built-in one,
// the entity resolution is approximate and this says so.

function readout(el, label, value, sub) {
  const box = el("div", "readout");
  box.append(el("div", "label", label), el("div", "value", String(value)));
  if (sub) box.append(el("div", "sub", sub));
  return box;
}

export function render(root, { data, el }) {
  const stats = data.log?.data;
  if (!stats) {
    root.replaceChildren(el("p", "empty", "no log source configured"));
    return;
  }
  if (!stats.found) {
    root.replaceChildren(
      el("p", "error", `no log at ${stats.path}`),
      el("p", "empty", "spots will show without needed-slot colouring"),
    );
    return;
  }

  const grid = el("div", "readouts");
  // "147 of 340" rather than a bare 147: progress needs a denominator, and
  // the honest one is however many entities the active prefix table can
  // resolve -- which is why it comes from the snapshot, not a constant here.
  const dxcc = stats.entity_total
    ? `${stats.entities} of ${stats.entity_total}`
    : String(stats.entities);
  grid.append(
    readout(el, "QSOs", stats.qso_count.toLocaleString()),
    readout(el, "DXCC", dxcc, `${stats.confirmed_entities} confirmed`),
    readout(el, "Band slots", stats.band_slots),
    readout(el, "Mode slots", stats.mode_slots),
  );
  if (stats.states !== undefined) {
    grid.append(
      readout(
        el,
        "WAS",
        `${stats.states} / 50`,
        stats.states === 0
          ? "no STATE fields seen in this log"
          : `${stats.confirmed_states} confirmed`,
      ),
    );
  }

  const parts = [grid];
  // The finish line is the interesting part: name the missing states once the
  // list is short enough to be a plan rather than a wall.
  const missing = stats.states_missing ?? [];
  if (stats.states > 0 && missing.length > 0 && missing.length <= 12) {
    parts.push(el("p", "count", `WAS needs: ${missing.join(" ")}`));
  }
  if (stats.prefix_source === "built-in") {
    parts.push(
      el("p", "empty", "entities resolved with the built-in prefix table — approximate. Set [log] cty_dat for accuracy."),
    );
  }
  if (stats.unresolved) {
    parts.push(el("p", "empty", `${stats.unresolved} callsigns could not be resolved to an entity`));
  }
  root.replaceChildren(...parts);
}

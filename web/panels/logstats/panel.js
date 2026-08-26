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
  grid.append(
    readout(el, "QSOs", stats.qso_count.toLocaleString()),
    readout(el, "Entities", stats.entities, `${stats.confirmed_entities} confirmed`),
    readout(el, "Band slots", stats.band_slots),
    readout(el, "Mode slots", stats.mode_slots),
  );

  const parts = [grid];
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

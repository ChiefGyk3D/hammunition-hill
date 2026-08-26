// POTA and SOTA in one list. Both programs answer the same operator question --
// "who is out there right now and what can I work?" -- so splitting them across
// two panels just makes you look twice.

import { distance, khz, neededClass } from "../../lib/format.js";

const MAX_ROWS = 20;

export function render(root, { data, el }) {
  const pota = data.pota?.data?.spots ?? [];
  const sota = data.sota?.data?.spots ?? [];

  if (!data.pota && !data.sota) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const merged = [
    ...pota.map((spot) => ({ ...spot, program: "POTA" })),
    ...sota.map((spot) => ({ ...spot, program: "SOTA" })),
  ]
    .filter((spot) => spot.khz)
    .sort((a, b) => (a.band_sort ?? 99) - (b.band_sort ?? 99) || a.khz - b.khz);

  if (merged.length === 0) {
    root.replaceChildren(el("p", "empty", "no activations right now"));
    return;
  }

  const list = el("ul", "activations");
  for (const spot of merged.slice(0, MAX_ROWS)) {
    const item = el("li");

    const head = el("div", "act-head");
    const call = el("span", "act-call", spot.call);
    const need = neededClass(spot.needed);
    head.append(el("span", `act-program prog-${spot.program.toLowerCase()}`, spot.program), call);
    if (need) head.append(el("span", `need-badge ${need.cls}`, need.label));
    head.append(el("span", "act-freq", `${khz(spot.khz)} ${spot.mode ?? ""}`.trim()));

    const where = [spot.reference, spot.park || spot.summit, spot.location]
      .filter(Boolean)
      .join(" · ");
    item.append(head, el("div", "act-where", where || spot.entity || ""));

    if (spot.path) {
      item.append(
        el("div", "act-path", `${Math.round(spot.path.bearing)}° ${spot.path.compass} · ${distance(spot.path)}`),
      );
    }
    list.append(item);
  }

  const parts = [list];
  if (merged.length > MAX_ROWS) {
    parts.push(el("p", "count", `${MAX_ROWS} of ${merged.length} activations`));
  }
  root.replaceChildren(...parts);
}

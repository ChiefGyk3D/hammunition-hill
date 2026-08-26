// Tier 1: reads snapshots written by the collector. Every value on this panel
// came from this host, not from a third-party banner image.

function readout(el, label, value, sub) {
  const box = el("div", "readout");
  box.append(el("div", "label", label), el("div", "value", value ?? "—"));
  if (sub) box.append(el("div", "sub", sub));
  return box;
}

export function render(root, { data, el }) {
  const solar = data.hamqsl?.data ?? {};
  const kp = data.kindex?.data ?? {};
  const flux = data.solarflux?.data ?? {};
  const xray = data.xray?.data ?? {};

  if (!data.hamqsl && !data.kindex) {
    root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
    return;
  }

  const grid = el("div", "readouts");
  grid.append(
    readout(el, "SFI", solar.solarflux ?? flux.flux, "10.7cm"),
    readout(el, "A-index", solar.aindex),
    readout(
      el,
      "K-index",
      kp.kp !== undefined ? kp.kp.toFixed(1) : solar.kindex,
      kp.storm_level && kp.storm_level !== "quiet" ? kp.storm_level : undefined,
    ),
    readout(el, "Sunspots", solar.sunspots),
    readout(el, "X-ray", xray.class ?? solar.xray, xray.peak_today?.class ? `peak ${xray.peak_today.class}` : undefined),
    readout(el, "Sol wind", solar.solarwind, "km/s"),
  );

  const parts = [grid];
  if (solar.geomagfield) {
    parts.push(el("p", "empty", `geomagnetic field: ${solar.geomagfield.toLowerCase()}`));
  }
  root.replaceChildren(...parts);
}

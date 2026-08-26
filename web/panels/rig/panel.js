// Live rig state from rigctld.
//
// Read-only, structurally: the collector's rigctl client sends two get commands
// and has no code path that sets anything. A dashboard should never be able to
// key your transmitter.

import { khz } from "../../lib/format.js";

export function render(root, { data, el }) {
  const state = data.rig?.data;
  if (!state) {
    root.replaceChildren(el("p", "empty", "rigctld not connected"));
    return;
  }
  if (state.error) {
    root.replaceChildren(el("p", "error", `rigctld: ${state.error}`));
    return;
  }

  const parts = [
    el("div", "clock-label", state.band ? `${state.band} · ${state.mode ?? ""}`.trim() : "no band"),
    el("div", "clock-main", state.khz ? khz(state.khz) : "—"),
    el("div", "clock-local", "kHz"),
  ];
  if (state.passband_hz) {
    parts.push(el("div", "clock-local", `${state.passband_hz} Hz passband`));
  }
  root.replaceChildren(...parts);
}

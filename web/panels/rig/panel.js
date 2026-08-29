// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Live rig state from rigctld.
//
// Read-only, structurally: the collector's rigctl client sends two get commands
// and has no code path that sets anything. A dashboard should never be able to
// key your transmitter.

import { khz } from "../../lib/format.js";

export function render(root, { data, el }) {
  // "Not connected" implies a connection was attempted. Without a
  // [[sources]] entry it never was; the missing snapshot is the difference.
  if (!data.rig) {
    root.replaceChildren(
      el("p", "empty", "no rig source configured — rigctld, see config.example.toml"),
    );
    return;
  }
  const state = data.rig.data;
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

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The Reverse Beacon Network, in the two forms that are worth screen space.
//
// "Hearing me" is the one nothing else in this dashboard can give you: call CQ
// and several hundred unattended receivers report whether they decoded you, and
// how well. It is the only feedback loop in amateur radio that answers "is my
// signal getting out" before anybody does.
//
// "Band activity" is the other half of the same data: thousands of automated
// decodes a minute is a propagation measurement rather than an opinion.
//
// The aggregation is done in the collector, because RBN emits far more than a
// browser should hold. This renders what arrived.

import { recall, relativeAge, remember } from "../../lib/format.js";

const VIEWS = ["hearing me", "band activity"];

let state = null;

function ensureState() {
  if (state) return state;
  state = { view: recall("rbn-view", "hearing me") };
  return state;
}

// A skimmer's SNR is a real measurement, so it can carry a real scale. The
// thresholds are the ones a CW operator would recognise: below 6 dB is a
// struggle, above 20 is armchair copy.
function snrClass(db) {
  if (db >= 20) return "rbn-strong";
  if (db >= 6) return "rbn-fair";
  return "rbn-weak";
}

export function render(root, { data, el }) {
  const snapshot = data.rbn;
  // Absent snapshot vs empty snapshot is the honest split: a configured
  // stream writes one (data or failure) soon after startup, an unconfigured
  // one never will, and "waiting for the first spots" from a receiver nobody
  // switched on is a wait that cannot end.
  if (!snapshot) {
    root.replaceChildren(
      el("p", "empty", "no RBN source configured — your callsign turns it on, see docs/RBN.md"),
    );
    return;
  }
  if (!snapshot.data) {
    root.replaceChildren(
      el(
        "p",
        snapshot.error ? "error" : "empty",
        snapshot.error ? `stream failed: ${snapshot.error}` : "waiting for the first spots…",
      ),
    );
    return;
  }
  const payload = snapshot.data;
  const s = ensureState();

  const draw = () => {
    const parts = [];

    const tabs = el("div", "cw-tabs");
    for (const view of VIEWS) {
      const button = el("button", "chip" + (view === s.view ? " on" : ""), view);
      button.type = "button";
      button.addEventListener("click", () => {
        s.view = view;
        remember("rbn-view", view);
        draw();
      });
      tabs.append(button);
    }
    parts.push(tabs);

    if (s.view === "hearing me") {
      const heard = payload.heard_me || [];
      const watching = (payload.watching || []).join(", ") || "nobody";
      if (!heard.length) {
        parts.push(
          el(
            "p",
            "empty",
            `no skimmer has reported ${watching} yet — ` +
              `call CQ and they will, or check the callsign in [[sources]]`,
          ),
        );
      } else {
        const list = el("div", "rbn-list");
        for (const item of heard) {
          const row = el("div", "rbn-row");
          row.append(
            el("span", "rbn-spotter", item.spotter),
            el("span", `rbn-snr ${snrClass(item.snr_db)}`, `${item.snr_db} dB`),
            el("span", "rbn-band", item.band || `${Math.round(item.khz)}`),
            el("span", "rbn-mode", item.mode),
            el("span", "rbn-wpm", item.wpm ? `${item.wpm} wpm` : ""),
            el("span", "rbn-age", relativeAge(item.spotted_at)),
          );
          list.append(row);
        }
        parts.push(list);
        parts.push(
          el("p", "rbn-note", `${heard.length} reports of ${watching}, newest first`),
        );
      }
    }

    if (s.view === "band activity") {
      const activity = payload.activity || [];
      if (!activity.length) {
        parts.push(el("p", "empty", "no spots in the window yet"));
      } else {
        const list = el("div", "rbn-list");
        for (const row of activity) {
          const line = el("div", "rbn-row rbn-activity");
          line.append(
            el("span", "rbn-band", row.band),
            el("span", "rbn-mode", row.mode),
            el("span", "rbn-count", `${row.spots}`),
            el("span", "rbn-calls", `${row.calls} calls`),
            el("span", "rbn-calls", `${row.spotters} skimmers`),
            el(
              "span",
              `rbn-snr ${snrClass(row.best_snr)}`,
              row.best_call ? `${row.best_call} ${row.best_snr} dB` : "",
            ),
          );
          list.append(line);
        }
        parts.push(list);
        parts.push(
          el(
            "p",
            "rbn-note",
            `${payload.spots_in_window} decodes in the last ` +
              `${Math.round(payload.window_seconds / 60)} minutes, busiest band first`,
          ),
        );
      }
    }

    parts.push(
      el(
        "p",
        "rbn-note",
        "Automated decodes by unattended receivers — a measurement of what got " +
          "through, not a judgement about who was interesting.",
      ),
    );

    root.replaceChildren(...parts);
  };

  draw();
}

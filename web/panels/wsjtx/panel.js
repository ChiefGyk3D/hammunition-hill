// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// WSJT-X decodes, straight off the local UDP broadcast.
//
// Listen-only: the collector binds a socket and never sends. WSJT-X's protocol
// has reply messages that change the running instance's state, and driving
// someone's transmitter is not a dashboard's job.

const MAX_ROWS = 12;

function snrClass(snr) {
  if (snr >= 0) return "snr-strong";
  if (snr >= -15) return "snr-fair";
  return "snr-weak";
}

export function render(root, { data, el }) {
  const payload = data.wsjtx?.data;
  if (!payload) {
    root.replaceChildren(el("p", "empty", "no WSJT-X broadcast heard"));
    return;
  }

  const parts = [];
  const status = payload.status;
  if (status) {
    const line = [status.khz ? `${status.khz} kHz` : null, status.mode]
      .filter(Boolean)
      .join(" · ");
    const bar = el("div", "wsjtx-status", line);
    if (status.transmitting) bar.append(el("span", "tx-flag", "TX"));
    parts.push(bar);
  }

  const decodes = payload.decodes ?? [];
  if (decodes.length === 0) {
    parts.push(el("p", "empty", "no decodes yet"));
  } else {
    const list = el("ul", "decodes");
    for (const decode of decodes.slice(0, MAX_ROWS)) {
      const item = el("li");
      item.append(
        el("span", `decode-snr ${snrClass(decode.snr)}`, String(decode.snr).padStart(3, " ")),
        el("span", "decode-msg", decode.message),
        el("span", "decode-at", decode.at),
      );
      list.append(item);
    }
    parts.push(list);
  }

  if (payload.last_logged) {
    parts.push(el("p", "count", `last logged: ${payload.last_logged.call}`));
  }
  root.replaceChildren(...parts);
}

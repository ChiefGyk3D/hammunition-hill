// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Logging a QSO.
//
// The reason this belongs here rather than in a standalone logger: the
// dashboard already knows almost the whole contact. rigctld gives the frequency,
// band and mode as they are right now; a selected spot gives the callsign and
// entity; the lookup gives the name. So logging is a confirmation, not a
// form-filling exercise.
//
// It writes to a plain ADIF file, which is the same file the needed-slot
// colouring reads -- so working a new entity here makes the spot list stop
// calling it new on the next cycle, with no synchronisation step.

import { recall, remember } from "../../lib/format.js";

const state = { book: recall("logbook.book", null), busy: false, message: null, fields: {} };

const INPUTS = [
  { key: "CALL", label: "Call", width: "10ch", required: true },
  { key: "RST_SENT", label: "Sent", width: "6ch" },
  { key: "RST_RCVD", label: "Rcvd", width: "6ch" },
  { key: "NAME", label: "Name", width: "12ch" },
  { key: "COMMENT", label: "Comment", width: "20ch" },
];

/** Default signal reports: 59 for voice, 599 for anything else. */
function defaultReport(mode) {
  return /SSB|USB|LSB|AM|FM/i.test(mode ?? "") ? "59" : "599";
}

function prefill(data) {
  const rig = data.rig?.data ?? {};
  const mode = rig.mode ?? "";
  return {
    BAND: rig.band ?? "",
    MODE: mode,
    FREQ: rig.khz ? (rig.khz / 1000).toFixed(4) : "",
    RST_SENT: defaultReport(mode),
    RST_RCVD: defaultReport(mode),
  };
}

export function render(root, { data, el }) {
  const payload = data.logbooks?.data;
  if (!payload) {
    root.replaceChildren(el("p", "empty", "no logbooks configured — see docs/LOGBOOK.md"));
    return;
  }

  const books = payload.logbooks ?? [];
  const active =
    books.find((b) => b.id === state.book) ?? books.find((b) => b.primary) ?? books[0];
  const auto = prefill(data);
  const parts = [];

  if (books.length > 1) {
    const row = el("div", "chips");
    for (const book of books) {
      const chip = el("button", "chip", book.name);
      chip.type = "button";
      if (book.id === active?.id) chip.classList.add("on");
      chip.addEventListener("click", () => {
        state.book = book.id;
        remember("logbook.book", book.id);
        render(root, { data, el });
      });
      row.append(chip);
    }
    parts.push(row);
  }

  if (!payload.writable) {
    parts.push(
      el("p", "empty", "read-only — set [logging] enabled = true to log from here"),
    );
  } else if (active) {
    const form = el("div", "log-form");

    for (const input of INPUTS) {
      const wrap = el("label", "log-field");
      wrap.append(el("span", "log-label", input.label));
      const field = el("input", "log-input");
      field.type = "text";
      field.style.width = input.width;
      field.value = state.fields[input.key] ?? auto[input.key] ?? "";
      field.dataset.key = input.key;
      field.autocomplete = "off";
      field.spellcheck = false;
      field.addEventListener("input", (event) => {
        state.fields[input.key] = event.target.value;
      });
      wrap.append(field);
      form.append(wrap);
    }

    const context = [auto.BAND, auto.MODE, auto.FREQ ? `${auto.FREQ} MHz` : null]
      .filter(Boolean)
      .join(" · ");
    if (context) form.append(el("span", "log-context", context));

    const submit = el("button", "chip log-submit", state.busy ? "LOGGING…" : "LOG QSO");
    submit.type = "button";
    submit.disabled = state.busy;
    submit.addEventListener("click", async () => {
      const qso = { ...auto, ...state.fields };
      state.busy = true;
      render(root, { data, el });
      try {
        const response = await fetch("./api/qso", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ logbook: active.id, qso }),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error ?? response.statusText);
        state.message = { text: `logged ${body.logged.CALL}`, ok: true };
        // Keep the band and mode; clear what belongs to the contact.
        state.fields = {};
      } catch (err) {
        state.message = { text: `not logged: ${err.message}`, ok: false };
      } finally {
        state.busy = false;
        render(root, { data, el });
      }
    });
    form.append(submit);
    parts.push(form);
  }

  if (state.message) {
    parts.push(el("p", state.message.ok ? "count" : "error", state.message.text));
  }

  const entries = active?.recent ?? [];
  if (entries.length) {
    const table = el("table", "beacons");
    const thead = el("thead");
    const head = el("tr");
    for (const label of ["Call", "Date", "UTC", "Band", "Mode"]) head.append(el("th", null, label));
    thead.append(head);
    table.append(thead);

    const body = el("tbody");
    for (const qso of entries) {
      const row = el("tr");
      const date = qso.QSO_DATE ?? "";
      const time = qso.TIME_ON ?? "";
      row.append(
        el("td", "bx-call", qso.CALL ?? "—"),
        el("td", "bx-freq", date.length === 8 ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6)}` : date),
        el("td", "bx-freq", time.slice(0, 4)),
        el("td", "bx-band", qso.BAND ?? "—"),
        el("td", "bx-where", qso.MODE ?? "—"),
      );
      body.append(row);
    }
    table.append(body);
    parts.push(el("p", "count", `${active.name} — last ${entries.length}`), table);
  } else if (active) {
    parts.push(el("p", "empty", `${active.name} is empty`));
  }

  root.replaceChildren(...parts);
}

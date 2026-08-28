// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The pocket reference. The CW panel teaches; this one answers.
//
// Everything is a static table published by the collector at startup, so the
// whole panel works with the WAN unplugged -- which is exactly when somebody
// in a field needs to check what QSP means or where the 40 m QRP calling
// frequency is. The one view that is links rather than tables navigates away
// on purpose: an anchor costs nothing under the CSP and the dashboard fetches
// nothing on anyone's behalf.

import { recall, remember } from "../../lib/format.js";

const VIEWS = ["q codes", "abbrev", "numbers", "phonetic", "RST", "freqs", "links"];

const state = { view: recall("reference.view") || "q codes", filter: "" };

function rows(el, entries, key, value) {
  const wrap = el("div", "cw-chart");
  const needle = state.filter.trim().toUpperCase();
  for (const entry of entries) {
    if (
      needle &&
      !String(entry[key]).toUpperCase().includes(needle) &&
      !String(entry[value]).toUpperCase().includes(needle)
    ) {
      continue;
    }
    const row = el("div", "cw-row");
    row.append(el("span", "cw-key", entry[key]), el("span", "cw-code", entry[value]));
    wrap.append(row);
  }
  if (!wrap.childElementCount) wrap.append(el("p", "empty", "nothing matches"));
  return wrap;
}

function rstColumn(el, title, entries) {
  const box = el("div", "ref-rst-col");
  box.append(el("p", "ref-rst-head", title));
  for (const entry of entries) {
    const row = el("div", "cw-row");
    row.append(el("span", "cw-key", entry.value), el("span", "cw-code", entry.meaning));
    box.append(row);
  }
  return box;
}

export function render(root, { data, el }) {
  const reference = data.reference?.data;
  if (!reference) {
    root.replaceChildren(el("p", "empty", "reference tables not published yet"));
    return;
  }

  const parts = [];
  const tabs = el("div", "cw-tabs");
  for (const view of VIEWS) {
    // "chip" is the styled class the other panels use; a first version said
    // "cw-tab", which exists nowhere in the stylesheet, so every tab rendered
    // as an unstyled grey button and the active one looked like the rest.
    const tab = el("button", "chip" + (view === state.view ? " on" : ""), view);
    tab.type = "button";
    tab.addEventListener("click", () => {
      state.view = view;
      remember("reference.view", view);
      render(root, { data, el });
    });
    tabs.append(tab);
  }
  parts.push(tabs);

  // One filter across the lookup views: the panel exists for "what was that
  // code again", and scanning sixty rows is the failure it replaces.
  if (!["RST", "links"].includes(state.view)) {
    const box = el("div", "cs-form");
    const input = el("input", "cs-input");
    input.type = "text";
    input.placeholder = "filter…";
    input.value = state.filter;
    input.autocomplete = "off";
    input.setAttribute("aria-label", "Filter the reference table");
    input.addEventListener("input", (event) => {
      state.filter = event.target.value;
      render(root, { data, el });
      const next = root.querySelector(".cs-input");
      if (next) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    });
    box.append(input);
    parts.push(box);
  }

  if (state.view === "q codes") {
    parts.push(rows(el, reference.q_codes, "code", "meaning"));
  } else if (state.view === "abbrev") {
    const merged = [...reference.prosigns, ...reference.abbreviations];
    parts.push(rows(el, merged, "code", "meaning"));
  } else if (state.view === "numbers") {
    parts.push(rows(el, reference.number_codes, "code", "meaning"));
    parts.push(
      el(
        "p",
        "cw-hint",
        "Survivors of the wire-telegraph 92 Code of 1859 — which is why 73 " +
          "is plural-free: it is a number, not a count.",
      ),
    );
  } else if (state.view === "phonetic") {
    parts.push(rows(el, reference.phonetics, "char", "word"));
  } else if (state.view === "RST") {
    const wrap = el("div", "ref-rst");
    wrap.append(
      rstColumn(el, "R — readability (1–5)", reference.rst.readability),
      rstColumn(el, "S — strength (1–9)", reference.rst.strength),
      rstColumn(el, "T — tone, CW only (1–9)", reference.rst.tone),
    );
    parts.push(wrap);
    parts.push(
      el(
        "p",
        "cw-hint",
        "Spoken reports drop the T: “five nine” on phone, 599 on CW. A " +
          "contest 599 is an exchange format, not a measurement.",
      ),
    );
  } else if (state.view === "freqs") {
    parts.push(rows(el, reference.calling_frequencies, "mhz", "use"));
    parts.push(
      el(
        "p",
        "cw-hint",
        "US conventions, MHz. Custom, not regulation — Part 97 assigns no " +
          "calling frequencies. Listen first; move off to work a contact.",
      ),
    );
  } else if (state.view === "links") {
    const wrap = el("div", "ref-links");
    for (const link of reference.links) {
      const row = el("div", "ref-link-row");
      const anchor = el("a", "ref-link", link.name);
      anchor.href = link.url;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      row.append(anchor, el("span", "cw-note", link.why));
      wrap.append(row);
    }
    parts.push(wrap);
    parts.push(
      el(
        "p",
        "cw-hint",
        "Links leave this dashboard — nothing here is fetched on your behalf.",
      ),
    );
  }

  root.replaceChildren(...parts);
}

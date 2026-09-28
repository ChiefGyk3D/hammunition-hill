// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Memory channels: the frequencies you actually use.
//
// Every operator keeps this list somewhere -- the back of a logbook, a note on
// the rig, a spreadsheet nobody can find. It is a small thing and it is the
// kind of small thing a dashboard should absorb.
//
// Tier 0 in the strongest sense available here: the list lives in this
// browser's localStorage and there is no endpoint that could accept it, so
// "nothing is sent anywhere" is a property of the architecture rather than a
// promise. That also means it is per display -- the shack TV and the field
// phone keep separate lists -- which is why export and import are on the panel
// rather than left as an exercise.
//
// The one piece of real work it does is check each entry against the band plan
// for your licence class. A memory is a frequency you are about to key up on,
// and a list that silently contains one you may not transmit on is worse than
// no list: it looks checked.

import { recall, remember } from "../../lib/format.js";
import { bandColor } from "../../lib/bandcolors.js";

const KEY = "memories.channels";

const state = {
  channels: null,
  plan: null,
  loading: false,
  error: null,
  adding: false,
  draft: { label: "", khz: "", mode: "", note: "" },
  rerender: null,
};

const MODES = ["CW", "Phone", "Digital", "FM", "SSB", "FT8"];

/** Which band plan segment covers a frequency, if any. */
function segmentAt(plan, khz) {
  for (const band of plan?.bands ?? []) {
    for (const segment of band.segments ?? []) {
      const [low, high] = segment.khz;
      if (khz >= low && khz <= high) return { band, segment };
    }
  }
  return null;
}

/**
 * Which licence class to check against.
 *
 * The same precedence the band plan panel uses, and deliberately so: an
 * operator who picked General over there should not have to pick it again
 * here, and a panel that disagreed with the one next to it about what you may
 * transmit on would be worse than one that did not check at all.
 */
function activeClass(plan, station) {
  const known = (id) => (plan?.classes ?? []).some((c) => c.id === id);
  const chosen = recall("bandplan.class", null);
  if (known(chosen)) return chosen;
  if (known(station?.license_class)) return station.license_class;
  return plan?.classes?.[plan.classes.length - 1]?.id ?? null;
}

function mhz(khz) {
  return (khz / 1000).toFixed(3);
}

function load() {
  const stored = recall(KEY, null);
  return Array.isArray(stored) ? stored : [];
}

function save(channels) {
  state.channels = channels;
  remember(KEY, channels);
}

/** Entries sorted by frequency, which is the order a rig's memories read in. */
function sorted(channels) {
  return [...channels].sort((a, b) => a.khz - b.khz);
}

function parseKhz(text) {
  const value = Number(String(text).trim().replace(/,/g, ""));
  if (!Number.isFinite(value) || value <= 0) return null;
  // People type both. Anything under 500 is being given in MHz -- there is no
  // amateur allocation below 500 kHz outside 630 m and 2200 m, and both of
  // those are above 135, so the ambiguous band is narrow and the guess is
  // safe. Above 500 it is kHz, which is what the rest of the dashboard uses.
  return value < 500 ? value * 1000 : value;
}

function field(el, { label, value, placeholder, onInput, list }) {
  const wrap = el("label", "mem-field");
  wrap.append(el("span", "mem-field-label", label));
  const input = el("input", "mem-input");
  input.value = value;
  input.placeholder = placeholder ?? "";
  if (list) input.setAttribute("list", list);
  input.addEventListener("input", () => onInput(input.value));
  wrap.append(input);
  return wrap;
}

function verdict(el, plan, klass, khz) {
  if (!plan) return el("span", "mem-verdict muted", "band plan not loaded");
  const hit = segmentAt(plan, khz);
  if (!hit) {
    return el("span", "mem-verdict mem-out", "outside the amateur bands");
  }
  const allowed = (hit.segment.classes ?? []).includes(klass);
  const modes = (hit.segment.modes ?? []).join(", ");
  if (!allowed) {
    const name = (plan.classes.find((c) => c.id === klass) ?? {}).name ?? klass;
    return el("span", "mem-verdict mem-out", `${hit.band.band} — not ${name}`);
  }
  return el("span", "mem-verdict mem-ok", `${hit.band.band} · ${modes}`);
}

function addForm(root, el, plan, klass) {
  const form = el("div", "mem-form");

  // The verdict line refreshes itself on every keystroke instead of the panel
  // re-rendering. Rebuilding the form to update one line would take the focus
  // and the cursor position with it, and typing a frequency into a field that
  // loses focus every character is not a feature.
  const preview = el("div", "mem-preview");
  const showVerdict = () => {
    const typed = parseKhz(state.draft.khz);
    if (typed === null) {
      preview.replaceChildren();
      return;
    }
    preview.replaceChildren(el("span", "mem-freq", mhz(typed)), verdict(el, plan, klass, typed));
  };

  form.append(
    field(el, {
      label: "Name",
      value: state.draft.label,
      placeholder: "Sunday net",
      onInput: (v) => {
        state.draft.label = v;
      },
    }),
    field(el, {
      label: "kHz or MHz",
      value: state.draft.khz,
      placeholder: "14300 or 14.300",
      onInput: (v) => {
        state.draft.khz = v;
        showVerdict();
      },
    }),
    field(el, {
      label: "Mode",
      value: state.draft.mode,
      placeholder: "SSB",
      list: "mem-modes",
      onInput: (v) => {
        state.draft.mode = v;
      },
    }),
    field(el, {
      label: "Note",
      value: state.draft.note,
      placeholder: "optional",
      onInput: (v) => {
        state.draft.note = v;
      },
    }),
  );

  // A datalist rather than a select: the six common answers are one keystroke
  // away and anything else is still typeable, which matters because the list of
  // modes people actually use has no end.
  const list = el("datalist");
  list.id = "mem-modes";
  for (const mode of MODES) {
    const option = el("option");
    option.value = mode;
    list.append(option);
  }
  form.append(list);

  const actions = el("div", "chips");
  const add = el("button", "chip on", "ADD");
  add.type = "button";
  add.addEventListener("click", () => {
    const khz = parseKhz(state.draft.khz);
    if (khz === null) {
      state.error = `"${state.draft.khz}" is not a frequency`;
      state.rerender();
      return;
    }
    save([
      ...state.channels,
      {
        label: state.draft.label.trim() || mhz(khz),
        khz,
        mode: state.draft.mode.trim(),
        note: state.draft.note.trim(),
      },
    ]);
    state.draft = { label: "", khz: "", mode: "", note: "" };
    state.error = null;
    state.adding = false;
    state.rerender();
  });

  const cancel = el("button", "chip", "CANCEL");
  cancel.type = "button";
  cancel.addEventListener("click", () => {
    state.adding = false;
    state.error = null;
    state.rerender();
  });
  actions.append(add, cancel);

  // Live verdict while typing, so a frequency outside your privileges is
  // obvious before it is saved rather than after.
  showVerdict();
  form.append(preview, actions);
  return form;
}

export function render(root, { data, el }) {
  if (state.channels === null) state.channels = load();

  if (!state.plan && !state.loading) {
    state.loading = true;
    fetch("./bandplans/index.json")
      .then((r) => r.json())
      .then((index) => {
        const chosen =
          index.available.find((p) => p.id === recall("bandplan.plan", null)) ??
          index.available.find((p) => p.id === index.default) ??
          index.available[0];
        return fetch(`./bandplans/${chosen.file}`).then((r) => r.json());
      })
      .then((plan) => {
        state.plan = plan;
      })
      .catch((err) => {
        // A failed band plan costs the privilege check and nothing else. The
        // list is the point; showing it unchecked beats showing an error.
        state.planError = err.message;
      })
      .finally(() => {
        state.loading = false;
        if (state.rerender) state.rerender();
      });
  }

  state.rerender = () => render(root, { data, el });

  const station = data.station?.data ?? {};
  const klass = activeClass(state.plan, station);

  const parts = [];

  const actions = el("div", "chips");
  if (!state.adding) {
    const add = el("button", "chip", "ADD");
    add.type = "button";
    add.addEventListener("click", () => {
      state.adding = true;
      state.rerender();
    });
    actions.append(add);
  }

  // Export writes the file the browser cannot keep for you across machines.
  // Import is the other half; without both, a list you built on the shack
  // machine is stranded there.
  const exportButton = el("button", "chip", "EXPORT");
  exportButton.type = "button";
  exportButton.title = "Download this list as JSON";
  exportButton.addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(sorted(state.channels), null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = el("a");
    link.href = url;
    link.download = "frequencies.json";
    link.click();
    URL.revokeObjectURL(url);
  });
  actions.append(exportButton);

  const importLabel = el("label", "chip", "IMPORT");
  const importInput = el("input", "mem-file");
  importInput.type = "file";
  importInput.accept = "application/json,.json";
  importInput.setAttribute("aria-label", "Import a frequency list");
  importInput.addEventListener("change", () => {
    const file = importInput.files?.[0];
    if (!file) return;
    file
      .text()
      .then((text) => {
        const parsed = JSON.parse(text);
        if (!Array.isArray(parsed)) throw new Error("not a list");
        const clean = parsed
          .filter((entry) => entry && Number.isFinite(Number(entry.khz)))
          .map((entry) => ({
            label: String(entry.label ?? "").slice(0, 60),
            khz: Number(entry.khz),
            mode: String(entry.mode ?? "").slice(0, 20),
            note: String(entry.note ?? "").slice(0, 120),
          }));
        save(clean);
        state.error = null;
      })
      .catch((err) => {
        state.error = `import failed: ${err.message}`;
      })
      .finally(() => state.rerender());
  });
  importLabel.append(importInput);
  actions.append(importLabel);

  parts.push(actions);

  if (state.adding) parts.push(addForm(root, el, state.plan, klass));
  if (state.error) parts.push(el("p", "error", state.error));

  const channels = sorted(state.channels);
  if (!channels.length) {
    parts.push(
      el(
        "p",
        "empty",
        "no frequencies yet — ADD one, or IMPORT a list you exported from another display",
      ),
    );
  } else {
    const table = el("table", "memories");
    const head = el("tr");
    for (const label of ["", "MHz", "Name", "Mode", "Band / privileges", ""]) {
      head.append(el("th", null, label));
    }
    const thead = el("thead");
    thead.append(head);
    table.append(thead);

    const body = el("tbody");
    for (const channel of channels) {
      const hit = segmentAt(state.plan, channel.khz);
      const row = el("tr");

      const swatch = el("td", "mem-swatch");
      const dot = el("span", "mem-dot");
      dot.style.background = bandColor(hit?.band.band);
      swatch.append(dot);

      row.append(
        swatch,
        el("td", "mem-freq", mhz(channel.khz)),
        el("td", "mem-name", channel.label),
        el("td", "mem-mode", channel.mode || "—"),
      );

      const check = el("td", "mem-check");
      check.append(verdict(el, state.plan, klass, channel.khz));
      if (channel.note) check.append(el("span", "mem-note", channel.note));
      row.append(check);

      const remove = el("td", "mem-remove");
      const button = el("button", "chip", "×");
      button.type = "button";
      button.setAttribute("aria-label", `Remove ${channel.label}`);
      button.addEventListener("click", () => {
        save(state.channels.filter((c) => c !== channel));
        state.rerender();
      });
      remove.append(button);
      row.append(remove);

      body.append(row);
    }
    table.append(body);
    parts.push(table);
  }

  const klassName =
    (state.plan?.classes ?? []).find((c) => c.id === klass)?.name ?? "no licence class set";
  parts.push(
    el(
      "p",
      "count",
      `${channels.length} ${channels.length === 1 ? "frequency" : "frequencies"} · ` +
        `checked against ${state.plan?.name ?? "no band plan"} for ${klassName} · ` +
        "kept in this browser only",
    ),
  );

  root.replaceChildren(...parts);
}

// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// CW: reference, translation, and something to practise against.
//
// Tier 0 throughout. The operator most likely to want a prosign chart is the
// one sitting at a straight key in a field with no signal, which is exactly
// when a hosted dashboard is no help at all.
//
// Tables come from the published snapshot rather than being defined here, so
// the chart on screen and the table under test are the same data.

import { recall, remember } from "../../lib/format.js";
import {
  KOCH_ORDER,
  decodeMorse,
  encodeText,
  play,
  practiceGroups,
  tables,
  timing,
} from "../../lib/morse.js";

const VIEWS = ["translate", "letters", "prosigns", "q codes", "abbrev", "practice"];

let state = null;
let stopAudio = null;

function ensureState() {
  if (state) return state;
  state = {
    view: recall("cw-view", "translate"),
    text: recall("cw-text", "CQ CQ DE"),
    wpm: Number(recall("cw-wpm", 20)) || 20,
    effective: Number(recall("cw-effective", 20)) || 20,
    pitch: Number(recall("cw-pitch", 600)) || 600,
    kochCount: Number(recall("cw-koch", 4)) || 4,
    practice: "",
    playing: false,
  };
  return state;
}

function chartRows(el, entries, key, value, extra) {
  const wrap = el("div", "cw-chart");
  for (const entry of entries) {
    const row = el("div", "cw-row");
    row.append(el("span", "cw-key", entry[key]), el("span", "cw-code", entry[value]));
    if (extra && entry[extra]) row.append(el("span", "cw-note", entry[extra]));
    wrap.append(row);
  }
  return wrap;
}

function control(el, label, value, min, max, onChange) {
  const box = el("label", "cw-control");
  box.append(el("span", "cw-control-label", `${label} ${value}`));
  const input = document.createElement("input");
  input.type = "range";
  input.min = String(min);
  input.max = String(max);
  input.value = String(value);
  input.className = "cw-slider";
  input.addEventListener("input", () => onChange(Number(input.value)));
  box.append(input);
  return box;
}

export function render(root, { data, el }) {
  const snapshot = data.morse;
  if (!snapshot?.data) {
    root.replaceChildren(el("p", "empty", "waiting for the reference tables…"));
    return;
  }
  const reference = snapshot.data;
  const { encode, decode } = tables(reference);
  const s = ensureState();

  const draw = () => {
    const parts = [];

    const tabs = el("div", "cw-tabs");
    for (const view of VIEWS) {
      const button = el("button", "chip" + (view === s.view ? " on" : ""), view);
      button.type = "button";
      button.addEventListener("click", () => {
        s.view = view;
        remember("cw-view", view);
        draw();
      });
      tabs.append(button);
    }
    parts.push(tabs);

    if (s.view === "translate" || s.view === "practice") {
      const speeds = el("div", "cw-controls");
      speeds.append(
        control(el, "WPM", s.wpm, 5, 40, (v) => {
          s.wpm = v;
          if (s.effective > v) s.effective = v;
          remember("cw-wpm", v);
          draw();
        }),
        control(el, "effective", s.effective, 5, 40, (v) => {
          s.effective = Math.min(v, s.wpm);
          remember("cw-effective", s.effective);
          draw();
        }),
        control(el, "Hz", s.pitch, 400, 900, (v) => {
          s.pitch = v;
          remember("cw-pitch", v);
          draw();
        }),
      );
      parts.push(speeds);

      const plan = timing(s.wpm, s.effective);
      const note = el("p", "cw-timing");
      note.textContent =
        `dit ${plan.dit.toFixed(0)} ms · dah ${plan.dah.toFixed(0)} ms · ` +
        `gap ${plan.inter.toFixed(0)} ms` +
        (s.effective < s.wpm ? ` · Farnsworth ${s.effective}/${s.wpm}` : "");
      parts.push(note);
    }

    if (s.view === "translate") {
      const input = document.createElement("textarea");
      input.className = "cw-input";
      input.rows = 2;
      input.value = s.text;
      input.spellcheck = false;
      input.setAttribute("aria-label", "Text or Morse to translate");
      input.addEventListener("input", () => {
        s.text = input.value;
        remember("cw-text", input.value);
        draw();
      });
      parts.push(input);

      // Which direction to translate is decided by what was typed, because
      // asking would be a control the input already answers.
      const looksLikeMorse = /^[.\-·•—–/\s]+$/.test(s.text) && /[.\-·•—–]/.test(s.text);
      const output = looksLikeMorse
        ? decodeMorse(s.text, decode)
        : encodeText(s.text, encode);

      const result = el("div", "cw-output", output || "—");
      parts.push(result);
      parts.push(
        el("p", "cw-hint", looksLikeMorse ? "reading as Morse → text" : "reading as text → Morse"),
      );

      const morse = looksLikeMorse ? s.text : output;
      const button = el("button", "cw-play", s.playing ? "stop" : "play");
      button.type = "button";
      button.disabled = !morse.trim();
      button.addEventListener("click", () => {
        if (s.playing) {
          if (stopAudio) stopAudio();
          return;
        }
        s.playing = true;
        draw();
        stopAudio = play(morse, {
          wpm: s.wpm,
          effectiveWpm: s.effective,
          pitch: s.pitch,
          onDone: () => {
            s.playing = false;
            stopAudio = null;
            draw();
          },
        });
      });
      parts.push(button);
    }

    if (s.view === "letters") {
      const wrap = el("div", "cw-columns");
      wrap.append(
        chartRows(el, reference.letters, "char", "code"),
        chartRows(el, reference.digits, "char", "code"),
        chartRows(el, reference.punctuation, "char", "code"),
      );
      parts.push(wrap);
    }

    if (s.view === "prosigns") {
      parts.push(
        el("p", "cw-hint", "Sent as one symbol, with no gap between the letters."),
        chartRows(el, reference.prosigns, "sign", "code", "meaning"),
      );
      const collisions = reference.prosigns.filter((p) => p.also);
      if (collisions.length) {
        parts.push(
          el(
            "p",
            "cw-hint",
            "Some are the same sound as a punctuation mark — " +
              collisions.map((p) => `${p.sign} = ${p.also}`).join(", ") +
              ". Context tells you which is meant.",
          ),
        );
      }
    }

    if (s.view === "q codes") parts.push(chartRows(el, reference.q_codes, "code", "meaning"));

    if (s.view === "abbrev") {
      parts.push(chartRows(el, reference.abbreviations, "code", "meaning"));
      if (reference.cut_numbers?.length) {
        parts.push(
          el("p", "cw-hint", "Cut numbers — contest shorthand, which is why you hear 5NN:"),
          chartRows(el, reference.cut_numbers, "digit", "cut", "code"),
        );
      }
    }

    if (s.view === "practice") {
      const alphabet = KOCH_ORDER.slice(0, s.kochCount);
      parts.push(
        control(el, "characters", s.kochCount, 2, KOCH_ORDER.length, (v) => {
          s.kochCount = v;
          remember("cw-koch", v);
          s.practice = "";
          draw();
        }),
      );
      parts.push(
        el(
          "p",
          "cw-hint",
          `Koch order: ${alphabet.split("").join(" ")} — each new character is ` +
            `chosen to be confusable with the ones before it, which is the point.`,
        ),
      );

      const controls = el("div", "cw-practice-controls");
      const gen = el("button", "cw-play", "new groups");
      gen.type = "button";
      gen.addEventListener("click", () => {
        s.practice = practiceGroups(alphabet);
        draw();
      });
      controls.append(gen);

      if (s.practice) {
        const send = el("button", "cw-play", s.playing ? "stop" : "send");
        send.type = "button";
        send.addEventListener("click", () => {
          if (s.playing) {
            if (stopAudio) stopAudio();
            return;
          }
          s.playing = true;
          draw();
          stopAudio = play(encodeText(s.practice, encode), {
            wpm: s.wpm,
            effectiveWpm: s.effective,
            pitch: s.pitch,
            onDone: () => {
              s.playing = false;
              stopAudio = null;
              draw();
            },
          });
        });
        controls.append(send);

        const reveal = el("button", "cw-play", "reveal");
        reveal.type = "button";
        reveal.addEventListener("click", () => {
          const answer = el("div", "cw-output", s.practice);
          controls.after(answer);
          reveal.disabled = true;
        });
        controls.append(reveal);
      }
      parts.push(controls);
      // Say what state we are in either way. After generating, the groups are
      // deliberately hidden -- that is the exercise -- but silence looks like
      // the button did nothing.
      parts.push(
        el(
          "p",
          "cw-hint",
          s.practice
            ? "Groups ready and hidden. Send them, copy what you hear, then reveal."
            : "Generate groups, copy what you hear, then reveal to check.",
        ),
      );
    }

    root.replaceChildren(...parts);
  };

  draw();
}

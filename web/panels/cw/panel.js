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
import { decodeMorse, encodeText, play, tables, timing } from "../../lib/morse.js";
import {
  alphabetFor,
  callsigns,
  entityFor,
  groups,
  qso,
  quizQuestion,
  rng,
  seedNow,
} from "../../lib/cwpractice.js";

// No "q codes" or "abbrev" here any more: this panel teaches, the Pocket
// Reference answers, and for a while both carried the same two tables. The
// trainer still quizzes on them (BANKS below) -- that is teaching.
const VIEWS = ["translate", "letters", "prosigns", "trainer"];

// What the trainer can send. Each is a different thing to get better at:
// discriminating characters, catching a callsign once, following an exchange
// you already half-know, and recalling what a signal means.
const DRILLS = ["groups", "callsigns", "QSO", "quiz"];
const BANKS = ["phonetics", "q codes", "abbrev"];

let state = null;
let stopAudio = null;

function ensureState() {
  if (state) return state;
  state = {
    // Reconciled against VIEWS below: a browser that stored "q codes" before
    // that view moved to the Pocket Reference would otherwise render nothing.
    view: recall("cw-view", "translate"),
    text: recall("cw-text", "CQ CQ DE"),
    wpm: Number(recall("cw-wpm", 20)) || 20,
    effective: Number(recall("cw-effective", 20)) || 20,
    pitch: Number(recall("cw-pitch", 600)) || 600,
    lesson: Number(recall("cw-lesson", 3)) || 3,
    drill: recall("cw-drill", "groups"),
    bank: recall("cw-bank", "phonetics"),
    qsoStyle: recall("cw-qso-style", "ragchew"),
    myCall: recall("cw-mycall", "N0CALL"),
    myName: recall("cw-myname", "OM"),
    // What is loaded and hidden: the text to send, and how to show the answer.
    drillText: "",
    drillAnswer: null,
    revealed: false,
    question: null,
    score: { right: 0, asked: 0 },
    playing: false,
  };
  if (!VIEWS.includes(state.view)) state.view = "translate";
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

function field(el, label, value, onChange) {
  const box = el("label", "cw-control");
  box.append(el("span", "cw-control-label", label));
  const input = document.createElement("input");
  input.type = "text";
  input.className = "cw-field";
  input.value = value;
  input.spellcheck = false;
  input.addEventListener("change", () => onChange(input.value.trim()));
  box.append(input);
  return box;
}

function scoreText() {
  const { right, asked } = state.score;
  if (!asked) return "Pick the meaning. Score appears once you answer.";
  return `${right} of ${asked} — ${Math.round((right / asked) * 100)}%`;
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

    // The quiz is written, not sent, so the speed and pitch controls would be
    // three sliders that do nothing.
    if (s.view === "translate" || (s.view === "trainer" && s.drill !== "quiz")) {
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

    if (s.view === "trainer") {
      const practice = reference.practice;
      if (!practice) {
        parts.push(el("p", "empty", "this snapshot predates the trainer — restart the collector"));
        root.replaceChildren(...parts);
        return;
      }
      const prefixNames = practice.prefixes.map((entry) => entry.prefix);

      // Changing what is being drilled must not leave the previous answer on
      // screen, so every switch clears the loaded item.
      const reset = () => {
        s.drillText = "";
        s.drillAnswer = null;
        s.revealed = false;
        s.question = null;
      };

      const drills = el("div", "cw-tabs cw-subtabs");
      for (const drill of DRILLS) {
        const button = el("button", "chip" + (drill === s.drill ? " on" : ""), drill);
        button.type = "button";
        button.addEventListener("click", () => {
          s.drill = drill;
          remember("cw-drill", drill);
          reset();
          draw();
        });
        drills.append(button);
      }
      parts.push(drills);

      // --- what to load, per drill -------------------------------------------
      const loaders = {
        groups: () => {
          const alphabet = alphabetFor(s.lesson, practice.koch_order, practice.first_lesson);
          s.drillText = groups(rng(seedNow()), alphabet);
          s.drillAnswer = el("div", "cw-output", s.drillText);
        },
        callsigns: () => {
          const calls = callsigns(rng(seedNow()), prefixNames);
          s.drillText = calls.join(" ");
          const list = el("div", "cw-chart cw-callsign-list");
          for (const call of calls) {
            const row = el("div", "cw-row");
            row.append(
              el("span", "cw-key", call),
              el("span", "cw-note", entityFor(call, practice.prefixes)),
            );
            list.append(row);
          }
          s.drillAnswer = list;
        },
        QSO: () => {
          const lines = qso(rng(seedNow()), prefixNames, practice, {
            style: s.qsoStyle,
            myCall: s.myCall,
            myName: s.myName,
          });
          // Only the other station is sent. Copying your own sending is not
          // the exercise -- following someone else's is.
          s.drillText = lines
            .filter((line) => line.speaker === "dx")
            .map((line) => line.text)
            .join(" = ");
          const script = el("div", "cw-qso");
          for (const line of lines) {
            const row = el("div", "cw-qso-line" + (line.speaker === "me" ? " cw-qso-me" : ""));
            row.append(
              el("span", "cw-qso-who", line.speaker === "me" ? "you" : "dx"),
              el("span", "cw-qso-text", line.text),
            );
            script.append(row);
          }
          s.drillAnswer = script;
        },
        quiz: () => {
          s.question = quizQuestion(rng(seedNow()), practice.quizzes[s.bank]);
          s.drillText = "";
          s.drillAnswer = null;
        },
      };

      // --- per-drill controls -------------------------------------------------
      if (s.drill === "groups") {
        const order = practice.koch_order;
        const maxLesson = order.length - practice.first_lesson + 1;
        parts.push(
          control(el, "lesson", s.lesson, 1, maxLesson, (v) => {
            s.lesson = v;
            remember("cw-lesson", v);
            reset();
            draw();
          }),
        );
        const alphabet = alphabetFor(s.lesson, order, practice.first_lesson);
        parts.push(
          el(
            "p",
            "cw-hint",
            `${alphabet.split("").join(" ")} — Koch order, so each new character ` +
              `is confusable with the ones before it. That is the point: you are ` +
              `always discriminating, never merely recognising.`,
          ),
        );
      }

      if (s.drill === "callsigns") {
        parts.push(
          el(
            "p",
            "cw-hint",
            `Real DXCC prefixes from the same table the callsign panel uses, so ` +
              `revealing also names the entity. A call goes past once on the air; ` +
              `this is practice at getting it the first time.`,
          ),
        );
      }

      if (s.drill === "QSO") {
        const styles = el("div", "cw-tabs cw-subtabs");
        for (const style of Object.keys(practice.scripts)) {
          const button = el("button", "chip" + (style === s.qsoStyle ? " on" : ""), style);
          button.type = "button";
          button.addEventListener("click", () => {
            s.qsoStyle = style;
            remember("cw-qso-style", style);
            reset();
            draw();
          });
          styles.append(button);
        }
        parts.push(styles);
        parts.push(field(el, "your call", s.myCall, (v) => {
          s.myCall = v.toUpperCase() || "N0CALL";
          remember("cw-mycall", s.myCall);
          reset();
        }));
        parts.push(field(el, "your name", s.myName, (v) => {
          s.myName = v.toUpperCase() || "OM";
          remember("cw-myname", s.myName);
          reset();
        }));
        parts.push(
          el(
            "p",
            "cw-hint",
            `Only the other station is sent. Knowing what comes next is most of ` +
              `what makes a real exchange readable above your cold-copy speed.`,
          ),
        );
      }

      if (s.drill === "quiz") {
        const banks = el("div", "cw-tabs cw-subtabs");
        for (const bank of BANKS) {
          const button = el("button", "chip" + (bank === s.bank ? " on" : ""), bank);
          button.type = "button";
          button.addEventListener("click", () => {
            s.bank = bank;
            remember("cw-bank", bank);
            reset();
            draw();
          });
          banks.append(button);
        }
        parts.push(banks);
      }

      // --- load / send / reveal ----------------------------------------------
      const controls = el("div", "cw-practice-controls");
      const gen = el("button", "cw-play", s.drill === "quiz" ? "next" : "new");
      gen.type = "button";
      gen.addEventListener("click", () => {
        reset();
        loaders[s.drill]();
        draw();
      });
      controls.append(gen);

      if (s.drillText) {
        const send = el("button", "cw-play", s.playing ? "stop" : "send");
        send.type = "button";
        send.addEventListener("click", () => {
          if (s.playing) {
            if (stopAudio) stopAudio();
            return;
          }
          s.playing = true;
          draw();
          stopAudio = play(encodeText(s.drillText, encode), {
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
        reveal.disabled = s.revealed;
        reveal.addEventListener("click", () => {
          s.revealed = true;
          draw();
        });
        controls.append(reveal);
      }
      parts.push(controls);

      if (s.revealed && s.drillAnswer) parts.push(s.drillAnswer);

      // --- the quiz is its own shape -----------------------------------------
      if (s.drill === "quiz" && s.question) {
        parts.push(el("div", "cw-output", s.question.prompt));
        const options = el("div", "cw-options");
        for (const option of s.question.options) {
          const button = el("button", "cw-option", option);
          button.type = "button";
          button.addEventListener("click", () => {
            const right = option === s.question.answer;
            s.score = { right: s.score.right + (right ? 1 : 0), asked: s.score.asked + 1 };
            button.classList.add(right ? "cw-right" : "cw-wrong");
            for (const other of options.querySelectorAll("button")) other.disabled = true;
            if (!right) {
              for (const other of options.querySelectorAll("button")) {
                if (other.textContent === s.question.answer) other.classList.add("cw-right");
              }
            }
            scoreLine.textContent = scoreText();
          });
          options.append(button);
        }
        parts.push(options);
        const scoreLine = el("p", "cw-hint", scoreText());
        parts.push(scoreLine);
      }

      // Say what state we are in either way. After generating, the item is
      // deliberately hidden -- that is the exercise -- but silence looks like
      // the button did nothing.
      if (s.drill !== "quiz") {
        parts.push(
          el(
            "p",
            "cw-hint",
            s.drillText
              ? s.revealed
                ? "Revealed. Load another when you are ready."
                : "Loaded and hidden. Send it, copy what you hear, then reveal."
              : "Load an item, copy what you hear, then reveal to check.",
          ),
        );
      }
    }

    root.replaceChildren(...parts);
  };

  draw();
}

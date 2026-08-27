// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Licence exam practice.
//
// This panel fetches its own data rather than declaring `sources` in its
// manifest, which is a deliberate exception to how every other panel works.
// The reason is size: a question pool is several hundred questions, roughly a
// megabyte of JSON across the three elements, and the panel host re-fetches a
// dashboard's declared sources every ten seconds. Re-downloading a megabyte
// every ten seconds for data that changes every four years is not a trade worth
// making on a Pi over WiFi.
//
// So: fetched once per element, on demand, and cached in module state. Still
// same-origin, still nothing outside this machine.

import { recall, remember } from "../../lib/format.js";
import {
  buildExam,
  grade,
  questionsIn,
  sectionExam,
  studyQuestion,
} from "../../lib/exam.js";
import { seedNow } from "../../lib/cwpractice.js";

const ELEMENTS = [
  { id: "technician", label: "Technician" },
  { id: "general", label: "General" },
  { id: "extra", label: "Extra" },
];

// Five ways to work, because people study differently and the pool supports all
// of them: read the syllabus through, be asked at random, sit one section, sit
// the whole thing, or go back over what you got wrong.
const MODES = ["read", "study", "section", "exam", "review"];

// element id -> pool, or the string "missing" / "failed".
const pools = new Map();
let state = null;

function ensureState() {
  if (state) return state;
  state = {
    element: recall("exam-element", "technician"),
    mode: recall("exam-mode", "study"),
    scope: recall("exam-scope", ""),
    cursor: 0,
    missed: [],
    question: null,
    answered: null,
    score: { right: 0, asked: 0 },
    weak: new Set(),
    exam: null,
    answers: [],
    index: 0,
    result: null,
  };
  return state;
}

async function loadPool(elementId, redraw) {
  if (pools.has(elementId)) return pools.get(elementId);
  pools.set(elementId, "loading");
  try {
    const response = await fetch(`./data/exam-${elementId}.json`, { cache: "no-store" });
    if (!response.ok) {
      pools.set(elementId, "missing");
    } else {
      const snapshot = await response.json();
      pools.set(elementId, snapshot.data || "failed");
    }
  } catch {
    pools.set(elementId, "failed");
  }
  redraw();
  return pools.get(elementId);
}

// 47 CFR Part 97, loaded the same way and for the same reason: 154 kB that
// only matters once a reader asks why an answer is what it is. Fetched on the
// first rules question and cached, so a session that never opens one never
// pays for it.
let rules = null;

async function loadRules(redraw) {
  if (rules !== null) return rules;
  rules = "loading";
  try {
    const response = await fetch("./data/part97.json", { cache: "no-store" });
    rules = response.ok ? (await response.json()).data || "missing" : "missing";
  } catch {
    rules = "missing";
  }
  redraw();
  return rules;
}

// `97.113(a)(4)` and `97.5a` both open at the section. Paragraph citations are
// shown as written, but the whole section is what gets displayed: quoting one
// paragraph out of its section is how a rule gets misread, because the
// exceptions usually live two paragraphs further down.
function sectionFor(reference) {
  const found = /97\.\d+/.exec(reference || "");
  return found ? found[0] : "";
}

// The rule itself, under the citation. Nothing here is written by us: every
// word is the FCC's, which is the entire reason this is worth showing. A
// question whose reference is outside Part 97 -- two cite Part 1 -- gets the
// citation alone, and says so rather than showing nothing.
function ruleFor(el, reference, redraw) {
  const parts = [el("p", "exam-note", `Rule reference: \u00a7${reference}`)];
  const number = sectionFor(reference);
  if (!number) {
    parts.push(el("p", "exam-hint", "Outside Part 97, so the text is not bundled."));
    return parts;
  }
  const loaded = loadRules(redraw);
  if (rules === "loading" || rules === null) {
    parts.push(el("p", "exam-hint", "loading the rule\u2026"));
    return parts;
  }
  if (rules === "missing") {
    parts.push(el("p", "exam-hint", "Part 97 is not on disk \u2014 run hamhill serve again."));
    return parts;
  }
  void loaded;
  const section = (rules.sections || []).find((entry) => entry.number === number);
  if (!section) {
    parts.push(el("p", "exam-hint", `\u00a7${number} is not in the bundled edition.`));
    return parts;
  }
  const box = el("div", "exam-rule");
  box.appendChild(el("p", "exam-rule-head", `\u00a7${section.number} ${section.title}`));
  box.appendChild(el("pre", "exam-rule-text", section.text));
  box.appendChild(
    el(
      "p",
      "exam-rule-note",
      `47 CFR \u00a7${section.number}, ${rules.edition || "as published"} edition. ` +
        `The section in full, as the FCC published it.`,
    ),
  );
  parts.push(box);
  return parts;
}

// A pool past its dates is the failure this feature has to guard against: the
// questions look completely normal and are the wrong ones.
function validity(el, pool) {
  if (pool.status === "expired") {
    return el(
      "p",
      "exam-expired",
      `This pool expired after ${pool.valid_until}. The questions have changed — ` +
        `download the current one and run hamhill exam-import again.`,
    );
  }
  if (pool.status === "future") {
    return el("p", "exam-note", `This pool takes effect in ${pool.valid_from}.`);
  }
  if (pool.status === "unknown") {
    return el(
      "p",
      "exam-note",
      "This pool states no validity years, so whether it is current cannot be checked here.",
    );
  }
  return el("p", "exam-note", `Valid ${pool.valid_from}–${pool.valid_until}.`);
}

function answerList(el, question, chosen, onPick) {
  const list = el("div", "exam-answers");
  question.answers.forEach((text, index) => {
    let className = "exam-answer";
    if (chosen !== null && index === question.correct) className += " exam-right";
    else if (chosen === index) className += " exam-wrong";
    const button = el("button", className, `${"ABCD"[index]}. ${text}`);
    button.type = "button";
    button.disabled = chosen !== null;
    button.addEventListener("click", () => onPick(index));
    list.append(button);
  });
  return list;
}

export function render(root, { el }) {
  const s = ensureState();

  const draw = () => {
    const parts = [];

    const tabs = el("div", "cw-tabs");
    for (const element of ELEMENTS) {
      const button = el("button", "chip" + (element.id === s.element ? " on" : ""), element.label);
      button.type = "button";
      button.addEventListener("click", () => {
        s.element = element.id;
        remember("exam-element", element.id);
        s.question = null;
        s.answered = null;
        s.exam = null;
        s.result = null;
        draw();
      });
      tabs.append(button);
    }
    parts.push(tabs);

    const pool = pools.get(s.element);
    if (pool === undefined) {
      loadPool(s.element, draw);
      parts.push(el("p", "empty", "loading the question pool…"));
      root.replaceChildren(...parts);
      return;
    }
    if (pool === "loading") {
      parts.push(el("p", "empty", "loading the question pool…"));
      root.replaceChildren(...parts);
      return;
    }
    if (pool === "missing" || pool === "failed") {
      parts.push(
        el(
          "p",
          "empty",
          `no ${s.element} pool imported — download it from arrl.org/question-pools ` +
            `and run: hamhill exam-import --file <pool.txt>`,
        ),
      );
      root.replaceChildren(...parts);
      return;
    }

    const modes = el("div", "cw-tabs cw-subtabs");
    for (const mode of MODES) {
      const button = el("button", "chip" + (mode === s.mode ? " on" : ""), mode);
      button.type = "button";
      button.addEventListener("click", () => {
        s.mode = mode;
        remember("exam-mode", mode);
        s.result = null;
        s.question = null;
        s.answered = null;
        s.exam = null;
        s.cursor = 0;
        draw();
      });
      modes.append(button);
    }
    parts.push(modes);

    // Scope: the whole pool, or one subelement. Section tests need one, and the
    // other modes are simply narrowed by it.
    if (s.mode !== "exam" && s.mode !== "review") {
      const scopes = el("div", "cw-tabs cw-subtabs");
      const all = el("button", "chip" + (s.scope === "" ? " on" : ""), "all");
      all.type = "button";
      all.addEventListener("click", () => {
        s.scope = "";
        remember("exam-scope", "");
        s.question = null;
        s.cursor = 0;
        draw();
      });
      if (s.mode !== "section") scopes.append(all);
      for (const subelement of pool.subelements) {
        const button = el("button", "chip" + (subelement === s.scope ? " on" : ""), subelement);
        button.type = "button";
        button.title = pool.subelement_titles[subelement] || subelement;
        button.addEventListener("click", () => {
          s.scope = subelement;
          remember("exam-scope", subelement);
          s.question = null;
          s.exam = null;
          s.cursor = 0;
          draw();
        });
        scopes.append(button);
      }
      parts.push(scopes);
      if (s.scope) {
        parts.push(
          el("p", "exam-id", pool.subelement_titles[s.scope] || s.scope),
        );
      }
    }

    parts.push(validity(el, pool));

    if (s.mode === "read") {
      // Straight through, in pool order, answer showing. Some people learn the
      // syllabus by reading it, and a panel that only ever asked questions at
      // random would not let them.
      const scoped = questionsIn(pool, s.scope);
      if (!scoped.length) {
        parts.push(el("p", "empty", "no questions in that section"));
      } else {
        s.cursor = Math.max(0, Math.min(s.cursor, scoped.length - 1));
        const question = scoped[s.cursor];
        const nav = el("div", "cw-practice-controls");
        const back = el("button", "cw-play", "previous");
        back.type = "button";
        back.disabled = s.cursor === 0;
        back.addEventListener("click", () => {
          s.cursor -= 1;
          draw();
        });
        const forward = el("button", "cw-play", "next");
        forward.type = "button";
        forward.disabled = s.cursor >= scoped.length - 1;
        forward.addEventListener("click", () => {
          s.cursor += 1;
          draw();
        });
        nav.append(back, forward);
        parts.push(nav);
        parts.push(
          el(
            "p",
            "exam-id",
            `${question.id} · ${s.cursor + 1} of ${scoped.length} · ` +
              `${pool.group_titles[question.group] || ""}`,
          ),
        );
        parts.push(el("div", "exam-question", question.text));
        parts.push(answerList(el, question, question.correct, () => {}));
        if (question.reference) {
          for (const node of ruleFor(el, question.reference, draw)) parts.push(node);
        }
      }
    }

    if (s.mode === "section" || s.mode === "review") {
      const controls = el("div", "cw-practice-controls");
      const label = s.mode === "section" ? "start section test" : "review missed";
      const start = el("button", "cw-play", s.exam ? "start over" : label);
      start.type = "button";
      start.disabled = s.mode === "review" && !s.missed.length;
      start.addEventListener("click", () => {
        s.exam =
          s.mode === "section"
            ? sectionExam(pool, s.scope || pool.subelements[0], seedNow())
            : s.missed.slice();
        s.answers = new Array(s.exam.length).fill(null);
        s.index = 0;
        s.result = null;
        draw();
      });
      controls.append(start);
      parts.push(controls);

      if (s.mode === "review" && !s.missed.length) {
        parts.push(
          el("p", "exam-note", "Nothing missed yet. Answer some questions first."),
        );
      } else if (!s.exam) {
        const wanted =
          s.mode === "section"
            ? (pool.subelement_weights || {})[s.scope || pool.subelements[0]] ||
              pool.groups.filter((g) => g.startsWith(s.scope)).length
            : s.missed.length;
        parts.push(
          el(
            "p",
            "exam-note",
            s.mode === "section"
              ? `${wanted} questions from ${s.scope || pool.subelements[0]} — exactly what ` +
                  `that subelement contributes to a real ${pool.exam_length}-question exam.`
              : `${wanted} questions you have got wrong this session.`,
          ),
        );
      }
    }

    if (s.mode === "study") {
      const next = el("div", "cw-practice-controls");
      const button = el("button", "cw-play", s.question ? "next question" : "start");
      button.type = "button";
      button.addEventListener("click", () => {
        s.question = studyQuestion(pool, seedNow(), s.weak, s.scope);
        s.answered = null;
        draw();
      });
      next.append(button);
      parts.push(next);

      if (s.question) {
        parts.push(
          el("p", "exam-id", `${s.question.id} · ${pool.group_titles[s.question.group] || ""}`),
        );
        parts.push(el("div", "exam-question", s.question.text));
        parts.push(
          answerList(el, s.question, s.answered, (index) => {
            if (s.answered !== null) return;
            s.answered = index;
            s.score = {
              right: s.score.right + (index === s.question.correct ? 1 : 0),
              asked: s.score.asked + 1,
            };
            // Wrong once means seen again sooner; right means it leaves the list.
            if (index === s.question.correct) {
              s.weak.delete(s.question.group);
            } else {
              s.weak.add(s.question.group);
              if (!s.missed.some((q) => q.id === s.question.id)) s.missed.push(s.question);
            }
            draw();
          }),
        );
        if (s.answered !== null && s.question.reference) {
          for (const node of ruleFor(el, s.question.reference, draw)) parts.push(node);
        }
      }

      const { right, asked } = s.score;
      parts.push(
        el(
          "p",
          "exam-note",
          asked
            ? `${right} of ${asked} this session — ${Math.round((right / asked) * 100)}%` +
                (s.weak.size
                  ? ` · ${s.weak.size} group${s.weak.size === 1 ? "" : "s"} to revisit`
                  : "")
            : "Answer to see the correct one and the rule it comes from.",
        ),
      );
    }

    if (s.mode === "exam") {
      const controls = el("div", "cw-practice-controls");
      const start = el("button", "cw-play", s.exam ? "start over" : "start exam");
      start.type = "button";
      start.addEventListener("click", () => {
        s.exam = buildExam(pool, seedNow());
        s.answers = new Array(s.exam.length).fill(null);
        s.index = 0;
        s.result = null;
        draw();
      });
      controls.append(start);
      parts.push(controls);

      if (!s.exam) {
        parts.push(
          el(
            "p",
            "exam-note",
            `${pool.exam_length} questions, one drawn from each group — the way a VE ` +
              `session builds one. ${pool.pass_mark} correct to pass.`,
          ),
        );
      }
    }

    // One renderer for every graded run: the full exam, a section test and a
    // review of what you missed all step through a list and score at the end.
    // They differ only in how the list was chosen.
    if (s.exam && (s.mode === "exam" || s.mode === "section" || s.mode === "review")) {
      if (s.result) {
        // A section test and a review are shorter than an exam, so the pass mark
        // does not apply to them; the score does.
        const graded = s.mode === "exam";
        parts.push(
          el(
            "div",
            "exam-result " + (!graded || s.result.passed ? "exam-passed" : "exam-failed"),
            `${s.result.right} of ${s.result.asked} — ${s.result.percent}%` +
              (graded
                ? ` · ${s.result.passed ? "pass" : "fail"} (${s.result.pass_mark} to pass)`
                : ""),
          ),
        );
        const missed = s.exam
          .map((question, index) => ({ question, given: s.answers[index] }))
          .filter((item) => item.given !== item.question.correct);
        for (const item of missed) {
          if (!s.missed.some((q) => q.id === item.question.id)) s.missed.push(item.question);
          s.weak.add(item.question.group);
        }
        if (missed.length) {
          const list = el("div", "exam-missed");
          for (const item of missed) {
            list.append(
              el("div", "exam-missed-row", `${item.question.id} · ${item.question.text}`),
            );
          }
          parts.push(el("p", "exam-note", `Missed ${missed.length}:`));
          parts.push(list);
        }
      } else {
        const question = s.exam[s.index];
        parts.push(
          el(
            "p",
            "exam-id",
            `Question ${s.index + 1} of ${s.exam.length} · ${question.id} · ` +
              `${pool.group_titles[question.group] || ""}`,
          ),
        );
        parts.push(el("div", "exam-question", question.text));
        parts.push(
          answerList(el, question, null, (index) => {
            s.answers[s.index] = index;
            if (s.index + 1 < s.exam.length) {
              s.index += 1;
            } else {
              s.result = grade(pool, s.exam, s.answers);
            }
            draw();
          }),
        );
        if (s.mode === "exam") {
          parts.push(
            el(
              "p",
              "exam-note",
              `One question from each of ${pool.groups.length} groups, which is how a ` +
                `real exam is built. ${pool.pass_mark} of ${pool.exam_length} to pass.`,
            ),
          );
        }
      }
    }

    root.replaceChildren(...parts);
  };

  draw();
}

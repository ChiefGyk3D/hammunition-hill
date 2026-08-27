// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The browser half of src/hammunition_hill/exam.py.
//
// Only the exam-building rule lives here; parsing and validation happen once at
// import time, in Python, where they are tested. What the browser needs is the
// ability to draw a fresh exam without asking anybody, which is the whole point
// of a tier 0 study panel: the operator practising for a licence is as likely
// to be on a train as at a desk.
//
// That rule is the load-bearing part and it is mirrored, so a test runs this
// file under node and demands the identical exam for the same seed.

import { rng } from "./cwpractice.js";

/** Fisher-Yates, matching the Python. */
function shuffle(items, next) {
  for (let i = items.length - 1; i > 0; i -= 1) {
    const j = Math.floor(next() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
}

/**
 * One question from each group, in a shuffled order.
 *
 * Not a uniform sample over the pool: that would over-weight whichever groups
 * happen to carry more questions and skip others entirely, which is a different
 * exam from the one a candidate will actually sit.
 */
export function buildExam(pool, seed) {
  const next = rng(seed);
  const groups = pool.groups.slice();
  const byGroup = new Map(groups.map((g) => [g, []]));
  for (const question of pool.questions) {
    const bucket = byGroup.get(question.group);
    if (bucket) bucket.push(question);
  }

  const chosen = groups.slice();
  shuffle(chosen, next);
  const wanted = pool.exam_length;
  while (chosen.length < wanted) {
    chosen.push(...groups.slice(0, wanted - chosen.length));
  }
  chosen.length = Math.min(chosen.length, wanted);

  const picked = chosen.map((group) => {
    const bucket = byGroup.get(group);
    return bucket[Math.floor(next() * bucket.length)];
  });
  shuffle(picked, next);
  return picked;
}

/**
 * A test over one subelement, the size that subelement contributes to the exam.
 *
 * The release states it -- "[6 Exam Questions - 6 Groups]" -- so practising a
 * section is practising that part of the real exam rather than a quiz that
 * happens to be about the same topic.
 */
export function sectionExam(pool, subelement, seed) {
  const next = rng(seed);
  const groups = pool.groups.filter((g) => g.startsWith(subelement));
  if (!groups.length) return [];

  const byGroup = new Map(groups.map((g) => [g, []]));
  for (const question of pool.questions) {
    const bucket = byGroup.get(question.group);
    if (bucket) bucket.push(question);
  }

  const wanted = (pool.subelement_weights || {})[subelement] || groups.length;
  const chosen = groups.slice();
  shuffle(chosen, next);
  while (chosen.length < wanted) chosen.push(...groups.slice(0, wanted - chosen.length));
  chosen.length = Math.min(chosen.length, wanted);

  const picked = chosen.map((group) => {
    const bucket = byGroup.get(group);
    return bucket[Math.floor(next() * bucket.length)];
  });
  shuffle(picked, next);
  return picked;
}

/** The pool narrowed to a subelement or a single group, in pool order. */
export function questionsIn(pool, scope) {
  if (!scope) return pool.questions;
  return pool.questions.filter((q) => q.id.startsWith(scope));
}

/** One question for study mode, weighted toward groups answered wrongly. */
export function studyQuestion(pool, seed, weakGroups, scope = "") {
  const next = rng(seed);
  const inScope = pool.groups.filter((g) => g.startsWith(scope));
  if (!inScope.length) return null;
  // A quarter of the time, revisit somewhere it went wrong. Not always: drilling
  // only mistakes means never seeing the rest of the syllabus again.
  const weak = [...(weakGroups || [])].filter((g) => inScope.includes(g));
  const from = weak.length && next() < 0.25 ? weak : inScope;
  const group = from[Math.floor(next() * from.length)];
  const candidates = pool.questions.filter((q) => q.group === group);
  return candidates[Math.floor(next() * candidates.length)];
}

/** Score an attempt the way a VE session would: a blank is wrong. */
export function grade(pool, questions, answers) {
  let right = 0;
  for (let i = 0; i < questions.length; i += 1) {
    if (answers[i] === questions[i].correct) right += 1;
  }
  return {
    right,
    asked: questions.length,
    pass_mark: pool.pass_mark,
    passed: right >= pool.pass_mark,
    percent: questions.length ? Math.round((1000 * right) / questions.length) / 10 : 0,
  };
}

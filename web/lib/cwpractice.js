// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The browser half of src/hammunition_hill/cwpractice.py.
//
// The curriculum data -- Koch order, phonetics, names, QTHs, QSO scripts --
// arrives as a snapshot; the generation happens here, because a trainer that
// asked the server for the next callsign would be a trainer that stops working
// when the network does, and this panel is tier 0 precisely so it does not.
//
// A second implementation is something that drifts, so every function below is
// mirrored in the Python module and a test runs this file under node and
// compares the exact output for the same seed. Keep them in step or the suite
// will tell you.

/** mulberry32. The same generator as the Python module, so seeds agree. */
export function rng(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = a ^ (a >>> 15);
    t = Math.imul(t, t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A seed from the clock, for when the caller does not care which one. */
export function seedNow() {
  return (Date.now() ^ (Math.random() * 0x100000000)) >>> 0;
}

function below(next, n) {
  return Math.floor(next() * n);
}

function pick(next, items) {
  return items[below(next, items.length)];
}

/** The characters a Koch lesson number covers. */
export function alphabetFor(lesson, order, firstLesson = 2) {
  const count = Math.max(firstLesson, Math.min(order.length, lesson + firstLesson - 1));
  return order.slice(0, count);
}

/** Random character groups: the Koch exercise itself. */
export function groups(next, alphabet, { count = 5, size = 5 } = {}) {
  if (!alphabet) return "";
  const out = [];
  for (let g = 0; g < count; g += 1) {
    let group = "";
    for (let i = 0; i < size; i += 1) group += pick(next, alphabet);
    out.push(group);
  }
  return out.join(" ");
}

// Two-letter suffixes dominate because they do on the air; see the Python
// module for why a generator weighted flat would be practice for a band that
// does not exist.
const SUFFIX_WEIGHTS = [
  [1, 0.15],
  [2, 0.5],
  [3, 0.35],
];
const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const DIGITS = "0123456789";

function suffixLength(next) {
  const roll = next();
  let running = 0;
  for (const [length, weight] of SUFFIX_WEIGHTS) {
    running += weight;
    if (roll < running) return length;
  }
  return SUFFIX_WEIGHTS[SUFFIX_WEIGHTS.length - 1][0];
}

/** A callsign shaped like a real one, from a real DXCC prefix. */
export function callsign(next, prefixes) {
  if (!prefixes || !prefixes.length) return "";
  const prefix = pick(next, prefixes);
  const area = DIGITS.includes(prefix[prefix.length - 1]) ? "" : pick(next, DIGITS);
  let suffix = "";
  for (let i = 0, n = suffixLength(next); i < n; i += 1) suffix += pick(next, LETTERS);
  return prefix + area + suffix;
}

export function callsigns(next, prefixes, { count = 5 } = {}) {
  const out = [];
  for (let i = 0; i < count; i += 1) out.push(callsign(next, prefixes));
  return out;
}

/** The DXCC entity a practice callsign belongs to, longest prefix first. */
export function entityFor(call, pool) {
  // Longest-first because "K" and "KH6" are both in the table and a Hawaiian
  // call must not come back as the mainland.
  const sorted = [...pool].sort((a, b) => b.prefix.length - a.prefix.length);
  for (const entry of sorted) {
    if (call.startsWith(entry.prefix)) return entry.entity;
  }
  return "";
}

function pad3(n) {
  return String(n).padStart(3, "0");
}

/** A whole simulated contact, both sides, with the other station filled in. */
export function qso(next, prefixes, practice, { style = "ragchew", myCall = "N0CALL", myName = "OM" } = {}) {
  const script = (practice.scripts || {})[style];
  if (!script) throw new Error(`unknown QSO style: ${style}`);
  const fields = {
    dx: callsign(next, prefixes),
    me: myCall,
    name: pick(next, practice.names),
    name_of_me: myName,
    qth: pick(next, practice.qths),
    rig: pick(next, practice.rigs),
    antenna: pick(next, practice.antennas),
    weather: pick(next, practice.weather),
    rst: `5${below(next, 3) + 7}9`,
    serial: pad3(below(next, 400) + 1),
    my_serial: pad3(below(next, 400) + 1),
  };
  return script.map((line) => ({
    speaker: line.speaker,
    text: line.text.replace(/\{(\w+)\}/g, (whole, key) => (key in fields ? fields[key] : whole)),
  }));
}

/** One quiz question: a prompt, the right answer, and three wrong ones. */
export function quizQuestion(next, pairs, { choices = 4 } = {}) {
  const answer = pick(next, pairs);
  const options = [answer];
  // Bounded: a pool with fewer distinct answers than `choices` would otherwise
  // spin here forever looking for a fourth wrong one that does not exist.
  for (let tries = 0; options.length < choices && tries < 200; tries += 1) {
    const candidate = pick(next, pairs);
    if (!options.some((o) => o.answer === candidate.answer)) options.push(candidate);
  }
  // Fisher-Yates, so the right answer is not always first.
  for (let i = options.length - 1; i > 0; i -= 1) {
    const j = below(next, i + 1);
    [options[i], options[j]] = [options[j], options[i]];
  }
  return { prompt: answer.prompt, answer: answer.answer, options: options.map((o) => o.answer) };
}

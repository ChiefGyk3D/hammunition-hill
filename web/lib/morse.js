// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Morse translation and audio, from the tables the collector published.
//
// The tables are NOT defined here. They live in src/hammunition_hill/morse.py,
// where a test checks that the digits follow the standard progression, that
// nothing collides, and that "PARIS" at N words per minute takes exactly a
// minute. This file receives them as data and does the two things a browser
// can do that Python cannot: translate as you type, and make a sound.
//
// The audio is a plain oscillator with a short attack and release envelope.
// Keying an oscillator on and off with a square edge produces key clicks --
// audible as a tick either side of every element, and on the air the thing
// that gets you a complaint from the next channel up. A few milliseconds of
// ramp removes them, and it is the same fix in software as in hardware.

const RAMP_SECONDS = 0.005;

/** Build the lookup maps from a published reference payload. */
export function tables(reference) {
  const encode = new Map();
  const decode = new Map();
  for (const group of ["letters", "digits", "punctuation", "extended"]) {
    for (const entry of reference[group] ?? []) {
      encode.set(entry.char, entry.code);
      if (!decode.has(entry.code)) decode.set(entry.code, entry.char);
    }
  }
  return { encode, decode };
}

export function encodeText(text, encode, { unknown = "?" } = {}) {
  return text
    .toUpperCase()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) =>
      [...word]
        .map((ch) => encode.get(ch) ?? unknown)
        .filter(Boolean)
        .join(" "),
    )
    .filter(Boolean)
    .join(" / ");
}

export function decodeMorse(code, decode, { unknown = "?" } = {}) {
  const normalised = code
    .replace(/[·•]/g, ".")
    .replace(/[—–_]/g, "-")
    .replace(/ {2,}/g, " / ");
  return normalised
    .split("/")
    .map((chunk) =>
      chunk
        .split(/\s+/)
        .filter(Boolean)
        .map((token) => decode.get(token) ?? unknown)
        .join(""),
    )
    .filter(Boolean)
    .join(" ");
}

/**
 * Element timings in milliseconds. Mirrors morse.timing() in Python; the
 * constants are the standard's, not ours.
 */
export function timing(wpm, effectiveWpm) {
  const effective = Math.min(effectiveWpm || wpm, wpm);
  const dit = 1200 / wpm;
  if (effective === wpm) {
    return { dit, dah: dit * 3, intra: dit, inter: dit * 3, word: dit * 7 };
  }
  // ARRL Farnsworth: stretch the gaps, leave the characters alone.
  const delayMs = ((60 * wpm - 37.2 * effective) / (wpm * effective)) * 1000;
  return {
    dit,
    dah: dit * 3,
    intra: dit,
    inter: (delayMs * 3) / 19,
    word: (delayMs * 7) / 19,
  };
}

/** Turn a Morse string into a flat schedule of tones and silences. */
export function schedule(morse, plan) {
  const events = [];
  let at = 0;
  const chars = morse.split(" ");
  for (let i = 0; i < chars.length; i += 1) {
    const token = chars[i];
    if (token === "/") {
      // The word gap replaces the character gap already added, not adds to it.
      at += plan.word - plan.inter;
      continue;
    }
    for (let e = 0; e < token.length; e += 1) {
      const length = token[e] === "-" ? plan.dah : plan.dit;
      events.push({ at, length });
      at += length + plan.intra;
    }
    at += plan.inter - plan.intra;
  }
  return { events, total: at };
}

/**
 * Play a Morse string. Returns a stop function.
 *
 * Created per playback and closed afterwards: an AudioContext left open holds
 * the audio device awake, which on a laptop in a field is a battery cost for
 * nothing.
 */
export function play(morse, { wpm = 20, effectiveWpm, pitch = 600, onDone } = {}) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return () => {};

  const ctx = new Ctx();
  const plan = timing(wpm, effectiveWpm);
  const { events, total } = schedule(morse, plan);
  const start = ctx.currentTime + 0.05;

  const gain = ctx.createGain();
  gain.gain.value = 0;
  gain.connect(ctx.destination);

  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.value = pitch;
  osc.connect(gain);
  osc.start(start);

  for (const event of events) {
    const on = start + event.at / 1000;
    const off = on + event.length / 1000;
    // Ramped, not switched: a square edge on a tone is a key click.
    gain.gain.setValueAtTime(0, on);
    gain.gain.linearRampToValueAtTime(0.25, on + RAMP_SECONDS);
    gain.gain.setValueAtTime(0.25, off - RAMP_SECONDS);
    gain.gain.linearRampToValueAtTime(0, off);
  }

  const endsAt = start + total / 1000 + 0.1;
  osc.stop(endsAt);

  let finished = false;
  const cleanup = () => {
    if (finished) return;
    finished = true;
    try {
      osc.stop();
    } catch {
      // Already stopped; the scheduled stop won the race.
    }
    ctx.close();
    if (onDone) onDone();
  };
  osc.onended = cleanup;

  return cleanup;
}

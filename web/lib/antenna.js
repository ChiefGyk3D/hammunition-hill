// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The browser half of src/hammunition_hill/antenna.py.
//
// The tables arrive as a snapshot; the arithmetic happens here, because a
// calculator that asked a server for the length of a dipole would be a
// calculator that stops working in a field. That is a second implementation,
// so a test runs this file under node against the same published tables and
// compares every answer to the Python one. Keep them in step.

/** Metres, from MHz. */
export function wavelengthM(freqMhz) {
  if (!(freqMhz > 0)) return NaN;
  return 299792458 / (freqMhz * 1e6);
}

/** The length to cut, in metres, for one entry of the published antenna table. */
export function elementLengthM(freqMhz, antenna, shortening) {
  const length = wavelengthM(freqMhz) * antenna.factor;
  return antenna.wire ? length * shortening : length;
}

/** Every antenna in the table at one frequency, metric and imperial. */
export function cutChart(freqMhz, reference) {
  return reference.antennas.map((entry) => {
    const metres = elementLengthM(freqMhz, entry, reference.wire_shortening);
    return {
      id: entry.id,
      name: entry.name,
      metres: round(metres, 3),
      feet: round(metres * reference.feet_per_metre, 2),
      note: entry.note || "",
    };
  });
}

// Python's round() is banker's rounding and JavaScript's toFixed is not, so
// comparing the two would fail on exact halves for no reason anyone cares
// about. This is Python's rule, written out, so the drift test compares
// arithmetic rather than tie-breaking conventions.
function round(value, digits) {
  if (!Number.isFinite(value)) return value;
  const scaled = value * 10 ** digits;
  const floor = Math.floor(scaled);
  const remainder = scaled - floor;
  let rounded;
  if (Math.abs(remainder - 0.5) < 1e-9) rounded = floor % 2 === 0 ? floor : floor + 1;
  else rounded = Math.round(scaled);
  return rounded / 10 ** digits;
}

/** Solve k1, k2 in loss = k1*sqrt(f) + k2*f from the two published points. */
export function lossConstants([[f1, l1], [f2, l2]]) {
  const r1 = Math.sqrt(f1);
  const r2 = Math.sqrt(f2);
  const determinant = r1 * f2 - r2 * f1;
  return [(l1 * f2 - l2 * f1) / determinant, (r1 * l2 - r2 * l1) / determinant];
}

/** Loss of a matched line, in dB. Nominal -- see the Python module. */
export function matchedLossDb(coax, freqMhz, lengthM, feetPerMetre) {
  const [k1, k2] = lossConstants(coax.at);
  const per100 = k1 * Math.sqrt(freqMhz) + k2 * freqMhz;
  return (per100 * (lengthM * feetPerMetre)) / 100;
}

/** How much cable makes a given electrical length -- a matching stub, say. */
export function electricalLengthM(freqMhz, coax, wavelengths = 0.25) {
  return wavelengthM(freqMhz) * wavelengths * coax.vf;
}

/** What an SWR reading means, in the units people care about. */
export function swrFigures(swr) {
  if (!(swr >= 1)) return null;
  if (!Number.isFinite(swr)) {
    return { swr: null, rho: 1, return_loss_db: 0, reflected_pct: 100, mismatch_loss_db: null };
  }
  const rho = (swr - 1) / (swr + 1);
  const reflected = rho * rho;
  return {
    swr: round(swr, 3),
    rho: round(rho, 4),
    return_loss_db: rho === 0 ? null : round(-20 * Math.log10(rho), 2),
    reflected_pct: round(reflected * 100, 2),
    mismatch_loss_db: round(-10 * Math.log10(1 - reflected), 3) + 0,
  };
}

/** Matched loss plus the extra a standing wave costs. */
export function totalLineLossDb(coax, freqMhz, lengthM, swr, feetPerMetre) {
  const matched = matchedLossDb(coax, freqMhz, lengthM, feetPerMetre);
  const rho = (swr - 1) / (swr + 1);
  if (rho === 0 || matched === 0) return matched;
  const a = 10 ** (-matched / 10);
  return -10 * Math.log10((a * (1 - rho * rho)) / (1 - a * a * rho * rho));
}

/** What reaches the antenna. The number that makes a loss figure mean something. */
export function powerAfterLoss(watts, lossDb) {
  return watts * 10 ** (-lossDb / 10);
}

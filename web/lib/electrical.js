// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// The browser half of src/hammunition_hill/electrical.py.
//
// Same contract as antenna.js: the constants arrive as a snapshot, the
// arithmetic happens here so the calculators work in a field with no network,
// and a drift test runs this file under node against the Python module and
// demands identical answers. Keep them in step.

/** Any two of volts/amps/ohms/watts -> all four, or null if not exactly two. */
export function ohm({ volts = null, amps = null, ohms = null, watts = null }) {
  const given = [volts, amps, ohms, watts].filter((value) => value !== null).length;
  if (given !== 2) return null;
  if ([volts, amps, ohms, watts].some((value) => value !== null && value < 0)) return null;

  let v = volts, i = amps, r = ohms, p = watts;
  if (v !== null && i !== null) {
    r = i ? v / i : Infinity;
    p = v * i;
  } else if (v !== null && r !== null) {
    if (r === 0) return null;
    i = v / r;
    p = v * i;
  } else if (v !== null && p !== null) {
    i = v ? p / v : 0;
    r = i ? v / i : Infinity;
  } else if (i !== null && r !== null) {
    v = i * r;
    p = v * i;
  } else if (i !== null && p !== null) {
    if (i === 0 && p > 0) return null;
    v = i ? p / i : 0;
    r = i ? v / i : Infinity;
  } else if (r !== null && p !== null) {
    i = r ? Math.sqrt(p / r) : Infinity;
    v = Math.sqrt(p * r);
  }
  return { volts: v, amps: i, ohms: r, watts: p };
}

/** dB from a power ratio; NaN when the ratio has no logarithm. */
export function dbFromPowerRatio(ratio) {
  if (!(ratio > 0)) return NaN;
  return 10 * Math.log10(ratio);
}

export function powerRatioFromDb(db) {
  return 10 ** (db / 10);
}

export function dbBetweenWatts(referenceW, comparedW) {
  if (!(referenceW > 0) || !(comparedW > 0)) return NaN;
  return dbFromPowerRatio(comparedW / referenceW);
}

/** Drop over a two-conductor run; the round trip is the resistance. */
export function voltageDrop(awgTable, feetPerMetre, awg, oneWayM, amps, supplyVolts) {
  const perKft = awgTable[String(awg)];
  if (perKft === undefined) return null;
  if (oneWayM < 0 || amps < 0 || !(supplyVolts > 0)) return null;
  const roundTripFt = 2 * oneWayM * feetPerMetre;
  const resistance = (perKft * roundTripFt) / 1000;
  const drop = resistance * amps;
  return {
    ohms: resistance,
    drop_volts: drop,
    at_load_volts: supplyVolts - drop,
    percent: (100 * drop) / supplyVolts,
  };
}

/** Hours a battery carries a load, honestly derated by chemistry. */
export function batteryRuntime(usableTable, ampHours, chemistry, loadWatts, volts) {
  const usable = usableTable[chemistry];
  if (usable === undefined) return null;
  if (!(ampHours > 0) || !(volts > 0) || !(loadWatts > 0)) return null;
  const usableWh = ampHours * volts * usable;
  return {
    usable_watt_hours: usableWh,
    hours: usableWh / loadWatts,
    usable_fraction: usable,
  };
}

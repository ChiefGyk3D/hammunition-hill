// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Where the moon is, and when either body crosses the horizon.
//
// solar.js draws the greyline. This is the pair of questions it does not
// answer: where is the moon (the EME window, and the only reason a 2 m
// operator watches a clock), and what time do the sun and moon rise and set
// here (the greyline times an HF operator plans around).
//
// The Python twin is src/hammunition_hill/ephemeris.py, and
// tests/test_ephemeris_drift.py runs this file under node against it and
// demands the same numbers. Two implementations of a published algorithm with
// a test pinning them together is cheaper here than a build step, which is the
// same trade solar.js/solar.py already made.
//
// Accuracy, said out loud: the lunar series is the Astronomical Almanac's
// low-precision one, good to about 0.3 degrees and 0.003 Earth radii. That is
// half a moon-width -- fine for "is it up, roughly where, how long left", and
// not fine for pointing a dish open-loop. The panel says so rather than
// letting four decimal places imply otherwise.

import { subsolarPoint, solarElevation } from "./solar.js";

const DEG = Math.PI / 180;

export const SYNODIC_MONTH_DAYS = 29.530588853;
export const EARTH_RADIUS_KM = 6378.14;

/** Geometric altitude of a body's centre when its upper limb is on the horizon. */
export const HORIZON_ALTITUDE = -0.833;

/** Civil twilight: light enough to work outside without a lamp. */
export const CIVIL_TWILIGHT_ALTITUDE = -6.0;

const norm360 = (d) => ((d % 360) + 360) % 360;

function daysSinceJ2000(date) {
  return date.getTime() / 86400000 + 2440587.5 - 2451545.0;
}

function gmstDegrees(n) {
  const hours = (18.697374558 + 24.06570982441908 * n) % 24;
  return ((hours + 24) % 24) * 15;
}

const PHASE_NAMES = [
  [0, "New"],
  [45, "Waxing crescent"],
  [90, "First quarter"],
  [135, "Waxing gibbous"],
  [180, "Full"],
  [225, "Waning gibbous"],
  [270, "Last quarter"],
  [315, "Waning crescent"],
];

// Within this many degrees of a quarter, call it by that name. Twelve degrees
// is about a day either side, which is how an almanac prints it.
const PHASE_EXACT_WINDOW = 12;

/** Conventional phase name, and whether the moon is waxing. */
export function phaseName(elongation) {
  const angle = norm360(elongation);
  const waxing = angle < 180;
  const shortWay = (centre) => Math.abs((((angle - centre + 180) % 360) + 360) % 360 - 180);
  for (const [centre, name] of PHASE_NAMES) {
    if (centre % 90 === 0 && shortWay(centre) <= PHASE_EXACT_WINDOW) return { name, waxing };
  }
  for (const [centre, name] of PHASE_NAMES) {
    if (centre % 90 !== 0 && shortWay(centre) < 45) return { name, waxing };
  }
  return { name: "New", waxing };
}

/**
 * Geocentric lunar position and phase.
 *
 * Seven periodic terms in longitude, four in latitude, four in parallax.
 * Truncating there is deliberate: the next terms are tenths of a degree and
 * this feeds a panel whose smallest readable division is a degree.
 */
export function moonPosition(date = new Date()) {
  const n = daysSinceJ2000(date);
  const t = n / 36525;
  const sin = (d) => Math.sin(d * DEG);
  const cos = (d) => Math.cos(d * DEG);

  let eclipticLon =
    218.32 + 481267.881 * t +
    6.29 * sin(135.0 + 477198.87 * t) -
    1.27 * sin(259.2 - 413335.36 * t) +
    0.66 * sin(235.7 + 890534.22 * t) +
    0.21 * sin(269.9 + 954397.74 * t) -
    0.19 * sin(357.5 + 35999.05 * t) -
    0.11 * sin(186.6 + 966404.03 * t);

  const eclipticLat =
    5.13 * sin(93.3 + 483202.02 * t) +
    0.28 * sin(228.2 + 960400.89 * t) -
    0.28 * sin(318.3 + 6003.15 * t) -
    0.17 * sin(217.6 - 407332.21 * t);

  const parallax =
    0.9508 +
    0.0518 * cos(135.0 + 477198.87 * t) +
    0.0095 * cos(259.2 - 413335.36 * t) +
    0.0078 * cos(235.7 + 890534.22 * t) +
    0.0028 * cos(269.9 + 954397.74 * t);

  eclipticLon = norm360(eclipticLon);
  const obliquity = (23.439281 - 0.0000004 * n) * DEG;

  const lam = eclipticLon * DEG;
  const beta = eclipticLat * DEG;
  const x = Math.cos(beta) * Math.cos(lam);
  const y =
    Math.cos(obliquity) * Math.cos(beta) * Math.sin(lam) -
    Math.sin(obliquity) * Math.sin(beta);
  const z =
    Math.sin(obliquity) * Math.cos(beta) * Math.sin(lam) +
    Math.cos(obliquity) * Math.sin(beta);

  const rightAscension = Math.atan2(y, x) / DEG;
  const declination = Math.asin(Math.max(-1, Math.min(1, z))) / DEG;

  let lon = rightAscension - gmstDegrees(n);
  lon = ((((lon + 180) % 360) + 360) % 360) - 180;

  const distanceKm = EARTH_RADIUS_KM / Math.sin(parallax * DEG);

  // Elongation against the sun's ecliptic longitude -- the same mean-plus-two
  // terms series solar.js uses for the subsolar point.
  const sunMeanLon = 280.46 + 0.9856474 * n;
  const sunAnomaly = (357.528 + 0.9856003 * n) * DEG;
  const sunLon =
    sunMeanLon + 1.915 * Math.sin(sunAnomaly) + 0.02 * Math.sin(2 * sunAnomaly);
  const elongation = norm360(eclipticLon - sunLon);

  // Illuminated fraction from the phase angle at the moon rather than from the
  // elongation directly: the sun is very far away but not infinitely so, and
  // doing it properly costs one atan2.
  const sunDistanceEarthRadii = 23454.8; // 1 AU
  const psi = elongation * DEG;
  const phaseAngle = Math.atan2(
    sunDistanceEarthRadii * Math.sin(psi),
    distanceKm / EARTH_RADIUS_KM - sunDistanceEarthRadii * Math.cos(psi),
  );
  const illumination = (1 + Math.cos(phaseAngle)) / 2;

  const { name, waxing } = phaseName(elongation);

  return {
    lat: declination,
    lon,
    distanceKm,
    parallaxDeg: parallax,
    eclipticLon,
    illumination,
    ageDays: (elongation / 360) * SYNODIC_MONTH_DAYS,
    elongation,
    phaseName: name,
    waxing,
  };
}

/**
 * Elevation and azimuth of a body directly over (subLat, subLon).
 *
 * Treats the body as infinitely distant: exactly right for the sun, and wrong
 * for the moon by up to the lunar parallax. moonLookAngles fixes that.
 */
export function lookAngles(lat, lon, subLat, subLon) {
  const a = lat * DEG;
  const b = subLat * DEG;
  const delta = (subLon - lon) * DEG;

  const cosC = Math.sin(a) * Math.sin(b) + Math.cos(a) * Math.cos(b) * Math.cos(delta);
  const elevation = Math.asin(Math.max(-1, Math.min(1, cosC))) / DEG;
  const azimuth =
    Math.atan2(
      Math.sin(delta) * Math.cos(b),
      Math.cos(a) * Math.sin(b) - Math.sin(a) * Math.cos(b) * Math.cos(delta),
    ) / DEG;

  return { elevation, azimuth: norm360(azimuth) };
}

/**
 * Topocentric look angles for the moon.
 *
 * The parallax term is the reason this is its own function. An observer on the
 * surface sees the moon up to a degree lower than one at the centre of the
 * Earth would -- more than the moon is wide, and enough to move moonrise by
 * minutes.
 */
export function moonLookAngles(lat, lon, moon) {
  const geocentric = lookAngles(lat, lon, moon.lat, moon.lon);
  return {
    elevation: geocentric.elevation - moon.parallaxDeg * Math.cos(geocentric.elevation * DEG),
    azimuth: geocentric.azimuth,
  };
}

export function sunElevationAt(lat, lon, date) {
  return solarElevation(lat, lon, subsolarPoint(date));
}

export function moonElevationAt(lat, lon, date) {
  return moonLookAngles(lat, lon, moonPosition(date)).elevation;
}

function bisectCrossing(elevationAt, lat, lon, before, after, altitude) {
  let lo = before.getTime();
  let hi = after.getTime();
  for (let i = 0; i < 16; i += 1) {
    const middle = lo + (hi - lo) / 2;
    const a = elevationAt(lat, lon, new Date(lo)) - altitude;
    const b = elevationAt(lat, lon, new Date(middle)) - altitude;
    if (a * b <= 0) hi = middle;
    else lo = middle;
  }
  return new Date(lo + (hi - lo) / 2);
}

function refineTransit(elevationAt, lat, lon, near, stepMs) {
  let low = near.getTime() - stepMs;
  let high = near.getTime() + stepMs;
  for (let i = 0; i < 24; i += 1) {
    const third = (high - low) / 3;
    const a = low + third;
    const b = high - third;
    if (elevationAt(lat, lon, new Date(a)) < elevationAt(lat, lon, new Date(b))) low = a;
    else high = b;
  }
  return new Date(low + (high - low) / 2);
}

/**
 * Rise, set and transit for one body over a window.
 *
 * Sampled and bracketed rather than solved in closed form. The closed form
 * exists for the sun and is a nuisance for the moon, whose declination moves
 * fast enough that holding it fixed across a day puts rise times minutes out.
 *
 * alwaysUp / alwaysDown are not a fallback: above the Arctic circle they are
 * the right answer for months at a time, and a panel that shows a blank
 * instead is the one that looks broken.
 */
export function horizonEvents(
  elevationAt,
  lat,
  lon,
  start,
  { hours = 24, altitude = HORIZON_ALTITUDE, stepMinutes = 10 } = {},
) {
  const stepMs = stepMinutes * 60000;
  const steps = Math.round((hours * 60) / stepMinutes);

  let rise = null;
  let setting = null;
  let transit = start;
  let best = -999;

  let previousTime = start;
  let previous = elevationAt(lat, lon, start);
  let aboveEver = previous > altitude;
  let belowEver = previous <= altitude;
  if (previous > best) {
    best = previous;
    transit = start;
  }

  for (let index = 1; index <= steps; index += 1) {
    const moment = new Date(start.getTime() + stepMs * index);
    const elevation = elevationAt(lat, lon, moment);
    aboveEver = aboveEver || elevation > altitude;
    belowEver = belowEver || elevation <= altitude;

    if (elevation > best) {
      best = elevation;
      transit = moment;
    }
    if (rise === null && previous <= altitude && altitude < elevation) {
      rise = bisectCrossing(elevationAt, lat, lon, previousTime, moment, altitude);
    } else if (setting === null && previous > altitude && altitude >= elevation) {
      setting = bisectCrossing(elevationAt, lat, lon, previousTime, moment, altitude);
    }
    previousTime = moment;
    previous = elevation;
  }

  transit = refineTransit(elevationAt, lat, lon, transit, stepMs);
  best = elevationAt(lat, lon, transit);

  return {
    rise,
    set: setting,
    transit,
    transitElevation: best,
    alwaysUp: !belowEver,
    alwaysDown: !aboveEver,
  };
}

export function sunEvents(lat, lon, start, options) {
  return horizonEvents(sunElevationAt, lat, lon, start, options);
}

export function moonEvents(lat, lon, start, options) {
  return horizonEvents(moonElevationAt, lat, lon, start, options);
}

/**
 * Civil twilight edges: the dawn and dusk either side of the greyline.
 *
 * The low bands do their trick in the band around sunrise and sunset rather
 * than at the instant of it, so the useful number is when the sun is six
 * degrees down, not zero.
 */
export function greylineWindow(lat, lon, start, options = {}) {
  return horizonEvents(sunElevationAt, lat, lon, start, {
    altitude: CIVIL_TWILIGHT_ALTITUDE,
    ...options,
  });
}

/**
 * Where a fixed celestial coordinate is overhead, right now.
 *
 * Meteor shower radiants are published as a right ascension and a declination
 * and do not move appreciably over the days a shower runs, so turning one into
 * a look angle is a single sidereal-time subtraction. That is what makes the
 * meteor panel tier 0: the radiants ship as data and the rest is the clock.
 */
export function celestialSubpoint(rightAscension, declination, date = new Date()) {
  const n = daysSinceJ2000(date);
  let lon = rightAscension - gmstDegrees(n);
  lon = ((((lon + 180) % 360) + 360) % 360) - 180;
  return { lat: declination, lon };
}

/** The sublunar point, in the shape the greyline code uses for the sun. */
export function sublunarPoint(date = new Date()) {
  const moon = moonPosition(date);
  return { lat: moon.lat, lon: moon.lon };
}

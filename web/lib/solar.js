// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Where the sun is, which is what draws the greyline.
//
// The terminator is the great circle 90 degrees from the subsolar point, so
// once you know where the sun is directly overhead the rest is geometry. This
// is the standard low-precision solar position algorithm, good to about a
// hundredth of a degree -- far better than a few hundred pixels of globe can
// show, and it runs in the browser with no data and no network.

const DEG = Math.PI / 180;
const TAU = Math.PI * 2;

/** Julian centuries-free day number since J2000.0. */
function daysSinceJ2000(date) {
  return date.getTime() / 86400000 + 2440587.5 - 2451545.0;
}

/**
 * The point on Earth where the sun is directly overhead, right now.
 * @returns {{lat: number, lon: number}} degrees
 */
export function subsolarPoint(date = new Date()) {
  const n = daysSinceJ2000(date);

  // Mean longitude and mean anomaly of the sun.
  const meanLon = (280.46 + 0.9856474 * n) * DEG;
  const meanAnomaly = (357.528 + 0.9856003 * n) * DEG;

  // Ecliptic longitude, with the two largest periodic corrections.
  const eclipticLon =
    meanLon + 1.915 * DEG * Math.sin(meanAnomaly) + 0.02 * DEG * Math.sin(2 * meanAnomaly);

  const obliquity = (23.439 - 0.0000004 * n) * DEG;

  const declination = Math.asin(Math.sin(obliquity) * Math.sin(eclipticLon));
  const rightAscension = Math.atan2(
    Math.cos(obliquity) * Math.sin(eclipticLon),
    Math.cos(eclipticLon),
  );

  // Greenwich mean sidereal time tells us which meridian faces the sun.
  const gmstHours = (18.697374558 + 24.06570982441908 * n) % 24;
  const gmst = ((gmstHours + 24) % 24) * 15 * DEG;

  let lon = (rightAscension - gmst) / DEG;
  lon = ((((lon + 180) % 360) + 360) % 360) - 180;

  return { lat: declination / DEG, lon };
}

/**
 * Points on the terminator: the circle 90 degrees from the subsolar point.
 * @returns {Array<{lat: number, lon: number}>}
 */
export function terminatorRing(subsolar, steps = 360) {
  const lat1 = subsolar.lat * DEG;
  const lon1 = subsolar.lon * DEG;
  const d = Math.PI / 2; // a quarter turn away, by definition

  const ring = [];
  for (let i = 0; i <= steps; i += 1) {
    const bearing = (i / steps) * TAU;
    const lat = Math.asin(
      Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(bearing),
    );
    const lon =
      lon1 +
      Math.atan2(
        Math.sin(bearing) * Math.sin(d) * Math.cos(lat1),
        Math.cos(d) - Math.sin(lat1) * Math.sin(lat),
      );
    ring.push({ lat: lat / DEG, lon: (((lon / DEG + 540) % 360) - 180) });
  }
  return ring;
}

/** Solar elevation at a point, in degrees. Negative is night. */
export function solarElevation(lat, lon, subsolar) {
  const a = lat * DEG;
  const b = subsolar.lat * DEG;
  const dl = (lon - subsolar.lon) * DEG;
  const cosZenith = Math.sin(a) * Math.sin(b) + Math.cos(a) * Math.cos(b) * Math.cos(dl);
  return Math.asin(Math.max(-1, Math.min(1, cosZenith))) / DEG;
}

/** True when a point is in darkness. */
export function isNight(lat, lon, subsolar) {
  return solarElevation(lat, lon, subsolar) < 0;
}

/**
 * How close a point is to the greyline, as a 0..1 weight.
 *
 * The band either side of sunrise and sunset is where the low bands do
 * remarkable things, so it is worth showing as more than a hard edge.
 */
export function greylineWeight(lat, lon, subsolar, halfWidthDegrees = 6) {
  const elevation = Math.abs(solarElevation(lat, lon, subsolar));
  return elevation >= halfWidthDegrees ? 0 : 1 - elevation / halfWidthDegrees;
}

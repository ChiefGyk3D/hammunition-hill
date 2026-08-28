// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can see one at https://mozilla.org/MPL/2.0/.

// MINIMUF 3.5 in the browser: src/hammunition_hill/minimuf.py written twice.
//
// The Python copy is canonical -- its docstring carries the provenance (NOSC,
// 1978/79, a public-domain US Government algorithm) and its test file pins
// the physics. This copy exists because the path predictor panel is
// interactive: the operator types a grid square and expects a 24-hour chart
// now, not on the collector's next cycle. tests/test_muf_drift.py runs this
// file under node against the Python across a grid of paths, hours and flux
// values and demands the same numbers, so the two cannot quietly disagree.

const MIN_PATH_KM = 250.0;
const MAX_PATH_KM = 12000.0;
const EARTH_RADIUS_KM = 6371.0;
const FLUX_FLOOR = 65.0;

export { MAX_PATH_KM, MIN_PATH_KM };

export function sunspotsFromFlux(flux) {
  if (flux < FLUX_FLOOR) return 0.0;
  if (flux < 110.0) return 108.36 - 0.005896 * (flux - 200.6) ** 2;
  if (flux < 213.0) return 60.0 + 1.068 * (flux - 110.0);
  return 384.0 - 0.0011059 * (flux - 652.9) ** 2;
}

function clamp(value, low = -1.0, high = 1.0) {
  return Math.max(low, Math.min(high, value));
}

function mod(value, span) {
  return ((value % span) + span) % span;
}

function sign(value) {
  if (value > 0.0) return 1.0;
  if (value < 0.0) return -1.0;
  return 0.0;
}

const rad = (deg) => (deg * Math.PI) / 180.0;

/** Predicted MUF in MHz for the path, or null outside the model's envelope. */
export function pathMuf({ sfi, month, day, utcHour, lat1, lon1, lat2, lon2 }) {
  const la1 = rad(clamp(lat1, -89.9, 89.9));
  const la2 = rad(clamp(lat2, -89.9, 89.9));
  const lo1 = rad(mod(-lon1, 360.0));
  const lo2 = rad(mod(-lon2, 360.0));

  const cosDist = clamp(
    Math.sin(la1) * Math.sin(la2) + Math.cos(la1) * Math.cos(la2) * Math.cos(lo2 - lo1),
  );
  const dist = Math.acos(cosDist);
  const km = dist * EARTH_RADIUS_KM;
  if (km < MIN_PATH_KM || km > MAX_PATH_KM) return null;

  const ssn = sunspotsFromFlux(Math.max(sfi, 0.0));

  const hops = Math.max(1.0, 1.59 * dist);
  const halfHop = clamp((2.5 * dist) / hops, -1.0, Math.PI / 2.0);
  const sinHalf = Math.sin(halfHop);
  const m9 = 1.0 + 2.5 * sinHalf * Math.sqrt(sinHalf);

  const y1 = 0.0172 * (10.0 + (month - 1) * 30.4 + day);
  const declination = 0.409 * Math.cos(y1);

  const azimuthCos =
    (Math.sin(la1) - Math.sin(la2) * Math.cos(dist)) / (Math.cos(la2) * Math.sin(dist));

  const fractions =
    hops <= 1.0 ? [0.5] : [1.0 / (2.0 * hops), 1.0 - 1.0 / (2.0 * hops)];

  let muf = 100.0;
  for (const fraction of fractions) {
    const along = dist * fraction;
    const sinLat = clamp(
      Math.sin(la2) * Math.cos(along) + Math.cos(la2) * Math.sin(along) * azimuthCos,
    );
    const pointLat = Math.asin(sinLat);
    const cosDlon = clamp(
      (Math.cos(along) - sinLat * Math.sin(la2)) /
        (Math.cos(la2) * Math.sqrt(1.0 - sinLat * sinLat)),
    );
    let pointLon = lo2 + Math.sign(Math.sin(lo1 - lo2) || 1) * Math.acos(cosDlon);
    pointLon = mod(pointLon, 2.0 * Math.PI);

    const noonUtc = mod(
      3.82 * pointLon + 12.0 + 0.13 * (Math.sin(y1) + 1.2 * Math.sin(2.0 * y1)),
      24.0,
    );

    let daylightHours = 0.0;
    let illumination = 0.0;
    if (Math.cos(pointLat + declination) > -0.26) {
      const ratio =
        (-0.26 + Math.sin(declination) * sinLat) /
        (Math.cos(declination) * Math.cos(pointLat) + 0.001);
      daylightHours =
        12.0 - Math.atan(ratio / Math.sqrt(Math.abs(1.0 - ratio * ratio))) * 7.639437;
      const sunrise = mod(noonUtc - daylightHours / 2.0, 24.0);
      const sunset = mod(noonUtc + daylightHours / 2.0, 24.0);

      const peak = Math.abs(Math.cos(pointLat + declination));
      const tau = Math.max(0.1, 9.7 * peak ** 9.6);
      const g8 = (Math.PI * tau) / daylightHours;

      const isNight =
        (sunset < sunrise && (utcHour - sunset) * (sunrise - utcHour) > 0.0) ||
        (sunset >= sunrise && (utcHour - sunrise) * (sunset - utcHour) <= 0.0);

      if (isNight) {
        const hour = sunset > utcHour ? utcHour + 24.0 : utcHour;
        illumination =
          (peak * (g8 * (Math.exp(-daylightHours / tau) + 1.0)) *
            Math.exp((sunset - hour) / 2.0)) /
          (1.0 + g8 * g8);
      } else {
        const hour = sunrise > utcHour ? utcHour + 24.0 : utcHour;
        const phase = (Math.PI * (hour - sunrise)) / daylightHours;
        illumination =
          (peak *
            (Math.sin(phase) + g8 * (Math.exp((sunrise - hour) / tau) - Math.cos(phase)))) /
          (1.0 + g8 * g8);
        const overnightFloor =
          (peak * (g8 * (Math.exp(-daylightHours / tau) + 1.0)) *
            Math.exp((daylightHours - 24.0) / 2.0)) /
          (1.0 + g8 * g8);
        illumination = Math.max(illumination, overnightFloor);
      }
    }

    let pointMuf =
      (1.0 + ssn / 250.0) * m9 * Math.sqrt(6.0 + 58.0 * Math.sqrt(Math.max(0.0, illumination)));
    pointMuf *= 1.0 - 0.1 * Math.exp((daylightHours - 24.0) / 3.0);
    pointMuf *= 1.0 + 0.1 * (1.0 - sign(lat1) * sign(lat2));
    pointMuf *= 1.0 - 0.1 * (1.0 + sign(Math.abs(Math.sin(pointLat)) - Math.cos(pointLat)));

    muf = Math.min(muf, pointMuf);
  }

  return muf;
}

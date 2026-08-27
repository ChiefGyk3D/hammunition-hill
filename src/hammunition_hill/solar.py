# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Where the sun is, in Python.

The browser already has this in ``web/lib/solar.js`` -- it draws the greyline.
The collector needs it too, because the propagation model is computed there and
its single most important input is *how high the sun is above the operator's
own station*, not what hour it happens to be in Greenwich.

This is the standard low-precision solar position algorithm, good to about a
hundredth of a degree. That is far more than enough: the ionospheric models
downstream are empirical approximations whose error is measured in megahertz,
so refining the sun's position past this point would be polishing the one part
that was never the problem.

Deliberately duplicated rather than shared. The browser copy has no build step
and no imports by design; making both sides read one file would mean either
shipping a Python-to-JS build or serving the maths as data. Two ~40-line
implementations of a published algorithm, with tests that pin them to the same
reference values, is the cheaper trade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

# Unix epoch as a Julian day number, minus the J2000.0 epoch.
_JD_UNIX_EPOCH = 2440587.5
_JD_J2000 = 2451545.0
_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class Subsolar:
    """The point on Earth where the sun is directly overhead."""

    lat: float
    lon: float


def days_since_j2000(moment: datetime) -> float:
    """Days since J2000.0. Naive datetimes are assumed UTC, not local."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp() / _SECONDS_PER_DAY + _JD_UNIX_EPOCH - _JD_J2000


def subsolar_point(moment: datetime | None = None) -> Subsolar:
    """Where the sun is overhead right now."""
    n = days_since_j2000(moment or datetime.now(UTC))

    mean_lon = math.radians(280.46 + 0.9856474 * n)
    mean_anomaly = math.radians(357.528 + 0.9856003 * n)

    # Ecliptic longitude, with the two largest periodic corrections.
    ecliptic_lon = (
        mean_lon
        + math.radians(1.915) * math.sin(mean_anomaly)
        + math.radians(0.020) * math.sin(2 * mean_anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * n)

    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_lon))
    right_ascension = math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_lon), math.cos(ecliptic_lon)
    )

    # Greenwich mean sidereal time says which meridian is facing the sun.
    gmst_hours = (18.697374558 + 24.06570982441908 * n) % 24
    gmst = math.radians(((gmst_hours + 24) % 24) * 15)

    lon = math.degrees(right_ascension - gmst)
    lon = ((lon + 180) % 360 + 360) % 360 - 180

    return Subsolar(lat=math.degrees(declination), lon=lon)


def solar_elevation(lat: float, lon: float, subsolar: Subsolar) -> float:
    """Sun's angle above the horizon at a point, in degrees. Negative is night."""
    a = math.radians(lat)
    b = math.radians(subsolar.lat)
    delta_lon = math.radians(lon - subsolar.lon)
    cos_zenith = math.sin(a) * math.sin(b) + math.cos(a) * math.cos(b) * math.cos(delta_lon)
    return math.degrees(math.asin(max(-1.0, min(1.0, cos_zenith))))


def solar_zenith(lat: float, lon: float, subsolar: Subsolar) -> float:
    """Angle from straight up, in degrees. 0 is overhead, 90 is the horizon.

    This is the quantity the ionospheric models actually want. Absorption
    scales with the cosine of it, which is why a solar-noon *proxy* built from
    the UTC hour is not good enough: it is exactly right on the Greenwich
    meridian and hours wrong everywhere else.
    """
    return 90.0 - solar_elevation(lat, lon, subsolar)


def is_night(lat: float, lon: float, subsolar: Subsolar) -> bool:
    return solar_elevation(lat, lon, subsolar) < 0.0

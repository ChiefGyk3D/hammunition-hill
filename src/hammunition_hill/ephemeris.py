# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Where the moon is, and when either body crosses the horizon.

``solar.py`` answers "where is the sun *now*", because the propagation model
needs the solar zenith at the operator's station. This module answers the two
questions a dashboard asks next and that one cannot:

* **Where is the moon?** Sublunar point, distance, illuminated fraction and
  phase -- the inputs to an EME window, and the reason a 2 m operator looks at
  a clock at all.
* **When does either body rise, set or transit here?** Sunrise and sunset are
  the greyline times an HF operator plans around; moonrise and moonset are the
  EME window's edges.

Deliberately duplicated in ``web/lib/ephemeris.js``, for the same reason
``solar.py`` is: the browser has no build step and no imports by design, and
two implementations pinned to each other by a drift test is cheaper than
shipping a transpiler. ``tests/test_ephemeris_drift.py`` is what keeps them
honest.

**Accuracy, stated rather than implied.** The lunar position is the
*Astronomical Almanac*'s low-precision series, which is good to roughly 0.3
degrees in right ascension and declination and about 0.003 Earth radii in
distance. That is half a moon-width, so it is fine for "is the moon up, where
do I point, how far through the window am I" and it is *not* fine for pointing
a 23 cm dish open-loop. The panel says so on its face rather than letting a
number that looks precise imply that it is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .solar import Subsolar, days_since_j2000, solar_elevation, subsolar_point

# Mean synodic month: new moon to new moon.
SYNODIC_MONTH_DAYS = 29.530588853

# Mean Earth radius, the unit the Almanac's lunar parallax is expressed in.
EARTH_RADIUS_KM = 6378.14

# Standard refraction allowance: the geometric altitude of the centre of a body
# whose upper limb is on the visible horizon. Used for both bodies here because
# the lunar elevation below is already corrected for parallax, which is the
# term that would otherwise dominate.
HORIZON_ALTITUDE = -0.833

# Sun below the horizon by this much is civil twilight's far edge -- the
# working definition of "light enough to work outside without a lamp", which is
# what a portable operator actually wants to know.
CIVIL_TWILIGHT_ALTITUDE = -6.0


@dataclass(frozen=True)
class Moon:
    """The moon's geocentric position and phase at one instant."""

    lat: float
    """Sublunar latitude, degrees. Equal to the geocentric declination."""

    lon: float
    """Sublunar longitude, degrees east."""

    distance_km: float
    parallax_deg: float
    """Horizontal parallax. Up to about a degree, which is why rise times move."""

    ecliptic_lon: float
    illumination: float
    """Fraction of the disc lit, 0 at new and 1 at full."""

    age_days: float
    """Days since the last new moon, from the sun-moon elongation."""

    elongation: float
    """Moon's ecliptic longitude minus the sun's, 0-360. 0 new, 180 full."""

    phase_name: str
    waxing: bool


@dataclass(frozen=True)
class Horizon:
    """Where a body is as seen from one place on the ground."""

    elevation: float
    azimuth: float
    """True bearing, degrees clockwise from north."""


@dataclass(frozen=True)
class Events:
    """Rise, set and transit for one body, one place, one day."""

    rise: datetime | None
    set: datetime | None
    transit: datetime | None
    transit_elevation: float
    always_up: bool
    always_down: bool


# The eight conventional phase names, by elongation. The quarters are the only
# ones that name an instant; the crescents and gibbous phases name the span
# between two of them, which is why the boundaries below are not all equal.
_PHASE_NAMES = (
    (0.0, "New"),
    (45.0, "Waxing crescent"),
    (90.0, "First quarter"),
    (135.0, "Waxing gibbous"),
    (180.0, "Full"),
    (225.0, "Waning gibbous"),
    (270.0, "Last quarter"),
    (315.0, "Waning crescent"),
)

# Half-width of the window, in degrees of elongation, within which a phase is
# called by its exact name rather than the span around it. 12 degrees is about
# a day either side, which matches how an almanac prints it.
_PHASE_EXACT_WINDOW = 12.0


def _norm360(degrees: float) -> float:
    return degrees % 360.0


def _gmst_degrees(n: float) -> float:
    """Greenwich mean sidereal time in degrees, from days since J2000."""
    hours = (18.697374558 + 24.06570982441908 * n) % 24
    return ((hours + 24) % 24) * 15


def phase_name(elongation: float) -> tuple[str, bool]:
    """Conventional phase name and whether the moon is waxing."""
    angle = _norm360(elongation)
    waxing = angle < 180.0
    for centre, name in _PHASE_NAMES:
        # 0 degrees is also 360; measure the short way round.
        delta = abs(((angle - centre + 180.0) % 360.0) - 180.0)
        if centre % 90 == 0 and delta <= _PHASE_EXACT_WINDOW:
            return name, waxing
    for centre, name in _PHASE_NAMES:
        if centre % 90 != 0 and abs(((angle - centre + 180.0) % 360.0) - 180.0) < 45.0:
            return name, waxing
    return "New", waxing


def moon_position(moment: datetime | None = None) -> Moon:
    """Geocentric lunar position and phase.

    The *Astronomical Almanac*'s low-precision series: seven periodic terms in
    longitude, four in latitude, four in parallax. Truncating there is a
    deliberate choice and not a shortcut -- the next terms are tenths of a
    degree, and this feeds a panel whose smallest readable division is a
    degree.
    """
    n = days_since_j2000(moment or datetime.now(UTC))
    t = n / 36525.0
    rad = math.radians

    # fmt: off
    ecliptic_lon = (
        218.32 + 481267.881 * t
        + 6.29 * math.sin(rad(135.0 + 477198.87 * t))
        - 1.27 * math.sin(rad(259.2 - 413335.36 * t))
        + 0.66 * math.sin(rad(235.7 + 890534.22 * t))
        + 0.21 * math.sin(rad(269.9 + 954397.74 * t))
        - 0.19 * math.sin(rad(357.5 + 35999.05 * t))
        - 0.11 * math.sin(rad(186.6 + 966404.03 * t))
    )
    ecliptic_lat = (
        5.13 * math.sin(rad(93.3 + 483202.02 * t))
        + 0.28 * math.sin(rad(228.2 + 960400.89 * t))
        - 0.28 * math.sin(rad(318.3 + 6003.15 * t))
        - 0.17 * math.sin(rad(217.6 - 407332.21 * t))
    )
    parallax = (
        0.9508
        + 0.0518 * math.cos(rad(135.0 + 477198.87 * t))
        + 0.0095 * math.cos(rad(259.2 - 413335.36 * t))
        + 0.0078 * math.cos(rad(235.7 + 890534.22 * t))
        + 0.0028 * math.cos(rad(269.9 + 954397.74 * t))
    )
    # fmt: on

    ecliptic_lon = _norm360(ecliptic_lon)
    obliquity = rad(23.439281 - 0.0000004 * n)

    lam = rad(ecliptic_lon)
    beta = rad(ecliptic_lat)
    x = math.cos(beta) * math.cos(lam)
    y = math.cos(obliquity) * math.cos(beta) * math.sin(lam) - math.sin(obliquity) * math.sin(beta)
    z = math.sin(obliquity) * math.cos(beta) * math.sin(lam) + math.cos(obliquity) * math.sin(beta)

    right_ascension = math.degrees(math.atan2(y, x))
    declination = math.degrees(math.asin(max(-1.0, min(1.0, z))))

    lon = right_ascension - _gmst_degrees(n)
    lon = ((lon + 180.0) % 360.0 + 360.0) % 360.0 - 180.0

    distance_km = EARTH_RADIUS_KM / math.sin(rad(parallax))

    # Elongation is measured in ecliptic longitude against the sun's, which is
    # what an almanac's phase column means. The sun's mean-plus-two-terms
    # longitude is the same series solar.py uses for the subsolar point.
    sun_mean_lon = 280.46 + 0.9856474 * n
    sun_anomaly = rad(357.528 + 0.9856003 * n)
    sun_lon = sun_mean_lon + 1.915 * math.sin(sun_anomaly) + 0.020 * math.sin(2 * sun_anomaly)
    elongation = _norm360(ecliptic_lon - sun_lon)

    # Illuminated fraction from the phase angle at the moon, not from the
    # elongation directly: the sun is very far away but not infinitely so, and
    # doing it properly costs one atan2.
    sun_distance_earth_radii = 23454.8  # 1 AU
    psi = rad(elongation)
    phase_angle = math.atan2(
        sun_distance_earth_radii * math.sin(psi),
        distance_km / EARTH_RADIUS_KM - sun_distance_earth_radii * math.cos(psi),
    )
    illumination = (1.0 + math.cos(phase_angle)) / 2.0

    name, waxing = phase_name(elongation)

    return Moon(
        lat=declination,
        lon=lon,
        distance_km=distance_km,
        parallax_deg=parallax,
        ecliptic_lon=ecliptic_lon,
        illumination=illumination,
        age_days=elongation / 360.0 * SYNODIC_MONTH_DAYS,
        elongation=elongation,
        phase_name=name,
        waxing=waxing,
    )


def look_angles(lat: float, lon: float, sub_lat: float, sub_lon: float) -> Horizon:
    """Elevation and azimuth of a body directly over ``(sub_lat, sub_lon)``.

    Treats the body as infinitely distant, which is exactly right for the sun
    and wrong for the moon by up to the lunar parallax. ``moon_look_angles``
    below applies that correction; nothing else needs it.
    """
    a = math.radians(lat)
    b = math.radians(sub_lat)
    delta = math.radians(sub_lon - lon)

    cos_c = math.sin(a) * math.sin(b) + math.cos(a) * math.cos(b) * math.cos(delta)
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, cos_c))))

    azimuth = math.degrees(
        math.atan2(
            math.sin(delta) * math.cos(b),
            math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b) * math.cos(delta),
        )
    )
    return Horizon(elevation=elevation, azimuth=_norm360(azimuth))


def moon_look_angles(lat: float, lon: float, moon: Moon) -> Horizon:
    """Topocentric look angles for the moon.

    The parallax correction is the whole reason this is a separate function.
    The moon is close enough that an observer on the surface sees it up to a
    degree lower than an observer at the centre of the Earth would -- which is
    more than the width of the moon, and enough to move moonrise by minutes.
    """
    geocentric = look_angles(lat, lon, moon.lat, moon.lon)
    elevation = geocentric.elevation - moon.parallax_deg * math.cos(
        math.radians(geocentric.elevation)
    )
    return Horizon(elevation=elevation, azimuth=geocentric.azimuth)


def sun_elevation_at(lat: float, lon: float, moment: datetime) -> float:
    return solar_elevation(lat, lon, subsolar_point(moment))


def moon_elevation_at(lat: float, lon: float, moment: datetime) -> float:
    return moon_look_angles(lat, lon, moon_position(moment)).elevation


def _bisect_crossing(
    elevation_at,
    lat: float,
    lon: float,
    before: datetime,
    after: datetime,
    altitude: float,
) -> datetime:
    """Narrow a bracketed horizon crossing to the second.

    Twenty halvings of a ten-minute bracket is under a millisecond of
    resolution, which is far past what the underlying position is good for.
    Sixteen gets to under a hundredth of a second and is where this stops,
    because the honest error bar is a minute or two either way.
    """
    for _ in range(16):
        middle = before + (after - before) / 2
        if (elevation_at(lat, lon, before) - altitude) * (
            elevation_at(lat, lon, middle) - altitude
        ) <= 0:
            after = middle
        else:
            before = middle
    return before + (after - before) / 2


def horizon_events(
    elevation_at,
    lat: float,
    lon: float,
    start: datetime,
    hours: float = 24.0,
    altitude: float = HORIZON_ALTITUDE,
    step_minutes: float = 10.0,
) -> Events:
    """Rise, set and transit for one body over a window.

    Sampled and bracketed rather than solved. The closed-form solution exists
    for the sun and is a nuisance for the moon, whose declination moves fast
    enough that treating it as fixed across the day puts rise times minutes
    out. One sampler that is correct for both, including at latitudes where
    the answer is "it never rises", is worth the arithmetic.

    The ``always_up`` / ``always_down`` pair is not a fallback. Above the
    Arctic circle it is the *right answer* for months at a time, and a panel
    that shows a blank instead is the one that looks broken.
    """
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)

    step = timedelta(minutes=step_minutes)
    steps = int(hours * 60 / step_minutes)

    rise: datetime | None = None
    setting: datetime | None = None
    transit: datetime | None = None
    best = -999.0

    previous_time = start
    previous = elevation_at(lat, lon, start)
    above_ever = previous > altitude
    below_ever = previous <= altitude
    if previous > best:
        best, transit = previous, start

    for index in range(1, steps + 1):
        moment = start + step * index
        elevation = elevation_at(lat, lon, moment)
        above_ever = above_ever or elevation > altitude
        below_ever = below_ever or elevation <= altitude

        if elevation > best:
            best, transit = elevation, moment

        if rise is None and previous <= altitude < elevation:
            rise = _bisect_crossing(elevation_at, lat, lon, previous_time, moment, altitude)
        elif setting is None and previous > altitude >= elevation:
            setting = _bisect_crossing(elevation_at, lat, lon, previous_time, moment, altitude)

        previous_time, previous = moment, elevation

    # Refine the transit: the coarse sample lands within a step of the peak,
    # and a golden-section squeeze on that bracket gets it to the second
    # without another pass over the whole window.
    if transit is not None:
        transit = _refine_transit(elevation_at, lat, lon, transit, step)
        best = elevation_at(lat, lon, transit)

    return Events(
        rise=rise,
        set=setting,
        transit=transit,
        transit_elevation=best,
        always_up=not below_ever,
        always_down=not above_ever,
    )


def _refine_transit(elevation_at, lat: float, lon: float, near: datetime, step: timedelta):
    low, high = near - step, near + step
    for _ in range(24):
        third = (high - low) / 3
        a, b = low + third, high - third
        if elevation_at(lat, lon, a) < elevation_at(lat, lon, b):
            low = a
        else:
            high = b
    return low + (high - low) / 2


def sun_events(lat: float, lon: float, start: datetime, **kwargs) -> Events:
    return horizon_events(sun_elevation_at, lat, lon, start, **kwargs)


def moon_events(lat: float, lon: float, start: datetime, **kwargs) -> Events:
    return horizon_events(moon_elevation_at, lat, lon, start, **kwargs)


def greyline_window(lat: float, lon: float, start: datetime, **kwargs) -> Events:
    """Civil twilight edges: the dawn and dusk either side of the greyline.

    The low bands do their trick in the band around sunrise and sunset rather
    than at the instant of it, so the useful number is when the sun is six
    degrees down, not zero.
    """
    kwargs.setdefault("altitude", CIVIL_TWILIGHT_ALTITUDE)
    return horizon_events(sun_elevation_at, lat, lon, start, **kwargs)


def celestial_subpoint(
    right_ascension: float, declination: float, moment: datetime | None = None
) -> Subsolar:
    """Where a fixed celestial coordinate is overhead, right now.

    Meteor shower radiants are published as a right ascension and a declination
    and do not move appreciably over the days a shower is active, so turning
    one into a look angle is a single sidereal-time subtraction. That is the
    whole reason the meteor panel is tier 0: the radiants ship as data and the
    rest is the clock.
    """
    n = days_since_j2000(moment or datetime.now(UTC))
    lon = right_ascension - _gmst_degrees(n)
    lon = ((lon + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
    return Subsolar(lat=declination, lon=lon)


def sublunar_point(moment: datetime | None = None) -> Subsolar:
    """The sublunar point in the same shape the greyline code uses for the sun."""
    moon = moon_position(moment)
    return Subsolar(lat=moon.lat, lon=moon.lon)

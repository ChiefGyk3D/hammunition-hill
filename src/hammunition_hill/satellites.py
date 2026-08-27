# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""When the satellites are up, and where to point.

Two-line elements come in as a tier 1 source; the passes are computed here from
the elements already on disk, which makes this a derived source in the same
sense as the propagation model: it adds no network of its own.

That split matters. A pass list is a function of the elements *and the clock*,
and the clock moves whether or not anybody fetched anything. Recomputing on a
timer from cached elements means the panel stays right through a WAN outage --
elements stay usable for days, and a set a week old still predicts a pass to
within a few seconds.

## Why SGP4 is a dependency and not code in this file

The orbit propagator is `sgp4`, an optional extra. It is the reference
implementation of Spacetrack Report #3 as revised in 2006 -- the model the
elements are *defined against*, since a TLE is not a state vector but a set of
constants fitted for one specific propagator. Reimplementing it would be five
hundred lines of dense orbital mechanics that could not be verified to the same
standard, and the failure mode of getting it subtly wrong is a pass list that
looks entirely plausible and is not there.

Everything around it -- element parsing and checksums, the sidereal rotation,
look angles, the pass search, Doppler -- is here, tested, and small.

## What is deliberately absent

No deep-space handling is *added* here (SGP4 itself switches to SDP4 above a
225-minute period, which is the right behaviour and nothing this module needs to
manage), no atmospheric refraction, and no polar motion in the TEME-to-ground
rotation. Refraction lifts a satellite on the horizon by about half a degree at
AOS and nothing at elevation; polar motion is under an arcsecond. Both are far
below the error in elements that are hours or days old, and pretending otherwise
would be precision this cannot support.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# WGS-84, the datum SGP4's output is expressed against.
EARTH_RADIUS_KM = 6378.137
EARTH_FLATTENING = 1.0 / 298.257223563

# How far above the horizon counts as a pass. Zero is the geometric horizon and
# nobody has one: trees, buildings and hills all sit above it. Five degrees is
# the conventional floor for a working pass.
DEFAULT_MIN_ELEVATION = 5.0

# The search walks the sky in steps and refines the crossings it finds. Thirty
# seconds cannot miss a LEO pass -- the shortest useful one is several minutes
# horizon to horizon -- and is cheap enough to run over a hundred satellites.
COARSE_STEP_SECONDS = 30
REFINE_ITERATIONS = 20

SPEED_OF_LIGHT_KM_S = 299792.458


class TleError(ValueError):
    """A set of elements that cannot be trusted."""


class PropagatorUnavailable(RuntimeError):
    """The optional sgp4 extra is not installed."""


@dataclass(frozen=True)
class Tle:
    """One satellite's elements, as they arrived."""

    name: str
    line1: str
    line2: str

    @property
    def catalog_number(self) -> int:
        return int(self.line1[2:7])


@dataclass
class Pass:
    """One appearance above the horizon, from one place."""

    name: str
    catalog_number: int
    rise: datetime
    peak: datetime
    set: datetime
    max_elevation: float
    rise_azimuth: float
    peak_azimuth: float
    set_azimuth: float

    @property
    def duration_seconds(self) -> float:
        return (self.set - self.rise).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "catalog_number": self.catalog_number,
            "rise": self.rise.isoformat().replace("+00:00", "Z"),
            "peak": self.peak.isoformat().replace("+00:00", "Z"),
            "set": self.set.isoformat().replace("+00:00", "Z"),
            "duration_seconds": round(self.duration_seconds),
            "max_elevation": round(self.max_elevation, 1),
            "rise_azimuth": round(self.rise_azimuth, 1),
            "peak_azimuth": round(self.peak_azimuth, 1),
            "set_azimuth": round(self.set_azimuth, 1),
        }


@dataclass
class Observer:
    """Where you are, in the terms the geometry needs."""

    lat: float
    lon: float
    alt_m: float = 0.0
    _ecef: tuple[float, float, float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._ecef = geodetic_to_ecef(self.lat, self.lon, self.alt_m)


# --- elements ---------------------------------------------------------------


def tle_checksum(line: str) -> int:
    """The modulo-10 sum every TLE line ends with.

    Digits count as themselves, a minus sign counts as one, everything else
    counts as nothing. It catches exactly one kind of problem -- a line that
    arrived corrupted -- which is worth catching, because SGP4 will happily
    propagate a mangled element set and produce a pass that is not there.
    """
    total = 0
    for char in line[:68]:
        if char.isdigit():
            total += int(char)
        elif char == "-":
            total += 1
    return total % 10


def validate_line(line: str, expected_number: int) -> None:
    if len(line) < 69:
        raise TleError(f"line {expected_number} is {len(line)} characters, expected at least 69")
    if line[0] != str(expected_number):
        raise TleError(f"line {expected_number} starts with {line[0]!r}")
    stated = line[68]
    if not stated.isdigit():
        raise TleError(f"line {expected_number} has no checksum digit")
    computed = tle_checksum(line)
    if int(stated) != computed:
        raise TleError(
            f"line {expected_number} checksum is {stated}, computed {computed} "
            "-- the elements arrived corrupted"
        )


def parse_tles(text: str, *, strict: bool = False) -> list[Tle]:
    """Parse a Celestrak-style three-line listing.

    One bad set in a file of a hundred should cost that satellite, not the
    whole panel, so a set that fails validation is skipped unless `strict`.
    Names are optional in the wild; a listing that begins directly with a `1 `
    line is still parsed, with the catalog number standing in for a name.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]

    found: list[Tle] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("1 ") and index + 1 < len(lines) and lines[index + 1].startswith("2 "):
            name, line1, line2 = "", lines[index], lines[index + 1]
            index += 2
        elif (
            index + 2 < len(lines)
            and lines[index + 1].startswith("1 ")
            and lines[index + 2].startswith("2 ")
        ):
            name, line1, line2 = line.strip(), lines[index + 1], lines[index + 2]
            index += 3
        else:
            index += 1
            continue

        try:
            validate_line(line1, 1)
            validate_line(line2, 2)
            if line1[2:7] != line2[2:7]:
                raise TleError(
                    f"the two lines name different satellites: {line1[2:7]} and {line2[2:7]}"
                )
        except TleError:
            if strict:
                raise
            continue

        found.append(Tle(name=name or f"CATALOG {line1[2:7].strip()}", line1=line1, line2=line2))
    return found


# --- geometry ---------------------------------------------------------------


def julian_date(moment: datetime) -> tuple[float, float]:
    """Split Julian date, the form SGP4 wants: whole days and the fraction."""
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    utc = moment.astimezone(UTC)
    year, month = utc.year, utc.month
    day = utc.day
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    jd = math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5
    fraction = (utc.hour * 3600 + utc.minute * 60 + utc.second + utc.microsecond / 1e6) / 86400.0
    return jd, fraction


def gmst_rad(jd: float, fraction: float) -> float:
    """Greenwich mean sidereal time, IAU 1982.

    The one rotation that turns an inertial position into a direction from a
    place on a turning Earth. Getting it wrong shifts every azimuth by a fixed
    amount and is invisible in any check that does not use a known direction --
    which is why the tests use the sub-satellite point, where the answer must
    be straight up.
    """
    tut = (jd - 2451545.0 + fraction) / 36525.0
    seconds = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * tut
        + 0.093104 * tut**2
        - 6.2e-6 * tut**3
    )
    return (math.radians(seconds / 240.0)) % (2 * math.pi)


def geodetic_to_ecef(lat: float, lon: float, alt_m: float = 0.0) -> tuple[float, float, float]:
    """A place on the ellipsoid, in Earth-fixed kilometres."""
    phi = math.radians(lat)
    lam = math.radians(lon)
    sin_phi = math.sin(phi)
    # Radius of curvature in the prime vertical.
    n = EARTH_RADIUS_KM / math.sqrt(1.0 - (2 * EARTH_FLATTENING - EARTH_FLATTENING**2) * sin_phi**2)
    alt_km = alt_m / 1000.0
    x = (n + alt_km) * math.cos(phi) * math.cos(lam)
    y = (n + alt_km) * math.cos(phi) * math.sin(lam)
    z = (n * (1.0 - EARTH_FLATTENING) ** 2 + alt_km) * sin_phi
    return x, y, z


def teme_to_ecef(
    position: tuple[float, float, float], jd: float, fraction: float
) -> tuple[float, float, float]:
    """Rotate an inertial position into Earth-fixed coordinates by sidereal time.

    Polar motion is ignored -- see the module docstring. It is under an
    arcsecond, and the elements are the error term here by orders of magnitude.
    """
    theta = gmst_rad(jd, fraction)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    x, y, z = position
    return x * cos_t + y * sin_t, -x * sin_t + y * cos_t, z


def look_angles(
    observer: Observer, satellite_ecef: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Azimuth, elevation and slant range from an observer to a point.

    Returns degrees, degrees and kilometres. Elevation is geometric: no
    refraction, which would lift a horizon pass by about half a degree.
    """
    ox, oy, oz = observer._ecef
    dx, dy, dz = (
        satellite_ecef[0] - ox,
        satellite_ecef[1] - oy,
        satellite_ecef[2] - oz,
    )

    phi = math.radians(observer.lat)
    lam = math.radians(observer.lon)
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    sin_lam, cos_lam = math.sin(lam), math.cos(lam)

    # Rotate the difference vector into the local horizon frame.
    south = sin_phi * cos_lam * dx + sin_phi * sin_lam * dy - cos_phi * dz
    east = -sin_lam * dx + cos_lam * dy
    up = cos_phi * cos_lam * dx + cos_phi * sin_lam * dy + sin_phi * dz

    slant = math.sqrt(dx * dx + dy * dy + dz * dz)
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, up / slant)))) if slant else 90.0
    azimuth = math.degrees(math.atan2(-east, south)) + 180.0
    return azimuth % 360.0, elevation, slant


# --- propagation ------------------------------------------------------------


def propagator_available() -> bool:
    """Whether the optional sgp4 extra is installed."""
    try:
        import sgp4.api  # noqa: F401
    except ImportError:
        return False
    return True


def _satrec(tle: Tle):
    try:
        from sgp4.api import Satrec
    except ImportError as exc:  # pragma: no cover - exercised via propagator_available
        raise PropagatorUnavailable(
            "satellite passes need the sgp4 extra: pip install 'hammunition-hill[satellites]'"
        ) from exc
    return Satrec.twoline2rv(tle.line1, tle.line2)


def position_at(tle: Tle, moment: datetime) -> tuple[float, float, float]:
    """Where the satellite is, in Earth-fixed kilometres."""
    jd, fraction = julian_date(moment)
    error, position, _velocity = _satrec(tle).sgp4(jd, fraction)
    if error:
        raise TleError(f"{tle.name}: sgp4 error {error} at {moment.isoformat()}")
    return teme_to_ecef(position, jd, fraction)


def observe(tle: Tle, observer: Observer, moment: datetime) -> tuple[float, float, float]:
    """Azimuth, elevation and range, right now."""
    return look_angles(observer, position_at(tle, moment))


def subsatellite_point(tle: Tle, moment: datetime) -> tuple[float, float, float]:
    """Latitude, longitude and altitude of the point directly beneath.

    Useful in itself, and the basis of the strongest test available here: from
    directly beneath, the satellite must be straight up.
    """
    x, y, z = position_at(tle, moment)
    lon = math.degrees(math.atan2(y, x))
    radius = math.sqrt(x * x + y * y)

    # Bowring's method, iterated. Converges in two passes for anything in orbit.
    e2 = 2 * EARTH_FLATTENING - EARTH_FLATTENING**2
    lat = math.atan2(z, radius)
    for _ in range(5):
        sin_lat = math.sin(lat)
        n = EARTH_RADIUS_KM / math.sqrt(1 - e2 * sin_lat**2)
        lat = math.atan2(z + e2 * n * sin_lat, radius)
    sin_lat = math.sin(lat)
    n = EARTH_RADIUS_KM / math.sqrt(1 - e2 * sin_lat**2)
    altitude = radius / math.cos(lat) - n if abs(math.cos(lat)) > 1e-9 else abs(z) - n * (1 - e2)
    return math.degrees(lat), ((lon + 180) % 360) - 180, altitude


def doppler_hz(tle: Tle, observer: Observer, moment: datetime, frequency_hz: float) -> float:
    """The shift on a given frequency, in Hz. Negative once the bird is receding.

    Range rate by difference rather than from the velocity vector: a one-second
    baseline is well inside the accuracy the elements support, and it means the
    number comes from the same geometry the display shows rather than a second
    path that could disagree with it.
    """
    before = observe(tle, observer, moment - timedelta(milliseconds=500))[2]
    after = observe(tle, observer, moment + timedelta(milliseconds=500))[2]
    range_rate = after - before  # km per second
    return -frequency_hz * range_rate / SPEED_OF_LIGHT_KM_S


# --- pass search ------------------------------------------------------------


def _elevation(tle: Tle, observer: Observer, moment: datetime) -> float:
    return observe(tle, observer, moment)[1]


def _refine_crossing(
    tle: Tle, observer: Observer, below: datetime, above: datetime, threshold: float
) -> datetime:
    """Bisect to the moment the satellite crosses the threshold.

    Twenty halvings of a thirty-second window land inside a millisecond, which
    is far finer than the elements justify and costs nothing.
    """
    for _ in range(REFINE_ITERATIONS):
        middle = below + (above - below) / 2
        if _elevation(tle, observer, middle) < threshold:
            below = middle
        else:
            above = middle
    return above


def passes(
    tle: Tle,
    observer: Observer,
    start: datetime,
    hours: float = 24.0,
    *,
    min_elevation: float = DEFAULT_MIN_ELEVATION,
    step_seconds: int = COARSE_STEP_SECONDS,
) -> list[Pass]:
    """Every pass above `min_elevation` in the window, in time order.

    A coarse walk finds the crossings and bisection refines them. The peak is
    then found by walking the arc at the coarse step and bisecting around the
    best sample, which is enough: near the maximum, elevation is flat, so a
    small error in the time of peak is a very small error in the elevation.
    """
    if hours <= 0:
        return []
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")

    end = start + timedelta(hours=hours)
    step = timedelta(seconds=step_seconds)
    found: list[Pass] = []

    moment = start
    previous_elevation = _elevation(tle, observer, moment)
    rise_at: datetime | None = None
    previous = moment

    while moment < end:
        moment = min(moment + step, end)
        elevation = _elevation(tle, observer, moment)

        if previous_elevation < min_elevation <= elevation and rise_at is None:
            rise_at = _refine_crossing(tle, observer, previous, moment, min_elevation)
        elif rise_at is not None and elevation < min_elevation <= previous_elevation:
            set_at = _refine_crossing(tle, observer, moment, previous, min_elevation)
            found.append(_describe(tle, observer, rise_at, set_at, step_seconds))
            rise_at = None

        previous, previous_elevation = moment, elevation

    # A pass still in progress at the end of the window is reported as far as
    # the window goes, rather than dropped -- "it is up now" is the single most
    # useful thing this can say.
    if rise_at is not None:
        found.append(_describe(tle, observer, rise_at, end, step_seconds))
    return found


def _describe(
    tle: Tle, observer: Observer, rise: datetime, set_at: datetime, step_seconds: int
) -> Pass:
    best_time, best_elevation = rise, _elevation(tle, observer, rise)
    span = (set_at - rise).total_seconds()
    samples = max(2, int(span / max(1, step_seconds // 3)))
    for index in range(samples + 1):
        moment = rise + timedelta(seconds=span * index / samples)
        elevation = _elevation(tle, observer, moment)
        if elevation > best_elevation:
            best_time, best_elevation = moment, elevation

    rise_az = observe(tle, observer, rise)[0]
    peak_az, peak_el, _ = observe(tle, observer, best_time)
    set_az = observe(tle, observer, set_at)[0]
    return Pass(
        name=tle.name,
        catalog_number=tle.catalog_number,
        rise=rise,
        peak=best_time,
        set=set_at,
        max_elevation=peak_el,
        rise_azimuth=rise_az,
        peak_azimuth=peak_az,
        set_azimuth=set_az,
    )


def upcoming(
    tles: list[Tle],
    observer: Observer,
    start: datetime,
    hours: float = 24.0,
    *,
    min_elevation: float = DEFAULT_MIN_ELEVATION,
    limit: int = 40,
) -> list[Pass]:
    """Passes for a whole constellation, merged and sorted by rise time.

    One satellite with unusable elements must not cost the other ninety-nine,
    so a set SGP4 rejects is skipped rather than raised. That is the same call
    parse_tles makes and for the same reason.
    """
    everything: list[Pass] = []
    for tle in tles:
        try:
            everything.extend(passes(tle, observer, start, hours, min_elevation=min_elevation))
        except (TleError, ValueError):
            continue
    everything.sort(key=lambda item: item.rise)
    return everything[:limit]

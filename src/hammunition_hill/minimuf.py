# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""MINIMUF 3.5: point-to-point MUF prediction, the honest VOACAP substitute.

## Provenance

This is an original implementation of the MINIMUF 3.5 algorithm published by
R. B. Rose and J. N. Martin at the Naval Ocean Systems Center (NOSC TR 201,
1978; the 3.5 revision is NOSC ADA066256, 1979) and popularised by the QST
write-up in December 1982. The algorithm is a United States Government work
and public domain; the code here is written fresh from the published
equations, not copied from any of the BASIC, FORTRAN or C ports that have
circulated since (David Mills' C port was read as a reference for the
coefficient values).

## What it is worth

MINIMUF was fitted against oblique-sounder measurements over 23 real paths
and its report claims an RMS error of about 3.8 MHz. That is the honest
number to keep in mind: it will tell you 20 m is open to Japan this
afternoon and 10 m is not, and it will sometimes be a band off. It models
the F2 layer only -- no sporadic-E, no antenna patterns, no power, no
signal-to-noise prediction. VOACAP does all of that and remains unwritten
here; docs/PROPAGATION.md says exactly where the line sits.

## How it works, briefly

The path is a great circle. For a short path the ionosphere is sampled at
the midpoint; for a long one, at two control points near each end (where
the rays actually refract). At each control point the model builds an
effective solar illumination ``G`` that rises after local sunrise with a
seasonal time constant and decays exponentially after sunset -- that lag is
why 20 m stays open into the evening -- then maps it to a critical
frequency, applies an obliquity factor for the hop geometry, and takes the
worst control point. All times are UTC; the model converts to local solar
time internally, equation-of-time correction included.
"""

from __future__ import annotations

import math

# The model's own operating envelope. The fit was made against real HF
# circuits, not against a station talking to itself: below a few hundred
# kilometres the control-point geometry degenerates (and NVIS is a different
# problem), and past roughly 12 000 km the two-control-point assumption
# stops resembling the real ray paths.
MIN_PATH_KM = 250.0
MAX_PATH_KM = 12000.0

EARTH_RADIUS_KM = 6371.0

# Sunspot number is the model's solar input; flux is what the dashboard has.
# This inverse of the standard SSN->flux fit is part of the published
# routine, with branch joins deliberately continuous at 110 and 213 sfu --
# the tests pin both joins.
FLUX_FLOOR = 65.0


def sunspots_from_flux(flux: float) -> float:
    """Smoothed sunspot number from 10.7 cm solar flux."""
    if flux < FLUX_FLOOR:
        return 0.0
    if flux < 110.0:
        return 108.36 - 0.005896 * (flux - 200.6) ** 2
    if flux < 213.0:
        return 60.0 + 1.0680 * (flux - 110.0)
    return 384.0 - 0.0011059 * (flux - 652.9) ** 2


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _mod(value: float, span: float) -> float:
    return value % span


def path_muf(
    *,
    sfi: float,
    month: int,
    day: int,
    utc_hour: float,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float | None:
    """Predicted MUF in MHz for the great-circle path, or None off-envelope.

    Latitudes and longitudes are ordinary degrees, east positive. ``utc_hour``
    may be fractional. ``None`` means the path is outside what the model was
    fitted for, which the caller should say rather than smooth over.
    """
    # The published routine works in west-positive radians; convert once at
    # the boundary and keep the interior in the paper's own conventions so
    # the equations below can be checked against it term by term.
    #
    # An endpoint on the pole makes the control-point longitude expression
    # divide by cos(latitude); nudging by a tenth of a degree costs nothing
    # a 3.8 MHz RMS model can measure.
    la1 = math.radians(_clamp(lat1, -89.9, 89.9))
    la2 = math.radians(_clamp(lat2, -89.9, 89.9))
    lo1 = math.radians(_mod(-lon1, 360.0))
    lo2 = math.radians(_mod(-lon2, 360.0))

    cos_dist = _clamp(
        math.sin(la1) * math.sin(la2) + math.cos(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    )
    dist = math.acos(cos_dist)  # path angle, radians
    km = dist * EARTH_RADIUS_KM
    if not MIN_PATH_KM <= km <= MAX_PATH_KM:
        return None

    ssn = sunspots_from_flux(max(sfi, 0.0))

    # k6: how many 2000-km-ish hops the path is; caps the control-point
    # spread. m9: the obliquity factor -- how much higher than vertical
    # incidence an oblique ray can be and still come back down.
    hops = max(1.0, 1.59 * dist)
    half_hop = _clamp(2.5 * dist / hops, high=math.pi / 2.0)
    sin_half = math.sin(half_hop)
    m9 = 1.0 + 2.5 * sin_half * math.sqrt(sin_half)

    # Day-of-year phase and solar declination, as the paper approximates them.
    y1 = 0.0172 * (10.0 + (month - 1) * 30.4 + day)
    declination = 0.409 * math.cos(y1)

    # cos(azimuth) at end 2 toward end 1, used to walk the great circle.
    azimuth_cos = (math.sin(la1) - math.sin(la2) * math.cos(dist)) / (
        math.cos(la2) * math.sin(dist)
    )

    # Control points: the midpoint for a single-hop path, otherwise one
    # point half a hop in from each end. The set is symmetric, which is why
    # the prediction is reciprocal -- pinned by a test.
    fractions = [0.5] if hops <= 1.0 else [1.0 / (2.0 * hops), 1.0 - 1.0 / (2.0 * hops)]

    muf = 100.0
    for fraction in fractions:
        along = dist * fraction
        sin_lat = _clamp(
            math.sin(la2) * math.cos(along) + math.cos(la2) * math.sin(along) * azimuth_cos
        )
        point_lat = math.asin(sin_lat)  # paper's y3, via pi/2 - acos
        cos_dlon = _clamp(
            (math.cos(along) - sin_lat * math.sin(la2))
            / (math.cos(la2) * math.sqrt(1.0 - sin_lat * sin_lat))
        )
        point_lon = lo2 + math.copysign(1.0, math.sin(lo1 - lo2)) * math.acos(cos_dlon)
        point_lon = _mod(point_lon, 2.0 * math.pi)

        # UTC time of local solar noon at this longitude (west positive), with
        # the paper's two-term equation of time.
        noon_utc = _mod(
            3.82 * point_lon + 12.0 + 0.13 * (math.sin(y1) + 1.2 * math.sin(2.0 * y1)), 24.0
        )

        if math.cos(point_lat + declination) <= -0.26:
            # Polar night at the control point: no F2 buildup at all.
            daylight_hours = 0.0
            illumination = 0.0
        else:
            # Half-day arc from the -0.26 solar-elevation threshold (the sun
            # ionises through the horizon for a while, hence not zero).
            ratio = (-0.26 + math.sin(declination) * sin_lat) / (
                math.cos(declination) * math.cos(point_lat) + 0.001
            )
            daylight_hours = (
                12.0 - math.atan(ratio / math.sqrt(abs(1.0 - ratio * ratio))) * 7.639437
            )
            sunrise = _mod(noon_utc - daylight_hours / 2.0, 24.0)
            sunset = _mod(noon_utc + daylight_hours / 2.0, 24.0)

            # Buildup/decay time constant: fast at the equator in equinox,
            # slow at high summer latitudes. The floor keeps the exponentials
            # finite in polar day.
            peak = abs(math.cos(point_lat + declination))
            tau = max(0.1, 9.7 * peak**9.6)
            g8 = math.pi * tau / daylight_hours

            is_night = (sunset < sunrise and (utc_hour - sunset) * (sunrise - utc_hour) > 0.0) or (
                sunset >= sunrise and (utc_hour - sunrise) * (sunset - utc_hour) <= 0.0
            )

            if is_night:
                # Exponential decay from the sunset value, two-hour constant.
                hour = utc_hour + 24.0 if sunset > utc_hour else utc_hour
                illumination = (
                    peak
                    * (g8 * (math.exp(-daylight_hours / tau) + 1.0))
                    * math.exp((sunset - hour) / 2.0)
                    / (1.0 + g8 * g8)
                )
            else:
                # Daytime: a solar half-sine plus the morning exponential
                # rise, floored at what is left of yesterday's decay.
                hour = utc_hour + 24.0 if sunrise > utc_hour else utc_hour
                phase = math.pi * (hour - sunrise) / daylight_hours
                illumination = (
                    peak
                    * (math.sin(phase) + g8 * (math.exp((sunrise - hour) / tau) - math.cos(phase)))
                    / (1.0 + g8 * g8)
                )
                overnight_floor = (
                    peak
                    * (g8 * (math.exp(-daylight_hours / tau) + 1.0))
                    * math.exp((daylight_hours - 24.0) / 2.0)
                    / (1.0 + g8 * g8)
                )
                illumination = max(illumination, overnight_floor)

        point_muf = (
            (1.0 + ssn / 250.0) * m9 * math.sqrt(6.0 + 58.0 * math.sqrt(max(0.0, illumination)))
        )
        # Polar-day paths lose a little; transequatorial ones gain a little;
        # a control point above 45 degrees latitude is trimmed, because the
        # fit was worst where the auroral ionosphere lives.
        point_muf *= 1.0 - 0.1 * math.exp((daylight_hours - 24.0) / 3.0)
        point_muf *= 1.0 + 0.1 * (1.0 - _sign(lat1) * _sign(lat2))
        point_muf *= 1.0 - 0.1 * (1.0 + _sign(abs(math.sin(point_lat)) - math.cos(point_lat)))

        muf = min(muf, point_muf)

    return muf


def _sign(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0

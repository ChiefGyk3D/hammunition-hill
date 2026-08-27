# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Antenna, feedline and SWR arithmetic.

The calculations an operator reaches for a website to do, done here instead:
how long to cut a dipole, what a run of RG-58 costs at 2 m, what an SWR of 2.5
actually means in watts. All of it is arithmetic over small tables, which makes
it tier 0 in the sense the rest of this project means it -- as available at a
POTA site with the phone in aeroplane mode as at home.

Two things this is honest about, because a calculator that is not is worse than
no calculator:

  - **Cut long.** Every length here is a starting point. Height above ground,
    nearby metal, insulation on the wire and the shape of the feedpoint all
    move resonance, and they move it by more than the difference between the
    formulas people argue about. Cut long, measure, trim.
  - **The coax figures are nominal.** They are manufacturer headline numbers
    for new cable on a bench. Real loss rises with age, water in the braid,
    every connector, and the temperature of the run. Treat the number as a
    floor.
"""

from __future__ import annotations

import math
from typing import Any

# Metres per second, and the number every length below descends from.
SPEED_OF_LIGHT = 299_792_458.0

# A half-wave of wire resonates a few per cent short of a free-space half wave,
# because a wire is not infinitely thin and its ends are not in free space. 0.95
# is the conventional figure and the one behind the 468/f rule of thumb that US
# handbooks have printed for a century.
#
# It is a rule of thumb. See the module docstring: cut long.
WIRE_SHORTENING = 0.95

# fmt: off
# Fenced per the rule in CONTRIBUTING: this is data, laid out as a table because
# that is how it is read and checked.
#
# Loss is given as two published points rather than as fitted constants. The
# model below (k1*sqrt(f) + k2*f -- conductor loss goes as the square root of
# frequency, dielectric loss goes linearly) is then *defined* by these two
# numbers, so what the calculator claims is exactly what is written here and a
# reviewer can check it against a datasheet without solving anything.
#
# dB per 100 ft, at MHz. Velocity factor is the nominal figure for the type.
COAX: tuple[dict[str, Any], ...] = (
    {"id": "rg174",    "name": "RG-174",           "vf": 0.66, "ohms": 50,
     "at": ((100.0, 8.9), (450.0, 21.0)),  "note": "thin, lossy, for jumpers only"},
    {"id": "rg58",     "name": "RG-58A/U",         "vf": 0.66, "ohms": 50,
     "at": ((100.0, 4.1), (450.0, 10.1)),  "note": "common and lossy above HF"},
    {"id": "rg8x",     "name": "RG-8X",            "vf": 0.82, "ohms": 50,
     "at": ((100.0, 3.7), (450.0, 8.6)),   "note": "the usual portable compromise"},
    {"id": "rg213",    "name": "RG-213/U",         "vf": 0.66, "ohms": 50,
     "at": ((100.0, 1.9), (450.0, 4.5)),   "note": "the HF workhorse"},
    {"id": "lmr240",   "name": "LMR-240",          "vf": 0.84, "ohms": 50,
     "at": ((100.0, 2.6), (450.0, 5.8))},
    {"id": "lmr400",   "name": "LMR-400",          "vf": 0.85, "ohms": 50,
     "at": ((100.0, 1.2), (450.0, 2.7)),   "note": "the VHF/UHF default"},
    {"id": "lmr600",   "name": "LMR-600",          "vf": 0.87, "ohms": 50,
     "at": ((100.0, 0.8), (450.0, 1.7))},
    {"id": "ldf4",     "name": "LDF4-50A hardline","vf": 0.88, "ohms": 50,
     "at": ((100.0, 0.6), (450.0, 1.3)),   "note": "heavy, stiff, and worth it on a tower"},
    {"id": "rg6",      "name": "RG-6 (75 Ω)",      "vf": 0.85, "ohms": 75,
     "at": ((100.0, 1.9), (450.0, 4.4)),   "note": "75 Ω -- receive and hardline feeds"},
    {"id": "window450","name": "450 Ω window line","vf": 0.91, "ohms": 450,
     "at": ((100.0, 0.5), (450.0, 1.2)),   "note": "very low loss, and it hates metal and rain"},
)

# What each of the common single-element antennas is, as a multiple of a
# wavelength, and whether a wire's end effect applies to it.
#
# `factor` is the length in wavelengths. `wire` says whether this is an
# end-fed-in-air conductor whose resonance sits ~5% short of the geometric
# length; a vertical over a ground plane behaves the same way, a loop much less
# so, which is why the full-wave loop carries its own conventional figure.
ANTENNAS: tuple[dict[str, Any], ...] = (
    {"id": "dipole",   "name": "Half-wave dipole",     "factor": 0.5,   "wire": True,
     "note": "total tip to tip; each leg is half of it"},
    {"id": "vertical", "name": "Quarter-wave vertical","factor": 0.25,  "wire": True,
     "note": "over a ground plane or radials, which are the other half of the antenna"},
    {"id": "efhw",     "name": "End-fed half wave",    "factor": 0.5,   "wire": True,
     "note": "same wire as a dipole, fed at the end through a transformer"},
    {"id": "fivth",    "name": "5/8-wave vertical",    "factor": 0.625, "wire": True,
     "note": "needs a loading coil at the base; gain over a quarter wave"},
    {"id": "loop",     "name": "Full-wave loop",       "factor": 1.02,  "wire": False,
     "note": "the 1005/f rule: a loop runs slightly long, not short"},
)
# fmt: on

COAX_BY_ID = {entry["id"]: entry for entry in COAX}
ANTENNA_BY_ID = {entry["id"]: entry for entry in ANTENNAS}

FEET_PER_METRE = 3.280839895013123


class AntennaError(ValueError):
    """A frequency, length or SWR that cannot mean anything."""


def wavelength_m(freq_mhz: float) -> float:
    """A free-space wavelength, in metres."""
    if freq_mhz <= 0:
        raise AntennaError(f"frequency must be positive, got {freq_mhz}")
    return SPEED_OF_LIGHT / (freq_mhz * 1e6)


def element_length_m(freq_mhz: float, antenna_id: str) -> float:
    """The length to cut, in metres, for one of the antennas in ANTENNAS."""
    entry = ANTENNA_BY_ID.get(antenna_id)
    if entry is None:
        raise AntennaError(f"unknown antenna: {antenna_id!r}")
    length = wavelength_m(freq_mhz) * entry["factor"]
    return length * WIRE_SHORTENING if entry["wire"] else length


def cut_chart(freq_mhz: float) -> list[dict[str, Any]]:
    """Every antenna in the table at one frequency, metric and imperial.

    Both units, because a chart that makes half its readers convert is a chart
    they will get wrong once and then stop using.
    """
    chart = []
    for entry in ANTENNAS:
        metres = element_length_m(freq_mhz, entry["id"])
        chart.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "metres": round(metres, 3),
                "feet": round(metres * FEET_PER_METRE, 2),
                "note": entry.get("note", ""),
            }
        )
    return chart


def loss_constants(low: tuple[float, float], high: tuple[float, float]) -> tuple[float, float]:
    """Solve k1, k2 in loss = k1*sqrt(f) + k2*f from two published points.

    Conductor loss rises as the square root of frequency and dielectric loss
    rises linearly with it, so two measurements pin the curve. Deriving the
    constants rather than storing them means COAX holds numbers a reviewer can
    check against a datasheet.
    """
    (f1, l1), (f2, l2) = low, high
    if f1 <= 0 or f2 <= 0:
        raise AntennaError("loss reference frequencies must be positive")
    r1, r2 = math.sqrt(f1), math.sqrt(f2)
    determinant = r1 * f2 - r2 * f1
    if determinant == 0:
        raise AntennaError("the two loss reference points are not independent")
    k1 = (l1 * f2 - l2 * f1) / determinant
    k2 = (r1 * l2 - r2 * l1) / determinant
    return k1, k2


def matched_loss_db(coax_id: str, freq_mhz: float, length_m: float) -> float:
    """Loss of a matched line, in dB. Nominal -- see the module docstring."""
    entry = COAX_BY_ID.get(coax_id)
    if entry is None:
        raise AntennaError(f"unknown coax: {coax_id!r}")
    if freq_mhz <= 0:
        raise AntennaError(f"frequency must be positive, got {freq_mhz}")
    if length_m < 0:
        raise AntennaError(f"length cannot be negative, got {length_m}")
    k1, k2 = loss_constants(*entry["at"])
    per_100ft = k1 * math.sqrt(freq_mhz) + k2 * freq_mhz
    return per_100ft * (length_m * FEET_PER_METRE) / 100.0


def electrical_length_m(freq_mhz: float, coax_id: str, wavelengths: float = 0.25) -> float:
    """How much cable makes a given electrical length -- a matching stub, say.

    A quarter-wave of *cable* is shorter than a quarter-wave of air by its
    velocity factor, which is the single most common way a home-made matching
    section ends up the wrong length.
    """
    entry = COAX_BY_ID.get(coax_id)
    if entry is None:
        raise AntennaError(f"unknown coax: {coax_id!r}")
    return wavelength_m(freq_mhz) * wavelengths * entry["vf"]


def swr_figures(swr: float) -> dict[str, float | None]:
    """What an SWR reading means, in the units people actually care about."""
    if swr < 1.0:
        raise AntennaError(f"SWR cannot be below 1.0, got {swr}")
    if math.isinf(swr):
        # An open or a short: everything comes back.
        return {
            "swr": None,
            "rho": 1.0,
            "return_loss_db": 0.0,
            "reflected_pct": 100.0,
            "mismatch_loss_db": None,
        }
    rho = (swr - 1.0) / (swr + 1.0)
    reflected = rho**2
    # A perfect match reflects nothing, and log(0) is not a number -- nor is it
    # JSON. Both infinities are published as null and rendered as an infinity
    # sign, which is what they are and what a reader wants to see.
    return {
        "swr": round(swr, 3),
        "rho": round(rho, 4),
        "return_loss_db": None if rho == 0 else round(-20.0 * math.log10(rho), 2),
        "reflected_pct": round(reflected * 100.0, 2),
        # `+ 0.0` because round(-0.0, 3) is -0.0, and "-0.0 dB" reads as a bug.
        "mismatch_loss_db": round(-10.0 * math.log10(1.0 - reflected), 3) + 0.0,
    }


def total_line_loss_db(coax_id: str, freq_mhz: float, length_m: float, swr: float) -> float:
    """Matched loss plus the extra a standing wave costs.

    An SWR of 2:1 on a short run of good cable costs almost nothing, and the
    same SWR on a long run of RG-58 at 2 m costs most of your power. The point
    of showing both numbers is that "high SWR" is not by itself the problem --
    high SWR *through a lossy line* is.

    Standard transmission-line result: with matched loss `a` as a power ratio
    and reflection coefficient rho,
        total = -10*log10( a*(1 - rho^2) / (1 - a^2*rho^2) )
    """
    matched = matched_loss_db(coax_id, freq_mhz, length_m)
    if swr < 1.0:
        raise AntennaError(f"SWR cannot be below 1.0, got {swr}")
    rho = (swr - 1.0) / (swr + 1.0)
    if rho == 0 or matched == 0:
        return matched
    a = 10.0 ** (-matched / 10.0)
    numerator = a * (1.0 - rho**2)
    denominator = 1.0 - (a**2) * (rho**2)
    return -10.0 * math.log10(numerator / denominator)


def power_after_loss(watts: float, loss_db: float) -> float:
    """What reaches the antenna. The number that makes a loss figure mean something."""
    if watts < 0:
        raise AntennaError(f"power cannot be negative, got {watts}")
    return watts * 10.0 ** (-loss_db / 10.0)


def reference() -> dict[str, Any]:
    """The tables the panel needs, published as one structure."""
    return {
        "antennas": [dict(entry) for entry in ANTENNAS],
        "coax": [
            {
                "id": entry["id"],
                "name": entry["name"],
                "vf": entry["vf"],
                "ohms": entry["ohms"],
                "at": [list(point) for point in entry["at"]],
                "note": entry.get("note", ""),
            }
            for entry in COAX
        ],
        "wire_shortening": WIRE_SHORTENING,
        "feet_per_metre": FEET_PER_METRE,
    }

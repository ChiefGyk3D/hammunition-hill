# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A crude HF propagation indicator, computed from numbers we already have.

## What this is, and what it is not

This is **not** a propagation prediction. VOACAP is a propagation prediction:
it models a specific path, at a specific hour, with antenna patterns and power,
against a climatological ionosphere, and it took decades of work. This is an
indicator built from three numbers -- solar flux, the K index, and how high the
sun is above your station -- that answers a much smaller question: *roughly
which bands are worth trying right now, and why not the others.*

It is worth having because the three inputs are already on the dashboard and
the arithmetic is free, and because the honest version of it is genuinely
useful: a number that says "10m is probably shut because the MUF is under
20 MHz" beats staring at an SFI of 92 and doing it in your head.

Every function here is an empirical approximation. The docstrings say which,
and `docs/PROPAGATION.md` says what each one is worth. Where a number would be
misleading without its caveat, the caveat is returned alongside it rather than
left in a document nobody opens.

## Why the station's own location is the point

The obvious version of this uses the UTC hour as a stand-in for how high the
sun is -- ``abs(utc_hour - 12)``, peaking at noon. That is exactly right on the
Greenwich meridian and wrong everywhere else, by four hours in Denver and nine
in Tokyo. Since the D layer's absorption is driven by solar illumination, an
operator in Colorado using that model is told the bands are at their worst
around 05:00 local.

This project knows the operator's grid square, so it computes the real solar
zenith angle at their actual location. That single change is most of the value
here, and it is the reason this is a port with corrections rather than a copy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .solar import Subsolar, solar_zenith, subsolar_point

# --- foF2 --------------------------------------------------------------------
# The F2 critical frequency: the highest frequency that comes straight back down
# at vertical incidence. Everything else here is derived from it.
#
# The relationship to solar flux is empirical and loose. Real foF2 swings with
# season, latitude, and day-to-day ionospheric weather that no flux number
# captures -- two days with the same SFI can differ by several MHz. Treat the
# output as an order-of-magnitude sanity check.
#
# A Chapman layer gives electron density proportional to sqrt(cos chi) and
# critical frequency proportional to sqrt(density), hence the fourth root of
# cos(zenith) below. The night floor exists because the F2 layer does not
# vanish after dark -- it decays, which is why 40m stays open all night.
# foF2 at the reference flux with the sun overhead. Calibrated against the
# operating anchors pinned in tests/test_propagation.py rather than derived.
FOF2_BASE_MHZ = 9.5
FOF2_FLUX_REFERENCE = 100.0

# Fraction of the daytime value the F2 layer retains after dark. An earlier
# 0.30 put solar-maximum nights at 4 MHz, which would have called 40m marginal
# on evenings when it is reliably open to the other side of the world.
FOF2_NIGHT_FLOOR = 0.45

# --- MUF ---------------------------------------------------------------------
# MUF(3000)F2 = foF2 * M, where M is the obliquity factor for a 3000 km hop. It
# depends on layer height and path geometry; 3.0 is the conventional mid-range
# value and what a "MUF" quoted without a path usually means.
M_FACTOR_3000 = 3.0

# --- D layer -----------------------------------------------------------------
# Daytime absorption on the lower bands. Non-deviative absorption scales as
# roughly cos^0.75(chi) and inversely with the square of frequency -- which is
# why 80m dies at midday while 20m does not notice.
ABSORPTION_ZENITH_EXPONENT = 0.75
ABSORPTION_FLUX_COEFFICIENT = 0.0037  # per flux unit, the classic (1 + 0.0037*S)
ABSORPTION_SCALE = 26.0  # tunes dB at the reference; see the test for the anchors

# Geomagnetic storms add absorption, worst at high latitudes where the particle
# precipitation actually lands. A K of 7 over Norway is a different day from a
# K of 7 over Ecuador, and a model that ignores that is wrong in the case an
# operator most needs it.
STORM_ABSORPTION_PER_K = 0.6
STORM_LATITUDE_PIVOT = 45.0

BANDS_MHZ: tuple[tuple[str, float], ...] = (
    ("160m", 1.9),
    ("80m", 3.7),
    ("60m", 5.35),
    ("40m", 7.1),
    ("30m", 10.1),
    ("20m", 14.2),
    ("17m", 18.1),
    ("15m", 21.2),
    ("12m", 24.9),
    ("10m", 28.4),
    ("6m", 50.1),
)


@dataclass(frozen=True)
class Conditions:
    """Everything the model produces for one moment at one place."""

    fof2_mhz: float
    muf_mhz: float
    luf_mhz: float
    absorption_db: float
    solar_zenith_deg: float
    is_daylight: bool
    bands: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fof2_mhz": round(self.fof2_mhz, 1),
            "muf_mhz": round(self.muf_mhz, 1),
            "luf_mhz": round(self.luf_mhz, 1),
            "absorption_db": round(self.absorption_db, 1),
            "solar_zenith_deg": round(self.solar_zenith_deg, 1),
            "is_daylight": self.is_daylight,
            "bands": list(self.bands),
        }


def _cos_zenith(zenith_deg: float) -> float:
    """cos(chi), floored at zero. Below the horizon there is no illumination."""
    return max(0.0, math.cos(math.radians(zenith_deg)))


def fof2_mhz(sfi: float, zenith_deg: float) -> float:
    """Estimated F2 critical frequency, in MHz.

    Empirical, and loose. Two inputs: solar flux sets the ceiling, solar zenith
    sets how much of it is realised right now.

    Note on the source this was ported from: its docstring described
    ``sqrt(SFI/150)`` while the code implemented ``sqrt(SFI/100)``, so the two
    disagreed about solar minimum by nearly a megahertz. Neither matched the
    ranges the docstring itself claimed. This implementation is written to hit
    plausible values at both ends -- roughly 4 MHz at night near solar minimum,
    roughly 13 MHz in the afternoon near solar maximum -- and the test file
    pins those anchors so a future tweak has to argue with them.
    """
    flux = max(sfi, 50.0)  # Below ~65 is instrumentally implausible; clamp low.
    ceiling = FOF2_BASE_MHZ * math.sqrt(flux / FOF2_FLUX_REFERENCE)

    # Chapman: foF2 goes as the fourth root of cos(chi), with a night floor
    # because the layer decays rather than disappearing.
    illumination = _cos_zenith(zenith_deg) ** 0.25
    factor = FOF2_NIGHT_FLOOR + (1.0 - FOF2_NIGHT_FLOOR) * illumination
    return ceiling * factor


def muf_mhz(fof2: float, m_factor: float = M_FACTOR_3000) -> float:
    """Maximum usable frequency for a long hop.

    ``M_FACTOR_3000`` assumes a 3000 km path, which is what an unqualified
    "MUF" usually means. A short path has a lower MUF and a chordal one can
    exceed this; the model has no path, so it cannot know which you want.
    """
    return fof2 * m_factor


def absorption_db(sfi: float, zenith_deg: float, k_index: float, latitude: float) -> float:
    """D-layer absorption at 1 MHz reference, in dB.

    Daylight-driven and strongly so: the D layer forms under illumination and
    is gone within an hour of sunset, which is the entire reason 160m and 80m
    are night bands.

    Storm absorption is scaled by latitude, because particle precipitation lands
    near the auroral oval. A model that applied a K of 7 equally to Tromsø and
    Quito would be most wrong exactly when it matters.
    """
    cos_chi = _cos_zenith(zenith_deg)
    daytime = ABSORPTION_SCALE * (1.0 + ABSORPTION_FLUX_COEFFICIENT * max(sfi, 0.0))
    absorption = daytime * (cos_chi**ABSORPTION_ZENITH_EXPONENT)

    if k_index >= 5:
        # Ramps in above the pivot latitude rather than switching on, so a
        # station at 44 degrees and one at 46 do not get wildly different answers.
        weight = min(1.0, max(0.0, (abs(latitude) - STORM_LATITUDE_PIVOT) / 25.0 + 0.35))
        absorption += STORM_ABSORPTION_PER_K * (k_index - 4.0) * weight * 10.0

    return absorption


def luf_mhz(absorption: float, threshold_db: float = 6.0) -> float:
    """Lowest usable frequency: below this, absorption eats the signal.

    Absorption scales as roughly 1/f^2, so inverting for the frequency at which
    it falls to a workable level gives a usable floor.
    """
    if absorption <= threshold_db:
        return 0.0
    return math.sqrt(absorption / threshold_db)


def _band_state(freq: float, muf: float, luf: float) -> tuple[str, str]:
    """(level, reason) for one band. Level is the shared good/warn/critical ramp."""
    if freq > muf:
        return "critical", "above the MUF"
    if freq < luf:
        return "critical", "below the LUF — D-layer absorption"
    # Within about 15% of the MUF is where paths are best but least reliable.
    if freq > muf * 0.85:
        return "warn", "near the MUF — long paths, may fade"
    if freq < luf * 1.3:
        return "warn", "close to the LUF — lossy"
    return "good", "open"


def conditions(
    *,
    sfi: float,
    k_index: float,
    latitude: float,
    longitude: float,
    moment: datetime | None = None,
    subsolar: Subsolar | None = None,
) -> Conditions:
    """The whole model for one station at one instant."""
    sun = subsolar or subsolar_point(moment)
    zenith = solar_zenith(latitude, longitude, sun)

    critical = fof2_mhz(sfi, zenith)
    maximum = muf_mhz(critical)
    absorption = absorption_db(sfi, zenith, k_index, latitude)
    lowest = luf_mhz(absorption)

    bands = []
    for name, freq in BANDS_MHZ:
        level, reason = _band_state(freq, maximum, lowest)
        bands.append({"band": name, "mhz": freq, "level": level, "reason": reason})

    return Conditions(
        fof2_mhz=critical,
        muf_mhz=maximum,
        luf_mhz=lowest,
        absorption_db=absorption,
        solar_zenith_deg=zenith,
        is_daylight=zenith < 90.0,
        bands=tuple(bands),
    )

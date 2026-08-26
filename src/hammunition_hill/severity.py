# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""What a space weather number actually means.

A K-index of 5 is a geomagnetic storm; a solar flux of 70 is a dead band. The
numbers alone say neither, so this module turns each metric into a severity
level, a plain-language label, and a position on its own scale -- which is what
a dial needs to draw and what an operator needs to read.

The classification lives here, in Python, rather than in the panel, for two
reasons. It is domain knowledge, not presentation: whether K=5 is a storm is a
fact about geomagnetism. And it is testable, which a canvas is not.

**Three severity levels, not four.** Four status colours cannot be told apart
reliably -- an amber-versus-orange pair measures below the normal-vision
separation floor, before considering colour blindness. Three separate cleanly.
Every level also carries a text label, because a colour must never be the only
thing carrying the meaning.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

GOOD = "good"
WARN = "warn"
CRITICAL = "critical"

LEVEL_ORDER = (GOOD, WARN, CRITICAL)


@dataclass(frozen=True)
class Zone:
    """Values up to and including ``upto`` carry this level and label."""

    upto: float
    level: str
    label: str


@dataclass(frozen=True)
class Scale:
    id: str
    name: str
    unit: str
    low: float
    high: float
    zones: tuple[Zone, ...]
    log: bool = False
    higher_is_better: bool = False
    decimals: int = 0
    upper_exclusive: bool = False
    """Whether a value sitting exactly on a boundary belongs to the zone above.

    The two conventions genuinely differ. K=3 and A=7 are quiet -- the boundary
    value belongs to the *lower* zone, which is how the indices are published.
    But X-ray classes are decade floors: 1.0e-5 is M1.0, which is M-class, not
    the top of C. Getting this wrong misreports a flare by a whole class.
    """

    def position(self, value: float) -> float:
        """Where the needle sits, 0..1 across the dial."""
        low, high, v = self.low, self.high, value
        if self.log:
            low = math.log10(max(low, 1e-12))
            high = math.log10(max(high, 1e-12))
            v = math.log10(max(value, 1e-12))
        if high == low:
            return 0.0
        return max(0.0, min(1.0, (v - low) / (high - low)))

    def zone_for(self, value: float) -> Zone:
        for zone in self.zones:
            if value < zone.upto or (not self.upper_exclusive and value == zone.upto):
                return zone
        return self.zones[-1]

    def bands(self) -> list[dict[str, object]]:
        """The coloured arc segments, as fractions of the dial.

        Adjacent zones of the same level are merged. Two abutting green
        segments would draw a seam the reader would try to interpret, when the
        only real boundary is where the severity actually changes.
        """
        out: list[dict[str, object]] = []
        start = 0.0
        for zone in self.zones:
            end = self.position(zone.upto)
            if end <= start:
                continue
            if out and out[-1]["level"] == zone.level:
                out[-1]["to"] = round(end, 4)
            else:
                out.append({"from": round(start, 4), "to": round(end, 4), "level": zone.level})
            start = end
        if start < 1.0:
            last = self.zones[-1].level
            if out and out[-1]["level"] == last:
                out[-1]["to"] = 1.0
            else:
                out.append({"from": round(start, 4), "to": 1.0, "level": last})
        return out


def _z(upto, level, label):
    return Zone(upto, level, label)


# Thresholds follow NOAA's published scales where they exist (G for geomagnetic,
# R for radio blackout, S for radiation) and long-standing operating convention
# where they do not (solar flux, sunspots, noise).
SCALES: dict[str, Scale] = {
    "sfi": Scale(
        id="sfi", name="Solar Flux", unit="SFU", low=60, high=300, higher_is_better=True,
        zones=(
            _z(70, CRITICAL, "Very low"),
            _z(100, WARN, "Low"),
            _z(150, GOOD, "Moderate"),
            _z(300, GOOD, "High"),
        ),
    ),
    "sunspots": Scale(
        id="sunspots", name="Sunspots", unit="", low=0, high=250, higher_is_better=True,
        zones=(
            _z(20, CRITICAL, "Very low"),
            _z(50, WARN, "Low"),
            _z(120, GOOD, "Moderate"),
            _z(250, GOOD, "High"),
        ),
    ),
    "xray": Scale(
        id="xray", name="X-Ray", unit="W/m²", low=1e-8, high=1e-3, log=True,
        upper_exclusive=True,
        zones=(
            _z(1e-6, GOOD, "Quiet"),
            _z(1e-5, WARN, "C-class"),
            _z(1e-4, CRITICAL, "M-class · R1–R2"),
            _z(1e-3, CRITICAL, "X-class · R3+"),
        ),
    ),
    "aindex": Scale(
        # Topped at 50 rather than the theoretical 400. A-index is almost always
        # under 30, and a 0-100 dial squeezed the quiet zone into a sliver -- the
        # dial looked alarming while the label said "Quiet", which is the worst
        # thing a severity display can do. Anything above 50 pins the needle,
        # which is the correct message for a major storm.
        id="aindex", name="A-Index", unit="", low=0, high=50,
        zones=(
            _z(7, GOOD, "Quiet"),
            _z(15, WARN, "Unsettled"),
            _z(29, WARN, "Active"),
            _z(50, CRITICAL, "Storm"),
        ),
    ),
    "kindex": Scale(
        id="kindex", name="K-Index", unit="", low=0, high=9, decimals=1,
        zones=(
            _z(3, GOOD, "Quiet"),
            _z(4, WARN, "Unsettled"),
            _z(5, CRITICAL, "G1 storm"),
            _z(6, CRITICAL, "G2 storm"),
            _z(7, CRITICAL, "G3 storm"),
            _z(9, CRITICAL, "G4–G5 storm"),
        ),
    ),
    "solarwind": Scale(
        id="solarwind", name="Solar Wind", unit="km/s", low=250, high=900,
        zones=(
            _z(400, GOOD, "Calm"),
            _z(550, WARN, "Elevated"),
            _z(700, CRITICAL, "High"),
            _z(900, CRITICAL, "Very high"),
        ),
    ),
    "noise": Scale(
        id="noise", name="Noise", unit="S-units", low=0, high=9, decimals=1,
        zones=(
            _z(2, GOOD, "Quiet"),
            _z(4, WARN, "Moderate"),
            _z(9, CRITICAL, "High"),
        ),
    ),
    "protons": Scale(
        id="protons", name="Protons", unit="pfu", low=0.1, high=10000, log=True, decimals=2,
        zones=(
            _z(10, GOOD, "Background"),
            _z(100, WARN, "S1 storm"),
            _z(10000, CRITICAL, "S2+ storm"),
        ),
    ),
}

# --- value parsing -------------------------------------------------------
_XRAY = re.compile(r"^([ABCMX])\s*([0-9]*\.?[0-9]*)$", re.IGNORECASE)
_XRAY_FLOOR = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}

_S_UNIT = re.compile(r"S\s*([0-9]+)", re.IGNORECASE)


def xray_to_watts(value: str | float | None) -> float | None:
    """'C1.4' to 1.4e-6. Accepts a raw flux number unchanged."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = _XRAY.match(str(value).strip())
    if not match:
        return None
    letter, magnitude = match.group(1).upper(), match.group(2)
    try:
        scale = float(magnitude) if magnitude else 1.0
    except ValueError:
        scale = 1.0
    return _XRAY_FLOOR[letter] * scale


def watts_to_xray(flux: float | None) -> str | None:
    """1.4e-6 back to 'C1.4', which is how operators speak."""
    if not flux or flux <= 0:
        return None
    for letter, floor in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7)):
        if flux >= floor:
            return f"{letter}{flux / floor:.1f}"
    return f"A{flux / 1e-8:.1f}"


def s_units(value: str | float | None) -> float | None:
    """HamQSL reports noise as a range like 'S0-S1'; take the worse end."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    found = _S_UNIT.findall(str(value))
    return float(max(int(n) for n in found)) if found else None


def to_number(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# --- classification ------------------------------------------------------
def classify(scale_id: str, raw: object) -> dict[str, object] | None:
    """One metric, ready for a dial. None when the value is missing or unusable."""
    scale = SCALES.get(scale_id)
    if scale is None:
        raise KeyError(f"unknown scale {scale_id!r}; known: {', '.join(sorted(SCALES))}")

    if scale_id == "xray":
        value = xray_to_watts(raw)  # type: ignore[arg-type]
        display = watts_to_xray(value)
    elif scale_id == "noise":
        value = s_units(raw)  # type: ignore[arg-type]
        display = f"S{value:.0f}" if value is not None else None
    else:
        value = to_number(raw)
        display = f"{value:.{scale.decimals}f}" if value is not None else None

    if value is None:
        return None

    zone = scale.zone_for(value)
    return {
        "id": scale.id,
        "name": scale.name,
        "unit": scale.unit,
        "value": value,
        "display": display,
        "level": zone.level,
        "label": zone.label,
        "position": round(scale.position(value), 4),
        "bands": scale.bands(),
        "higher_is_better": scale.higher_is_better,
    }


def classify_all(values: dict[str, object]) -> dict[str, dict[str, object]]:
    """Classify whatever is present, skipping what is not."""
    out = {}
    for scale_id, raw in values.items():
        if scale_id not in SCALES:
            continue
        result = classify(scale_id, raw)
        if result is not None:
            out[scale_id] = result
    return out


def worst(gauges: dict[str, dict[str, object]]) -> str:
    """The most severe level present -- the headline for a panel or status line."""
    level = GOOD
    for gauge in gauges.values():
        if LEVEL_ORDER.index(str(gauge["level"])) > LEVEL_ORDER.index(level):
            level = str(gauge["level"])
    return level

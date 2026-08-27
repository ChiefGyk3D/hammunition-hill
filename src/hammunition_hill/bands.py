# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Frequency to band, and the band-plan segments that imply a mode.

A DX cluster spot carries a frequency in kHz and, usually, nothing else machine
readable. Band and likely mode both have to be inferred, and the inference is
only as good as the band plan behind it -- so it is stated explicitly here
rather than buried in a regex.

Mode inference is a hint, not a fact. IARU regions differ, band plans move, and
operators do not always read them. The UI labels it as inferred wherever a spot
does not carry an explicit mode.
"""

from __future__ import annotations

from dataclasses import dataclass

# Band edges in kHz, widest common allocation across IARU regions. A spot just
# outside an edge is still recognisably on that band, which is what matters for
# grouping -- this is not a transmit-legality check and must never be used as one.
# fmt: off
# ruff format is enabled for this project, and deliberately switched off for the
# data tables below. The formatter's value is consistency in *code*; these are
# *data*, laid out as a table because that is how they are read and reviewed.
# Expanding the band tables to one field per line adds 49 lines and makes a
# reviewer scroll a screen to check what currently fits in a glance.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("2190m", 135.7, 137.8),
    ("630m", 472.0, 479.0),
    ("160m", 1800.0, 2000.0),
    ("80m", 3500.0, 4000.0),
    ("60m", 5250.0, 5450.0),
    ("40m", 7000.0, 7300.0),
    ("30m", 10100.0, 10150.0),
    ("20m", 14000.0, 14350.0),
    ("17m", 18068.0, 18168.0),
    ("15m", 21000.0, 21450.0),
    ("12m", 24890.0, 24990.0),
    ("10m", 28000.0, 29700.0),
    ("6m", 50000.0, 54000.0),
    ("4m", 70000.0, 70500.0),
    ("2m", 144000.0, 148000.0),
    ("1.25m", 222000.0, 225000.0),
    ("70cm", 420000.0, 450000.0),
    ("33cm", 902000.0, 928000.0),
    ("23cm", 1240000.0, 1300000.0),
)

# Ordered low to high, which is how operators read a band table.
BAND_ORDER: tuple[str, ...] = tuple(name for name, _, _ in BANDS)

# Digital watering holes, in kHz. These are narrow and well observed, so a spot
# landing on one is a strong signal -- much stronger than a general segment.
_DIGITAL_SPOTS: tuple[tuple[float, str], ...] = (
    (1840.0, "FT8"), (3573.0, "FT8"), (5357.0, "FT8"), (7074.0, "FT8"),
    (10136.0, "FT8"), (14074.0, "FT8"), (18100.0, "FT8"), (21074.0, "FT8"),
    (24915.0, "FT8"), (28074.0, "FT8"), (50313.0, "FT8"), (144174.0, "FT8"),
    (3568.0, "FT4"), (7047.5, "FT4"), (10140.0, "FT4"), (14080.0, "FT4"),
    (18104.0, "FT4"), (21140.0, "FT4"), (24919.0, "FT4"), (28180.0, "FT4"),
    (14070.0, "PSK31"), (7070.0, "PSK31"), (3580.0, "PSK31"),
    (14100.0, "RTTY"), (7040.0, "RTTY"), (21080.0, "RTTY"), (3590.0, "RTTY"),
)
_DIGITAL_TOLERANCE_KHZ = 3.0

# CW is at the bottom of every HF band. Upper bound in kHz per band.
_CW_CEILING: dict[str, float] = {
    "160m": 1843.0, "80m": 3600.0, "60m": 5354.0, "40m": 7040.0, "30m": 10130.0,
    "20m": 14070.0, "17m": 18095.0, "15m": 21070.0, "12m": 24910.0, "10m": 28070.0,
    "6m": 50100.0, "2m": 144100.0,
}
# fmt: on


@dataclass(frozen=True)
class BandInfo:
    band: str | None
    mode: str | None
    mode_inferred: bool


def band_for(khz: float) -> str | None:
    """The band a frequency in kHz falls in, or None if it is outside all of them."""
    for name, low, high in BANDS:
        if low <= khz <= high:
            return name
    return None


def infer_mode(khz: float, band: str | None = None) -> str | None:
    """Best guess at the mode from frequency alone. Always a hint, never a fact."""
    for centre, mode in _DIGITAL_SPOTS:
        if abs(khz - centre) <= _DIGITAL_TOLERANCE_KHZ:
            return mode

    band = band or band_for(khz)
    if band is None:
        return None

    ceiling = _CW_CEILING.get(band)
    if ceiling is not None and khz <= ceiling:
        return "CW"

    # Everything above the CW segment on HF is voice by default. On 160-40m that
    # means LSB, above 30m USB -- a distinction operators care about.
    if band in ("160m", "80m", "40m"):
        return "LSB"
    if band in ("60m", "30m"):
        return None  # 60m is channelised and 30m is CW/digital only.
    return "USB"


def classify(khz: float, explicit_mode: str | None = None) -> BandInfo:
    """Band and mode for a spot, preferring a mode the spot stated itself."""
    band = band_for(khz)
    if explicit_mode:
        return BandInfo(band=band, mode=explicit_mode.upper(), mode_inferred=False)
    return BandInfo(band=band, mode=infer_mode(khz, band), mode_inferred=True)


def sort_key(band: str | None) -> int:
    """Sort bands low to high; unknown bands sort last."""
    try:
        return BAND_ORDER.index(band)  # type: ignore[arg-type]
    except ValueError:
        return len(BAND_ORDER)

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Power arithmetic for a station: Ohm's law, decibels, wire, batteries.

The other half of the shack-tools panel. antenna.py is RF; this is the DC and
the ratios -- what a field operator computes on a napkin at the tailgate, and
gets wrong at exactly the moment a battery is running down.

Same contract as the rest of the tier 0 arithmetic: a JavaScript mirror in
web/lib/electrical.js renders the numbers, this module is canonical, and a
drift test runs both against the same inputs and demands identical output.
Formulas only earn a place here if they answer a question somebody in a field
actually has; a calculator nobody needs is UI surface with a maintenance bill.
"""

from __future__ import annotations

import math
from typing import Any


class ElectricalError(ValueError):
    """Inputs that have no answer, as a message somebody can act on."""


def ohm(
    volts: float | None = None,
    amps: float | None = None,
    ohms: float | None = None,
    watts: float | None = None,
) -> dict[str, float]:
    """Any two of V, I, R, P -> all four.

    The power wheel, without the wheel. Exactly two must be given: with three
    the system is overdetermined and silently ignoring one would mean the
    caller's typo becomes an answer.
    """
    given = {k: v for k, v in {"volts": volts, "amps": amps, "ohms": ohms, "watts": watts}.items()
             if v is not None}  # fmt: skip
    if len(given) != 2:
        raise ElectricalError(f"give exactly two of volts/amps/ohms/watts, not {len(given)}")
    for name, value in given.items():
        if value < 0:
            raise ElectricalError(f"{name} cannot be negative")

    v, i, r, p = volts, amps, ohms, watts
    if v is not None and i is not None:
        r, p = (v / i if i else math.inf), v * i
    elif v is not None and r is not None:
        if r == 0:
            raise ElectricalError("resistance of zero with a fixed voltage has no finite current")
        i = v / r
        p = v * i
    elif v is not None and p is not None:
        i = p / v if v else 0.0
        r = v / i if i else math.inf
    elif i is not None and r is not None:
        v = i * r
        p = v * i
    elif i is not None and p is not None:
        if i == 0 and p > 0:
            raise ElectricalError("power with zero current has no finite voltage")
        v = p / i if i else 0.0
        r = v / i if i else math.inf
    elif r is not None and p is not None:
        i = math.sqrt(p / r) if r else math.inf
        v = math.sqrt(p * r)
    return {"volts": v, "amps": i, "ohms": r, "watts": p}  # type: ignore[dict-item]


def db_from_power_ratio(ratio: float) -> float:
    if ratio <= 0:
        raise ElectricalError("a power ratio must be positive")
    return 10.0 * math.log10(ratio)


def power_ratio_from_db(db: float) -> float:
    return 10.0 ** (db / 10.0)


def db_between_watts(reference_w: float, compared_w: float) -> float:
    """+3 dB is double; the sign says which way."""
    if reference_w <= 0 or compared_w <= 0:
        raise ElectricalError("power must be positive on both sides")
    return db_from_power_ratio(compared_w / reference_w)


# fmt: off
# AWG copper, ohms per 1000 ft at 20 C, the table every ARRL handbook carries.
# Solid copper; stranded runs a few percent higher, which the round trip and
# the safety margin both dwarf.
AWG_OHMS_PER_KFT: dict[int, float] = {
    4: 0.2485, 6: 0.3951, 8: 0.6282, 10: 0.9989,
    12: 1.588, 14: 2.525, 16: 4.016, 18: 6.385, 20: 10.15,
}
# fmt: on

FEET_PER_METRE = 3.28084


def voltage_drop(
    awg: int, one_way_m: float, amps: float, supply_volts: float = 13.8
) -> dict[str, float]:
    """Drop over a two-conductor run: the round trip is the resistance.

    The classic field mistake is computing one conductor. Power goes out one
    wire and back the other, so ten metres of cable is twenty metres of copper.
    """
    if awg not in AWG_OHMS_PER_KFT:
        raise ElectricalError(
            f"AWG {awg} is not in the table; use one of {sorted(AWG_OHMS_PER_KFT)}"
        )
    if one_way_m < 0 or amps < 0 or supply_volts <= 0:
        raise ElectricalError("length and current must be >= 0 and supply > 0")
    round_trip_ft = 2.0 * one_way_m * FEET_PER_METRE
    resistance = AWG_OHMS_PER_KFT[awg] * round_trip_ft / 1000.0
    drop = resistance * amps
    return {
        "ohms": resistance,
        "drop_volts": drop,
        "at_load_volts": supply_volts - drop,
        "percent": 100.0 * drop / supply_volts,
    }


# Usable fraction of nameplate capacity before the chemistry is being hurt or
# the radio browns out. Lead-acid past half is trading cycles for minutes;
# lithium iron phosphate holds voltage nearly to the floor.
BATTERY_USABLE: dict[str, float] = {"lifepo4": 0.90, "lead_acid": 0.50, "agm": 0.60}


def battery_runtime(
    amp_hours: float, chemistry: str, load_watts: float, volts: float = 12.8
) -> dict[str, float]:
    """Hours a battery carries a load, honestly derated by chemistry."""
    if chemistry not in BATTERY_USABLE:
        raise ElectricalError(f"chemistry must be one of {sorted(BATTERY_USABLE)}")
    if amp_hours <= 0 or volts <= 0:
        raise ElectricalError("capacity and voltage must be positive")
    if load_watts <= 0:
        raise ElectricalError("load must be positive")
    usable_wh = amp_hours * volts * BATTERY_USABLE[chemistry]
    return {
        "usable_watt_hours": usable_wh,
        "hours": usable_wh / load_watts,
        "usable_fraction": BATTERY_USABLE[chemistry],
    }


def reference() -> dict[str, Any]:
    """The constants the panel shows, published so JS renders data, not lore."""
    return {
        "awg_ohms_per_kft": {str(k): v for k, v in AWG_OHMS_PER_KFT.items()},
        "battery_usable": dict(BATTERY_USABLE),
    }

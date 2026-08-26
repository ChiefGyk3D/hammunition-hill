# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Guessing a US licence class from callsign format.

The FCC issues callsigns from four groups, and you may hold a call from your own
group **or any group below it**. That asymmetry is the whole story:

- A **Group A** call (1x2, 2x1, or a 2x2 beginning with A) can only be held by
  an Amateur Extra. Seeing one tells you the class exactly.
- Every other format tells you only a *floor*. A 1x3 belongs to General's
  sequential group, but an Extra can hold one by vanity, and so can a Technician
  who had it before upgrading.

So this returns a best guess plus how much to trust it, and the guess is always
overridable. It exists to save an operator one line of config, not to be
authoritative -- which is why ``[station] license_class`` always wins.

**US only.** Other countries' callsign structures carry no class information
this could read, so a non-US call gets no guess at all rather than a wrong one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .prefix import PrefixTable, base_call

# One or two letters, one digit, one to three letters.
_US_CALL = re.compile(r"^([A-Z]{1,2})([0-9])([A-Z]{1,3})$")

# US callsign prefixes: K, N, W, and A followed by A-L.
_SINGLE_PREFIXES = frozenset("KNW")
_DOUBLE_FIRST = frozenset("AKNW")
_A_SECOND = frozenset("ABCDEFGHIJKL")

# Entities the FCC issues callsigns for. A DL or JA call has its own structure
# and none of this applies.
US_ENTITIES = frozenset({
    "United States",
    "Hawaii",
    "Alaska",
    "Puerto Rico",
    "US Virgin Islands",
    "Guam",
    "Mariana Islands",
    "American Samoa",
    "Midway Island",
    "Wake Island",
    "Baker & Howland Islands",
    "Johnston Island",
    "Navassa Island",
    "Palmyra & Jarvis Islands",
})


@dataclass(frozen=True)
class LicenceGuess:
    """A guessed class, with an honest account of how solid the guess is."""

    klass: str
    group: str
    certain: bool
    reason: str


def _classify_format(prefix: str, suffix: str) -> tuple[str, str, bool] | None:
    """(group, most likely class, certain) for a US callsign shape."""
    p, s = len(prefix), len(suffix)

    # Group A -- Amateur Extra only.
    if (p == 1 and s == 2) or (p == 2 and s == 1):
        return "A", "extra", True
    if p == 2 and prefix[0] == "A" and s == 2:
        return "A", "extra", True

    # Group B -- Advanced's sequential group, closed since 2000. An Extra may
    # hold one by vanity, so this is a floor rather than an answer.
    if p == 2 and prefix[0] in "KNW" and s == 2:
        return "B", "advanced", False

    # Group C -- General's sequential group.
    if p == 1 and s == 3:
        return "C", "general", False

    # Group D -- Technician's sequential group, and Novice's before it closed.
    if p == 2 and s == 3:
        return "D", "technician", False

    return None


def _looks_us(prefix: str) -> bool:
    if len(prefix) == 1:
        return prefix in _SINGLE_PREFIXES
    if prefix[0] == "A":
        return prefix[1] in _A_SECOND
    return prefix[0] in _DOUBLE_FIRST


def guess_class(callsign: str, table: PrefixTable | None = None) -> LicenceGuess | None:
    """Best guess at a US operator's licence class, or None if we cannot tell.

    Pass a prefix table to reject non-US callsigns that happen to match the US
    shape -- there are plenty, and guessing at one would be worse than silence.
    """
    call = base_call(callsign or "")
    match = _US_CALL.match(call)
    if not match:
        return None

    prefix, _digit, suffix = match.groups()
    if not _looks_us(prefix):
        return None

    if table is not None:
        entity = table.lookup(call)
        if entity is None or entity.name not in US_ENTITIES:
            return None

    classified = _classify_format(prefix, suffix)
    if classified is None:
        return None
    group, klass, certain = classified

    if certain:
        reason = f"{call} is a Group {group} callsign, which only an Amateur Extra may hold"
    else:
        reason = (
            f"{call} is a Group {group} callsign — most likely {klass}, "
            f"but a higher class may hold one by vanity"
        )
    return LicenceGuess(klass=klass, group=group, certain=certain, reason=reason)

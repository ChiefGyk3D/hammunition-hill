# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""ADIF log parsing and the worked/needed index.

This is the feature a hosted dashboard structurally cannot have. Your log is on
your disk; a cloud service has to ask you to upload it. We just read it.

The index answers one question fast, for every spot on the screen: *have I
worked this entity, on this band, in this mode?* Everything else about the log
is deliberately ignored -- we are not building a logger.

**Entities are resolved by running the logged callsign through the same prefix
table the spots use.** Not the log's own DXCC or COUNTRY field. Those are often
absent, sometimes disagree between logging programs, and would give "needed" a
different notion of entity than the spot has. Consistency matters more than
authority here: if the prefix table is wrong about an entity, it is wrong the
same way on both sides and the comparison still holds.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .prefix import PrefixTable

log = logging.getLogger(__name__)

# <NAME:LENGTH> or <NAME:LENGTH:TYPE>, case-insensitive, as ADIF specifies.
_FIELD = re.compile(r"<([A-Za-z_0-9]+):(\d+)(?::[A-Za-z])?>", re.ASCII)
_EOH = re.compile(r"<EOH>", re.IGNORECASE)
_EOR = re.compile(r"<EOR>", re.IGNORECASE)

# Fields we keep. An ADIF record can carry a hundred; we need five.
_WANTED = frozenset({"CALL", "BAND", "MODE", "SUBMODE", "QSO_DATE", "QSL_RCVD", "LOTW_QSL_RCVD"})

# Modes that count as the same slot for award purposes. An operator chasing
# DXCC on "digital" does not care whether it was FT8 or RTTY, and one chasing
# phone does not care whether it was SSB or FM.
_MODE_GROUPS: dict[str, str] = {
    "SSB": "PHONE",
    "USB": "PHONE",
    "LSB": "PHONE",
    "AM": "PHONE",
    "FM": "PHONE",
    "CW": "CW",
    "FT8": "DIGITAL",
    "FT4": "DIGITAL",
    "JT65": "DIGITAL",
    "JT9": "DIGITAL",
    "RTTY": "DIGITAL",
    "PSK31": "DIGITAL",
    "PSK": "DIGITAL",
    "MFSK": "DIGITAL",
    "OLIVIA": "DIGITAL",
    "JS8": "DIGITAL",
    "Q65": "DIGITAL",
    "MSK144": "DIGITAL",
    "DATA": "DIGITAL",
    "DIGITALVOICE": "DIGITAL",
}


def mode_group(mode: str | None) -> str | None:
    """Collapse a mode to the slot operators actually chase."""
    if not mode:
        return None
    return _MODE_GROUPS.get(mode.strip().upper(), mode.strip().upper())


def normalize_band(band: str | None) -> str | None:
    """ADIF writes bands as '20M'; we use '20m' everywhere else."""
    if not band:
        return None
    return band.strip().lower()


def parse_adif(text: str) -> Iterator[dict[str, str]]:
    """Yield one dict per QSO record.

    Tolerant by design. Logs come from a dozen programs and decades of history;
    a malformed record should cost you that record, not the whole file.
    """
    header_end = _EOH.search(text)
    body = text[header_end.end() :] if header_end else text

    record: dict[str, str] = {}
    position = 0
    while position < len(body):
        match = _FIELD.search(body, position)
        end_of_record = _EOR.search(body, position)

        if end_of_record and (not match or end_of_record.start() < match.start()):
            if record:
                yield record
            record = {}
            position = end_of_record.end()
            continue

        if not match:
            break

        name = match.group(1).upper()
        try:
            length = int(match.group(2))
        except ValueError:  # pragma: no cover - regex guarantees digits
            break
        value_start = match.end()
        value = body[value_start : value_start + length]
        if name in _WANTED:
            record[name] = value.strip()
        position = value_start + length

    if record:
        yield record


@dataclass
class LogIndex:
    """What has been worked, in the shapes the spot list needs to ask about."""

    entities: set[str] = field(default_factory=set)
    entity_band: set[tuple[str, str]] = field(default_factory=set)
    entity_mode: set[tuple[str, str]] = field(default_factory=set)
    entity_band_mode: set[tuple[str, str, str]] = field(default_factory=set)
    confirmed_entities: set[str] = field(default_factory=set)
    qso_count: int = 0
    unresolved: int = 0

    def add(self, entity: str, band: str | None, mode: str | None, confirmed: bool) -> None:
        self.entities.add(entity)
        if confirmed:
            self.confirmed_entities.add(entity)
        group = mode_group(mode)
        if band:
            self.entity_band.add((entity, band))
        if group:
            self.entity_mode.add((entity, group))
        if band and group:
            self.entity_band_mode.add((entity, band, group))

    def status(self, entity: str | None, band: str | None, mode: str | None) -> dict[str, bool]:
        """How badly do you want this spot?

        Three independent answers rather than one score, because operators chase
        different things and the UI colours them differently:

        - ``new_entity``  -- never worked at all. Drop everything.
        - ``new_band``    -- worked, but not on this band. A band slot.
        - ``new_mode``    -- worked, but not in this mode group.
        """
        if not entity:
            return {"new_entity": False, "new_band": False, "new_mode": False, "known": False}

        group = mode_group(mode)
        new_entity = entity not in self.entities
        return {
            "new_entity": new_entity,
            "new_band": bool(band) and (entity, band) not in self.entity_band,
            "new_mode": bool(group) and (entity, group) not in self.entity_mode,
            "confirmed": entity in self.confirmed_entities,
            "known": True,
        }

    def worked_summary(self) -> dict[str, object]:
        """Worked and confirmed entities, for the callsign panel.

        Entity names only -- a few hundred strings. The per-band and per-mode
        slots stay server-side; publishing those would be a much larger payload
        for a panel that only needs "have I worked this place".
        """
        return {
            "entities": sorted(self.entities),
            "confirmed": sorted(self.confirmed_entities),
        }


def _is_confirmed(record: dict[str, str]) -> bool:
    return (
        record.get("QSL_RCVD", "").upper() == "Y" or record.get("LOTW_QSL_RCVD", "").upper() == "Y"
    )


def build_index(text: str, table: PrefixTable) -> LogIndex:
    """Parse a log and index it."""
    index = LogIndex()
    for record in parse_adif(text):
        call = record.get("CALL")
        if not call:
            continue
        index.qso_count += 1

        entity = table.lookup(call)
        if entity is None:
            index.unresolved += 1
            continue

        index.add(
            entity.name,
            normalize_band(record.get("BAND")),
            record.get("SUBMODE") or record.get("MODE"),
            _is_confirmed(record),
        )
    return index


def load_index(path: Path, table: PrefixTable) -> LogIndex:
    """Read and index a log file. Errors are logged, never fatal."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("could not read log %s: %s", path, exc)
        return LogIndex()

    index = build_index(text, table)
    log.info(
        "indexed %s: %d QSOs, %d entities, %d band-slots (%d callsigns unresolved)",
        path,
        index.qso_count,
        len(index.entities),
        len(index.entity_band),
        index.unresolved,
    )
    return index

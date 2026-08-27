# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The FCC ULS bulk amateur database, imported into a local index.

This is the only provider with **no per-lookup network at all**, which is what
makes it the right one for a portable station. Once the index is on disk, every
US callsign resolves from local storage: no account, no rate limit, no third
party learning who you are working, and it keeps working at a park with no
signal. It is also authoritative for operator class, which turns the Band Plan
panel's licence-class guess into a fact for US calls.

The costs are real and worth stating: a ~160 MB download and a few hundred MB of
extracted text to chew through, which matters on a Pi with an SD card. It is
also US only, which is why it belongs in a chain rather than on its own.

**SQLite rather than a JSON blob, and streamed rather than buffered.** There are
roughly 800,000 active US amateur licences. An earlier version of this collected
them into a dict and wrote the database at the end, which measured at ~770 bytes
per record -- around 620 MB of peak memory at full scale. That is more RAM than a
Pi Zero has and most of a Pi 3's, for a feature meant to run in the background.

So each pass writes straight through to the database in batches, and peak memory
is one batch rather than one country. It is slower, and it is the difference
between running on the hardware people actually put in a shack and not.

Import is a deliberate command rather than something the collector does on a
timer -- a 160 MB fetch should not happen unattended on a metered hotspot.

## The file format

The archive holds pipe-delimited ``.dat`` files, one record per line, positional
fields, per the FCC's published ULS layouts. Three matter:

- ``HD.dat`` -- licence header: status, grant and expiry dates
- ``EN.dat`` -- entity: name and address
- ``AM.dat`` -- amateur-specific: operator class

All three carry the callsign, so this keys on the callsign directly rather than
joining on the system identifier. One less thing to get wrong, and it degrades
better: a malformed ``AM`` line costs one licence its operator class instead of
breaking a join.

The passes run in that order for a reason. ``HD`` inserts the active licences;
``EN`` and ``AM`` then *update* rows that already exist. An entity record for an
expired licence updates nothing and is discarded by the database rather than by
us -- the status filter applies itself to the later passes for free.

Parsing is positional because the format is, but every line is checked for its
record-type tag before its fields are read, and anything short or mistagged is
counted and skipped rather than raising. The importer prints what it saw --
records read per file, callsigns indexed, lines skipped -- because a positional
parser against a format you cannot re-verify should show its working.
"""

from __future__ import annotations

import logging
import sqlite3
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# The FCC rebuilds the complete amateur file early Sunday morning.
ULS_COMPLETE_URL = "https://data.fcc.gov/download/pub/uls/complete/l_amat.zip"
ULS_HOST = "data.fcc.gov"

DEFAULT_DB_NAME = "fcc_uls.sqlite3"

# Field positions, per the FCC ULS record layouts. Named rather than inlined so
# a layout change is one edit in one visible place.
HD_CALLSIGN, HD_STATUS, HD_SERVICE, HD_GRANT, HD_EXPIRES = 4, 5, 6, 7, 8
EN_CALLSIGN, EN_TYPE, EN_NAME, EN_FIRST, EN_LAST = 4, 5, 7, 8, 10
EN_STREET, EN_CITY, EN_STATE, EN_ZIP = 15, 16, 17, 18
AM_CALLSIGN, AM_CLASS = 4, 5

# ULS operator class codes -> the names used everywhere else in this project.
# All six appear, including the two no longer issued: Novice and Advanced
# licences that were never let lapse are still held and still on the air.
OPERATOR_CLASS = {
    "N": "Novice",
    "T": "Technician",
    "P": "Technician Plus",
    "G": "General",
    "A": "Advanced",
    "E": "Amateur Extra",
}

# Licence status. Only active licences are worth indexing -- an expired record
# answers "who was this" and the panel is asking "who is this".
STATUS_ACTIVE = "A"

# Rows per transaction during import. Large enough that the per-transaction cost
# disappears, small enough that peak memory is measured in megabytes.
BATCH = 10_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS licences (
    callsign      TEXT PRIMARY KEY,
    name          TEXT,
    operator_class TEXT,
    city          TEXT,
    state         TEXT,
    zip           TEXT,
    status        TEXT,
    granted       TEXT,
    expires       TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@dataclass
class ImportStats:
    """What the importer actually saw, so a bad parse is visible immediately."""

    hd_records: int = 0
    en_records: int = 0
    am_records: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    indexed: int = 0
    inactive: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def report(self) -> str:
        lines = [
            f"  HD (licence header) : {self.hd_records:>9,} records",
            f"  EN (entity/name)    : {self.en_records:>9,} records",
            f"  AM (operator class) : {self.am_records:>9,} records",
            f"  indexed             : {self.indexed:>9,} active callsigns",
            f"  skipped (inactive)  : {self.inactive:>9,}",
        ]
        for reason, count in sorted(self.skipped.items()):
            lines.append(f"  skipped ({reason}) : {count:>9,}")
        return "\n".join(lines)


def _fields(line: str) -> list[str]:
    return [part.strip() for part in line.rstrip("\n\r").split("|")]


def _person_name(parts: list[str]) -> str:
    """A displayable name from whichever of the entity fields are populated.

    Clubs and trustees populate ``entity_name``; individuals populate first and
    last. Both forms occur in the same file.
    """
    entity = parts[EN_NAME] if len(parts) > EN_NAME else ""
    if entity:
        return entity
    first = parts[EN_FIRST] if len(parts) > EN_FIRST else ""
    last = parts[EN_LAST] if len(parts) > EN_LAST else ""
    return " ".join(part for part in (first, last) if part)


def _lines(archive: zipfile.ZipFile, member: str) -> Iterator[str]:
    """Stream one .dat file. Never read whole -- EN.dat alone is hundreds of MB."""
    try:
        handle = archive.open(member)
    except KeyError:
        log.warning("%s not present in archive", member)
        return
    with handle as raw:
        for chunk in raw:
            # The FCC files are Latin-1 in practice and contain names that are
            # not ASCII. Replacing beats aborting an 800,000-line import.
            yield chunk.decode("latin-1", errors="replace")


def build_index(zip_path: Path, db_path: Path) -> ImportStats:
    """Read l_amat.zip and write a callsign-keyed SQLite index.

    Three streaming passes, each writing through to the database in batches.
    Nothing accumulates in memory across a pass, which is what keeps this
    runnable on a Pi -- see the module docstring for the measurement that
    forced the design.

    Written to a temporary file and renamed over the target, the same
    atomic-replace rule the snapshots follow: an interrupted import must not
    leave a dashboard querying a half-built index.
    """
    stats = ImportStats()

    if not zipfile.is_zipfile(zip_path):
        raise ValueError(
            f"{zip_path} is not a zip archive. Expected the FCC's l_amat.zip "
            f"from {ULS_COMPLETE_URL}"
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".building")
    tmp.unlink(missing_ok=True)

    connection = sqlite3.connect(tmp)
    try:
        # This file is disposable until the final rename, so durability during
        # the build buys nothing and costs a great deal of time on an SD card.
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.executescript(SCHEMA)

        with zipfile.ZipFile(zip_path) as archive:
            names = {name.upper(): name for name in archive.namelist()}
            _pass_hd(connection, archive, names, stats)
            _pass_en(connection, archive, names, stats)
            _pass_am(connection, archive, names, stats)

        stats.indexed = connection.execute("SELECT COUNT(*) FROM licences").fetchone()[0]
        _write_meta(connection, stats)
        connection.commit()
    finally:
        connection.close()

    tmp.replace(db_path)
    return stats


def _batched(connection: sqlite3.Connection, statement: str, rows: Iterator[tuple]) -> None:
    """Execute in fixed-size transactions so peak memory is one batch."""
    batch: list[tuple] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= BATCH:
            connection.executemany(statement, batch)
            connection.commit()
            batch.clear()
    if batch:
        connection.executemany(statement, batch)
        connection.commit()


def _pass_hd(
    connection: sqlite3.Connection,
    archive: zipfile.ZipFile,
    names: dict[str, str],
    stats: ImportStats,
) -> None:
    """Insert the active licences. Everything later updates these rows."""

    def rows() -> Iterator[tuple]:
        for line in _lines(archive, names.get("HD.DAT", "HD.dat")):
            parts = _fields(line)
            if not parts or parts[0] != "HD":
                stats.skip("not an HD record")
                continue
            stats.hd_records += 1
            if len(parts) <= HD_EXPIRES:
                stats.skip("HD line too short")
                continue
            callsign = parts[HD_CALLSIGN].upper()
            if not callsign:
                continue
            if parts[HD_STATUS] != STATUS_ACTIVE:
                stats.inactive += 1
                continue
            yield (
                callsign,
                parts[HD_STATUS],
                parts[HD_GRANT] or None,
                parts[HD_EXPIRES] or None,
            )

    _batched(
        connection,
        "INSERT OR REPLACE INTO licences (callsign, status, granted, expires) VALUES (?, ?, ?, ?)",
        rows(),
    )


def _pass_en(
    connection: sqlite3.Connection,
    archive: zipfile.ZipFile,
    names: dict[str, str],
    stats: ImportStats,
) -> None:
    """Add names and locations to licences that exist.

    An UPDATE against a callsign with no row is a no-op, so entity records for
    expired licences filter themselves out without a lookup on our side.
    """

    def rows() -> Iterator[tuple]:
        for line in _lines(archive, names.get("EN.DAT", "EN.dat")):
            parts = _fields(line)
            if not parts or parts[0] != "EN":
                stats.skip("not an EN record")
                continue
            stats.en_records += 1
            if len(parts) <= EN_ZIP:
                stats.skip("EN line too short")
                continue
            # The street address is read past and deliberately never stored.
            # A wall display does not need somebody's house number, and every
            # viewer on the LAN can read whatever ends up in a snapshot.
            yield (
                _person_name(parts) or None,
                parts[EN_CITY] or None,
                parts[EN_STATE] or None,
                parts[EN_ZIP] or None,
                parts[EN_CALLSIGN].upper(),
            )

    _batched(
        connection,
        "UPDATE licences SET name = ?, city = ?, state = ?, zip = ? WHERE callsign = ?",
        rows(),
    )


def _pass_am(
    connection: sqlite3.Connection,
    archive: zipfile.ZipFile,
    names: dict[str, str],
    stats: ImportStats,
) -> None:
    """Add the operator class, which is the field nothing else can give us."""

    def rows() -> Iterator[tuple]:
        for line in _lines(archive, names.get("AM.DAT", "AM.dat")):
            parts = _fields(line)
            if not parts or parts[0] != "AM":
                stats.skip("not an AM record")
                continue
            stats.am_records += 1
            if len(parts) <= AM_CLASS:
                stats.skip("AM line too short")
                continue
            yield (
                OPERATOR_CLASS.get(parts[AM_CLASS].upper()),
                parts[AM_CALLSIGN].upper(),
            )

    _batched(
        connection,
        "UPDATE licences SET operator_class = ? WHERE callsign = ?",
        rows(),
    )


def _write_meta(connection: sqlite3.Connection, stats: ImportStats) -> None:
    from datetime import UTC, datetime

    connection.executemany(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        [
            ("imported_at", datetime.now(UTC).isoformat().replace("+00:00", "Z")),
            ("callsigns", str(stats.indexed)),
            ("source", ULS_COMPLETE_URL),
        ],
    )


class UlsIndex:
    """Read-only queries against an imported index."""

    def __init__(self, db_path: Path) -> None:
        self.path = db_path
        self._connection: sqlite3.Connection | None = None

    @property
    def available(self) -> bool:
        return self.path.is_file()

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            # Opened read-only via URI so a query cannot modify the index, and
            # check_same_thread=False because the collector may resolve from a
            # worker thread. Reads are safe across threads; we never write here.
            self._connection = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True, check_same_thread=False
            )
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def meta(self) -> dict[str, str]:
        if not self.available:
            return {}
        try:
            rows = self._connect().execute("SELECT key, value FROM meta").fetchall()
        except sqlite3.Error as exc:
            log.warning("could not read ULS index metadata: %s", exc)
            return {}
        return {row["key"]: row["value"] for row in rows}

    def lookup(self, callsign: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            row = (
                self._connect()
                .execute("SELECT * FROM licences WHERE callsign = ?", (callsign.upper(),))
                .fetchone()
            )
        except sqlite3.Error as exc:
            log.warning("ULS lookup failed for %s: %s", callsign, exc)
            return None
        return dict(row) if row else None

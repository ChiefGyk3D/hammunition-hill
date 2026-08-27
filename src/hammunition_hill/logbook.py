# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Writing QSOs to ADIF files.

Each logbook is a plain ADIF file we append complete records to. No database, no
proprietary format: your log stays readable by every other program in the hobby,
you can back it up with ``cp``, and if you outgrow this you open the same file in
a real logger with nothing to export.

It also closes a loop. The ADIF reader that powers needed-slot spot colouring
reads these same files, so logging a new entity here makes the spot list stop
calling it new on the next cycle -- no synchronisation step, because both halves
are looking at the same bytes.

**Append-only.** There is no edit and no delete, here or over HTTP. That is a
security property as much as a simplicity one: the worst outcome of a
successful attack on the write endpoint is junk records in a text file you can
open and fix, rather than a destroyed log. Corrections are made in a real
logger, or in a text editor.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ADIF_VERSION = "3.1.4"
PROGRAM_ID = "hammunition-hill"

# Fields we write, in the order they appear in a record. Anything not on this
# list is dropped rather than passed through -- a log file is not a place to put
# arbitrary caller-supplied keys.
FIELDS: tuple[str, ...] = (
    "CALL",
    "QSO_DATE",
    "TIME_ON",
    "BAND",
    "MODE",
    "SUBMODE",
    "FREQ",
    "RST_SENT",
    "RST_RCVD",
    "GRIDSQUARE",
    "NAME",
    "QTH",
    "STATE",
    "COUNTRY",
    "TX_PWR",
    "COMMENT",
    "MY_GRIDSQUARE",
    "STATION_CALLSIGN",
    "OPERATOR",
)

REQUIRED = ("CALL",)

# Per-field caps. ADIF has no limit; a log file does not need one either, but an
# endpoint that accepts input does.
MAX_FIELD_CHARS = 128
MAX_COMMENT_CHARS = 256

_CALLSIGN = re.compile(r"^[A-Z0-9/]{3,20}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DATE = re.compile(r"^\d{8}$")
_TIME = re.compile(r"^\d{4,6}$")


class LogbookError(Exception):
    """The record could not be written. Message is safe to show a user."""


@dataclass(frozen=True)
class Logbook:
    id: str
    name: str
    path: Path
    primary: bool = False
    station_callsign: str | None = None


def _clean(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    """Strip control characters and cap length.

    ADIF is length-prefixed rather than delimited, so a stray character cannot
    break the format the way it would in CSV -- but control characters in a log
    file are still junk, and an unbounded field is still a way to fill a disk.
    """
    text = _CONTROL.sub("", str(value)).strip()
    return text[:limit]


def _encode_field(name: str, value: str) -> str:
    """``<NAME:len>value``, where len is the length in bytes, as ADIF specifies."""
    return f"<{name}:{len(value.encode('utf-8'))}>{value}"


def normalize(record: dict[str, Any], book: Logbook, station: dict[str, Any]) -> dict[str, str]:
    """Validate and fill in a QSO, or raise LogbookError.

    Anything the operator did not supply that we already know -- their callsign,
    their grid, the time -- is filled in here rather than being asked for.
    """
    out: dict[str, str] = {}

    for key, raw in record.items():
        field = str(key).upper()
        if field not in FIELDS:
            continue
        limit = MAX_COMMENT_CHARS if field == "COMMENT" else MAX_FIELD_CHARS
        cleaned = _clean(raw, limit)
        if cleaned:
            out[field] = cleaned

    call = out.get("CALL", "").upper()
    if not call:
        raise LogbookError("a QSO needs a callsign")
    if not _CALLSIGN.match(call):
        raise LogbookError(f"{call!r} is not a plausible callsign")
    out["CALL"] = call

    now = datetime.now(UTC)
    out.setdefault("QSO_DATE", now.strftime("%Y%m%d"))
    out.setdefault("TIME_ON", now.strftime("%H%M%S"))

    if not _DATE.match(out["QSO_DATE"]):
        raise LogbookError("QSO_DATE must be YYYYMMDD")
    if not _TIME.match(out["TIME_ON"]):
        raise LogbookError("TIME_ON must be HHMM or HHMMSS")

    # ADIF wants bands lowercase with the unit, and modes uppercase.
    if "BAND" in out:
        out["BAND"] = out["BAND"].lower()
    for field in ("MODE", "SUBMODE", "GRIDSQUARE", "MY_GRIDSQUARE"):
        if field in out:
            out[field] = out[field].upper()

    station_call = book.station_callsign or station.get("callsign")
    if station_call:
        out.setdefault("STATION_CALLSIGN", str(station_call).upper())
    if station.get("grid"):
        out.setdefault("MY_GRIDSQUARE", str(station["grid"]).upper())

    return out


def render_record(fields: dict[str, str]) -> str:
    """One ADIF record, fields in a stable order."""
    parts = [_encode_field(name, fields[name]) for name in FIELDS if name in fields]
    return " ".join(parts) + " <EOR>\n"


def _header() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d %H%M%S")
    return (
        f"ADIF export from {PROGRAM_ID}\n"
        f"{_encode_field('ADIF_VER', ADIF_VERSION)}\n"
        f"{_encode_field('PROGRAMID', PROGRAM_ID)}\n"
        f"{_encode_field('CREATED_TIMESTAMP', stamp)}\n"
        "<EOH>\n"
    )


def append(book: Logbook, fields: dict[str, str]) -> Path:
    """Append one record, creating the file with a header if it is new."""
    path = book.path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8") as handle:
        if new_file:
            handle.write(_header())
        handle.write(render_record(fields))
    return path


def log_qso(book: Logbook, record: dict[str, Any], station: dict[str, Any]) -> dict[str, str]:
    """Validate and append. Returns what was actually written."""
    fields = normalize(record, book, station)
    append(book, fields)
    log.info("logged %s in %s", fields["CALL"], book.id)
    return fields


def recent(book: Logbook, limit: int = 20) -> list[dict[str, str]]:
    """The last few QSOs from a logbook, newest first.

    Reads the tail rather than the whole file: a long log is megabytes and this
    runs on every panel poll.
    """
    from .adif import parse_adif

    path = book.path.expanduser()
    if not path.is_file():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            window = min(size, 64 * 1024)
            handle.seek(size - window)
            text = handle.read().decode("utf-8", errors="replace")
    except OSError as exc:
        log.warning("could not read %s: %s", path, exc)
        return []

    # A partial first record from cutting mid-file is dropped by starting after
    # the first record separator we find.
    if window < size:
        marker = text.upper().find("<EOR>")
        text = text[marker + 5 :] if marker != -1 else text

    records = list(parse_adif(text))
    return list(reversed(records[-limit:]))

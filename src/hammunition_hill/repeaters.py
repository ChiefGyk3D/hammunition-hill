# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The repeaters panel's data: Hammunition's repeater layers, read back.

Tier 0. The engine (Hammunition) already holds the operator's repeater layers
on this disk -- an import of their own export, an OpenStreetMap extraction, a
RepeaterBook fetch they chose to run. This module runs two of its read-only
commands, joins what they say with the station's grid square, and hands the
collector one snapshot. Nothing is fetched from anyone: the engine's layers are
the only source, and a machine with no engine, or no layers, gets an empty
state that says which command to run.

**Who may be served what.** A ``personal_use`` row is RepeaterBook's, whose
terms keep it on the machine that fetched it (Hammunition D-081). The snapshot
on disk holds those rows, because this machine's own page shows them. The
server answers anyone else through :func:`public_data`, which removes them, and
the layer and the credit that name RepeaterBook with them. Nothing in Hill
exports rows, and a test holds that.

**What the collector may run.** Exactly :data:`LIST_ARGV` and
:data:`STATION_ARGV`. Both are read-only; a front end never drives a command
that changes the machine (Hammunition D-059), and the operator's terminal is
where ``import`` and ``fetch-*`` run.
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .bands import BAND_ORDER, band_for
from .geo import GridError, bearing_deg, distance_km, grid_to_latlon

log = logging.getLogger(__name__)

ENGINE = "hammunition"
LIST_ARGV: tuple[str, ...] = ("maps", "repeaters", "list", "--json")
STATION_ARGV: tuple[str, ...] = ("station", "show", "--json")

# The interface version this reads. A major it does not know is refused by
# name, which is what the engine's own document asks of a front end.
SCHEMA_MAJOR = "hammunition/1"

# The engine answers from local files; ten seconds is generous, and a hang
# must not hold the collector's thread.
ENGINE_TIMEOUT_SECONDS = 20.0

# A country's worth of repeaters is some thousands of rows and the snapshot is
# read by a browser every poll. The nearest are kept; the cut is counted so the
# panel can say so. 6000 rows is roughly 1.5 MB.
MAX_ROWS = 6000

# Rows of areas the engine has not activated are carried beside the active
# ones, so a chip can add an area for one browser session without a second
# trip to the engine. They are a separate, smaller list: the map and every
# other reader of `rows` see the active areas only, and a large inactive area
# can never crowd an active one out of the cut.
INACTIVE_MAX_ROWS = 3000

# The engine's mode vocabulary, in its order (Hammunition's `repeaters.MODES`),
# and the digital details a source may supply. Anything else in a document is
# dropped: a front end shows what the engine promises, not what it happens to
# print.
MODES: tuple[str, ...] = ("FM", "DMR", "D-STAR", "YSF", "P25", "NXDN", "M17", "TETRA", "ATV")
DIGITAL_KEYS: tuple[str, ...] = (
    "dmr_color_code",
    "dmr_network",
    "dmr_id",
    "dstar_module",
    "dstar_gateway",
    "ysf_dgid",
    "p25_nac",
    "nxdn_ran",
)

# Stored per row. Notes, labels, status and update dates are in the engine's
# document and not on this panel: carrying them would only make the file the
# browser polls larger.
_ROW_FIELDS = (
    "callsign",
    "output_hz",
    "offset_hz",
    "tone",
    "mode",
    "place",
    "use",
    "lat",
    "lon",
    "source",
    "also",
    "layer",
    "personal_use",
)

IMPORT_HINT = (
    "import your own export with `hammunition maps repeaters import FILE`, or fetch "
    "with your own RepeaterBook token with "
    "`hammunition maps repeaters fetch-repeaterbook --state CODE`"
)

_PERSONAL_WORD = "repeaterbook"


class EngineError(Exception):
    """The engine could not give a document. The reason is safe to display."""


def find_engine() -> str | None:
    """The engine's executable: on PATH, else where its bootstrap links it."""
    found = shutil.which(ENGINE)
    if found:
        return found
    linked = Path.home() / ".local" / "bin" / ENGINE
    if linked.is_file():
        return str(linked)
    return None


def run_engine(
    exe: str, args: Sequence[str], timeout: float = ENGINE_TIMEOUT_SECONDS
) -> dict[str, Any]:
    """Run one engine command and parse the one JSON document it prints.

    Neither stdout nor stderr of a failing run is quoted back: the station
    document holds a callsign and a grid square, and an error message is
    exactly where a program ends up logging what it was never meant to.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell, never operator-supplied
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"{ENGINE} did not answer within {timeout:g} s") from exc
    except OSError as exc:
        raise EngineError(f"could not start {ENGINE}: {exc.strerror or 'failed'}") from exc
    if done.returncode != 0:
        raise EngineError(f"{ENGINE} {args[0]} exited {done.returncode}")
    try:
        document = json.loads(done.stdout)
    except ValueError as exc:
        raise EngineError(f"{ENGINE} {args[0]} did not print JSON") from exc
    if not isinstance(document, dict):
        raise EngineError(f"{ENGINE} {args[0]} printed JSON that is not a document")
    return document


def band_for_hz(hz: int | float) -> str | None:
    if not hz or hz <= 0:
        return None
    return band_for(hz / 1000.0)


def unavailable(reason: str) -> dict[str, Any]:
    """The empty state: nothing to show, and what to run."""
    return {
        "available": False,
        "reason": reason,
        "grid": None,
        "station": None,
        "distance_note": "",
        "layers": [],
        "skipped": [],
        "rows": [],
        "other_rows": [],
        "other_truncated": 0,
        "areas": [],
        "has_areas": False,
        "bands": [],
        "modes": [],
        "has_modes": False,
        "merged": 0,
        "credits": [],
        "truncated": 0,
        "has_personal_use": False,
    }


def _station_point(
    station: Mapping[str, Any] | None, fallback_latlon: tuple[float, float] | None
) -> tuple[str | None, tuple[float, float] | None]:
    """The grid square and the point distances are measured from.

    The engine's saved grid square wins: it is the one value the operator set
    for every program. Hill's own configured station is the fallback, so a
    dashboard that already knows where it is does not lose distances because
    the engine has no station yet.
    """
    grid = station.get("grid_square") if station else None
    if isinstance(grid, str) and grid.strip():
        try:
            return grid.strip(), grid_to_latlon(grid)
        except GridError:
            log.warning("repeaters: the engine's grid square is not a Maidenhead locator")
    return None, fallback_latlon


def _modes_of(value: Any) -> list[str]:
    """The vocabulary's modes in the engine's order; nothing else, never a guess."""
    if not isinstance(value, list):
        return []
    named = {m for m in value if isinstance(m, str)}
    return [m for m in MODES if m in named]


def _digital_of(value: Any) -> dict[str, str]:
    """Only the documented keys, only non-empty strings."""
    if not isinstance(value, Mapping):
        return {}
    return {
        key: value[key].strip()
        for key in DIGITAL_KEYS
        if isinstance(value.get(key), str) and value[key].strip()
    }


def _row_of(raw: Mapping[str, Any], origin: tuple[float, float] | None) -> dict[str, Any] | None:
    try:
        lat, lon = float(raw["lat"]), float(raw["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    row: dict[str, Any] = {key: raw.get(key) for key in _ROW_FIELDS}
    row["lat"], row["lon"] = lat, lon
    row["output_hz"] = int(raw.get("output_hz") or 0)
    row["also"] = [str(a) for a in raw.get("also") or []]
    row["personal_use"] = bool(raw.get("personal_use"))
    row["band"] = band_for_hz(row["output_hz"])
    row["modes"] = _modes_of(raw.get("modes"))
    row["digital"] = _digital_of(raw.get("digital"))
    if origin is None:
        row["km"] = None
        row["bearing"] = None
    else:
        row["km"] = round(distance_km(origin[0], origin[1], lat, lon), 1)
        row["bearing"] = round(bearing_deg(origin[0], origin[1], lat, lon), 1)
    return row


def _areas_of(
    layers: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The areas the layers belong to, in layer order, each with its middle.

    The middle is the mean of its rows' positions: a state's repeaters spread
    over the state, and the engine carries no boundary to take a centroid of.
    An area with no row has no middle (null), and the panel never centres on it.
    """
    areas: dict[str, dict[str, Any]] = {}
    for layer in layers:
        area = layer.get("area")
        if not isinstance(area, str) or not area:
            continue
        entry = areas.setdefault(
            area, {"area": area, "active": False, "layers": [], "rows": 0, "centre": None}
        )
        entry["layers"].append(str(layer.get("id", "")))
        entry["active"] = entry["active"] or layer.get("active") is not False
        entry["rows"] += int(layer.get("rows") or 0)
    for entry in areas.values():
        mine = [r for r in rows if r["layer"] in entry["layers"]]
        if mine:
            entry["centre"] = {
                "lat": round(sum(r["lat"] for r in mine) / len(mine), 4),
                "lon": round(sum(r["lon"] for r in mine) / len(mine), 4),
            }
    return list(areas.values())


def build_data(
    listing: Mapping[str, Any],
    station: Mapping[str, Any] | None,
    *,
    fallback_latlon: tuple[float, float] | None = None,
    max_rows: int = MAX_ROWS,
) -> dict[str, Any]:
    """One snapshot payload from a ``repeaters-list`` and a ``station`` document."""
    problem = _document_problem(listing, "repeaters-list")
    if problem:
        return unavailable(problem)

    layers = [layer for layer in listing.get("layers") or [] if isinstance(layer, Mapping)]
    skipped = [
        {"layer": str(s.get("layer", "")), "reason": str(s.get("reason", ""))}
        for s in listing.get("skipped") or []
        if isinstance(s, Mapping)
    ]
    if not layers:
        reason = "no repeater layers on this machine — " + IMPORT_HINT
        if skipped:
            left_out = "; ".join(f"{s['layer']}: {s['reason']}" for s in skipped)
            reason = f"no repeater layer could be read ({left_out}) — " + IMPORT_HINT
        return unavailable(reason)

    grid, origin = _station_point(station, fallback_latlon)

    all_rows = [
        r
        for raw in listing.get("rows") or []
        if isinstance(raw, Mapping) and (r := _row_of(raw, origin)) is not None
    ]
    # An engine that predates areas (Hammunition D-082) prints no `active` on a
    # layer: everything is then active, and the panel hides the area chips.
    has_areas = any(isinstance(layer.get("active"), bool) for layer in layers)
    inactive_ids: set[str] = {
        str(layer.get("id", "")) for layer in layers if layer.get("active") is False
    }
    areas = _areas_of(layers, all_rows)
    rows = [r for r in all_rows if r["layer"] not in inactive_ids]
    other_rows = [r for r in all_rows if r["layer"] in inactive_ids]
    # Nearest first, which is what the panel is for. With no origin the
    # engine's order stands: sorting on an absent distance would only shuffle.
    if origin is not None:
        rows.sort(key=lambda r: (r["km"], r["callsign"] or ""))
        other_rows.sort(key=lambda r: (r["km"], r["callsign"] or ""))
    truncated = max(0, len(rows) - max_rows)
    rows = rows[:max_rows]
    other_truncated = max(0, len(other_rows) - INACTIVE_MAX_ROWS)
    other_rows = other_rows[:INACTIVE_MAX_ROWS]

    shown = rows + other_rows
    present = {r["band"] for r in shown if r["band"]}
    bands = [b for b in BAND_ORDER if b in present]
    modes_present = {m for r in shown for m in r["modes"]}
    # An engine that predates the vocabulary prints neither `centre` nor a
    # `modes` list on its rows; the panel then hides the chips and says so.
    has_modes = "centre" in listing or any(
        isinstance(raw, Mapping) and isinstance(raw.get("modes"), list)
        for raw in listing.get("rows") or []
    )

    return {
        "available": True,
        "reason": "",
        "grid": grid,
        "station": {"lat": origin[0], "lon": origin[1]} if origin else None,
        "distance_note": (
            ""
            if origin
            else "no grid square is set, so distance and bearing are not shown — "
            "set one with `hammunition station set --grid-square GRID`"
        ),
        "layers": [
            {
                "id": str(layer.get("id", "")),
                "area": layer["area"] if isinstance(layer.get("area"), str) else None,
                "active": layer.get("active") is not False,
                "name": str(layer.get("name", "")),
                "day": str(layer.get("day", "")),
                "rows": int(layer.get("rows") or 0),
                "sources": [str(s) for s in layer.get("sources") or []],
                "personal_use": bool(layer.get("personal_use")),
                "unverified": bool(layer.get("unverified")),
            }
            for layer in layers
        ],
        "skipped": skipped,
        "rows": rows,
        "other_rows": other_rows,
        "other_truncated": other_truncated,
        "areas": areas,
        "has_areas": has_areas,
        "bands": bands,
        "modes": [m for m in MODES if m in modes_present],
        "has_modes": has_modes,
        "merged": int(listing.get("merged") or 0),
        "credits": [str(c) for c in listing.get("credits") or []],
        "truncated": truncated,
        "has_personal_use": any(bool(layer.get("personal_use")) for layer in layers),
    }


def _document_problem(document: Mapping[str, Any], kind: str) -> str | None:
    schema = str(document.get("schema", ""))
    if schema != SCHEMA_MAJOR:
        return (
            f"the engine's interface schema is {schema or 'missing'!r} and this dashboard "
            f"reads {SCHEMA_MAJOR!r} — update hammunition-hill or the engine"
        )
    if document.get("kind") != kind:
        return f"the engine answered with a {document.get('kind')!r} document, not {kind!r}"
    return None


def collect(
    *,
    finder: Callable[[], str | None] | None = None,
    runner: Callable[[str, Sequence[str]], dict[str, Any]] | None = None,
    fallback_latlon: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Ask the engine, and return a payload either way. Never raises.

    The two collaborators are parameters so a test never needs a real engine
    and so this machine's own station is never read by one.
    """
    # Looked up at call time, not bound as defaults, so a test can replace the
    # module's functions and have the collector see the replacement.
    exe = (finder or find_engine)()
    run = runner or run_engine
    if exe is None:
        return unavailable(
            f"the {ENGINE} engine is not installed on this machine, so there are no "
            "repeater layers to show — install it, then " + IMPORT_HINT
        )
    try:
        listing = run(exe, LIST_ARGV)
    except EngineError as exc:
        return unavailable(f"{exc} — " + IMPORT_HINT)

    station: dict[str, Any] | None
    try:
        station = run(exe, STATION_ARGV)
        if _document_problem(station, "station"):
            station = None
    except EngineError as exc:
        log.info("repeaters: no station from the engine (%s)", exc)
        station = None
    return build_data(listing, station, fallback_latlon=fallback_latlon)


# --- what another host may see ----------------------------------------------
def _names_personal_use(value: Any) -> bool:
    return _PERSONAL_WORD in json.dumps(value, default=str).lower()


def public_data(data: Any) -> dict[str, Any]:
    """The snapshot payload with everything RepeaterBook's terms keep home removed.

    A deep copy, so the stored data is never touched. Rows go if the engine
    flagged them *or* anything about them names RepeaterBook -- the flag is
    the engine's rule, and a filter that trusts only one field is one engine
    release away from leaking. The layer, and any credit, that names it go
    too. The count of withheld rows stays, so a viewer is told something is
    held back rather than shown a short list as if it were the whole one.
    """
    if not isinstance(data, dict):
        return {"available": False, "reason": "", "rows": [], "withheld": 0}
    out = copy.deepcopy(data)

    rows = out.get("rows")
    kept: list[Any] = []
    withheld = 0
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or row.get("personal_use") or _names_personal_use(row):
                withheld += 1
            else:
                kept.append(row)
    out["rows"] = kept
    # The rows of areas that are not active: the same rule, the same count.
    other = out.get("other_rows")
    other_kept: list[Any] = []
    if isinstance(other, list):
        for row in other:
            if not isinstance(row, dict) or row.get("personal_use") or _names_personal_use(row):
                withheld += 1
            else:
                other_kept.append(row)
    out["other_rows"] = other_kept
    out["withheld"] = withheld

    layers = out.get("layers")
    out["layers"] = [
        layer
        for layer in (layers if isinstance(layers, list) else [])
        if isinstance(layer, dict)
        and not layer.get("personal_use")
        and not _names_personal_use(layer)
    ]
    # An area whose every layer was removed goes with them: its name and middle
    # would say where the withheld rows are.
    kept_ids = {layer.get("id") for layer in out["layers"]}
    areas = out.get("areas")
    out["areas"] = [
        a
        for a in (areas if isinstance(areas, list) else [])
        if isinstance(a, dict) and any(i in kept_ids for i in a.get("layers") or [])
    ]
    skipped = out.get("skipped")
    out["skipped"] = [
        s for s in (skipped if isinstance(skipped, list) else []) if not _names_personal_use(s)
    ]
    credits = out.get("credits")
    out["credits"] = [
        c for c in (credits if isinstance(credits, list) else []) if not _names_personal_use(c)
    ]
    out["has_personal_use"] = False
    # The bands present are those of the rows kept.
    shown = [r for r in kept + other_kept if isinstance(r, dict)]
    present = {r.get("band") for r in shown}
    out["bands"] = [b for b in BAND_ORDER if b in present]
    modes_present = {m for r in shown for m in r.get("modes") or []}
    out["modes"] = [m for m in MODES if m in modes_present]
    out["has_modes"] = bool(out.get("has_modes"))
    return out

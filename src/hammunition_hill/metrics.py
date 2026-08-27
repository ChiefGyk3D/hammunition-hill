# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A Prometheus endpoint, so Grafana can do what Grafana is good at.

Snapshots have no history. Each write replaces the last, deliberately, because
the design is "what is true now" -- which is exactly right for a wall display
and useless for "SFI over six months" or "spots per band across a contest
weekend". This is the export path out, and the trending happens somewhere that
is built for it.

## Why this is a read path and not a write

The earlier plan called an exporter "the first outbound write the collector
would ever make". A Prometheus endpoint is not: Prometheus *pulls*. Nothing
here originates a connection, nothing leaves the machine unless something on
the network asks for it, and the egress allowlist is untouched. That is a
meaningfully smaller change than an InfluxDB push, which would be a write, and
it is why this comes first.

It is still off by default. It is served from the dashboard's own port, so it
is reachable by exactly the audience that can already read the dashboard, and
it exposes the same numbers the dashboard already shows -- but "the same
exposure" is a claim worth making deliberately rather than inheriting.

## Cardinality

The classic way to ruin a Prometheus is a label whose values are unbounded. A
callsign label would do it: every station heard becomes a new time series,
forever, and the database grows without limit even after the operator goes to
bed.

So nothing here is labelled by callsign. Labels are band, mode and source id --
all bounded by the band plan and the config file. There is a hard series cap as
well, because a bound that is only argued for is a bound that a future source
quietly breaks.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .snapshot import read_snapshot

# The Prometheus text exposition format, version 0.0.4. Content type included
# because a wrong one makes Prometheus refuse the scrape with a message that
# does not mention the content type.
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# A hard ceiling on series. Reached means something new is emitting per-value
# labels, which is the bug this exists to catch -- so it truncates and says so
# in the output rather than quietly handing a database an unbounded stream.
MAX_SERIES = 2000

_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


def _escape_label(value: str) -> str:
    """Backslash, double quote and newline, in that order.

    Order matters: escaping the quote first would then have its own backslash
    escaped by the next pass, which doubles it.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_value(value: float) -> str:
    """A number Prometheus will parse.

    Infinities and NaN are legal in this format and are how "we do not know"
    is spelled, which is better than omitting a series and leaving a gap that
    looks like downtime.
    """
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(float(value))


class Registry:
    """Collects samples and renders them once, grouped by family.

    Grouped because the format requires it: every sample of a family must
    follow that family's HELP and TYPE lines, and a scraper is entitled to
    reject a file where they are interleaved.
    """

    def __init__(self, max_series: int = MAX_SERIES) -> None:
        self._families: dict[str, dict[str, Any]] = {}
        self._series = 0
        self._max = max_series
        self.truncated = False

    def gauge(
        self,
        name: str,
        help_text: str,
        value: float | None,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record one sample. A value of None is simply not recorded.

        Not recorded rather than zero: a source that has never reported is not
        the same as one reporting zero, and a graph that cannot tell them apart
        will be read wrongly.
        """
        if value is None:
            return
        if not _NAME.match(name):
            raise ValueError(f"invalid metric name: {name!r}")
        if self._series >= self._max:
            self.truncated = True
            return

        family = self._families.setdefault(name, {"help": help_text, "samples": []})
        rendered = ""
        if labels:
            pairs = ",".join(f'{key}="{_escape_label(str(labels[key]))}"' for key in sorted(labels))
            rendered = "{" + pairs + "}"
        family["samples"].append((rendered, float(value)))
        self._series += 1

    def render(self) -> str:
        lines: list[str] = []
        for name in sorted(self._families):
            family = self._families[name]
            lines.append(f"# HELP {name} {family['help']}")
            lines.append(f"# TYPE {name} gauge")
            for rendered, value in family["samples"]:
                lines.append(f"{name}{rendered} {_format_value(value)}")
        if self.truncated:
            lines.append(
                f"# WARNING series cap of {self._max} reached; output truncated. "
                "Something is emitting unbounded labels."
            )
        return "\n".join(lines) + "\n"


def _number(value: Any) -> float | None:
    """The value as a float, or None if it is not one.

    Upstreams disagree about whether a number is a number or a string of one,
    and a missing field arrives as None, an empty string or the word "None"
    depending on who wrote it.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _age_seconds(snapshot: dict[str, Any], now: datetime) -> float | None:
    stamp = snapshot.get("fetched_at")
    if not isinstance(stamp, str):
        return None
    try:
        fetched = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return (now - fetched).total_seconds()


# Which snapshot each scalar lives in, what it is called there, and what to
# call it here. A table rather than a run of ifs, because that is what it is.
#
# fmt: off
SCALARS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("solarflux",   ("flux",),        "hamhill_solar_flux",        "10.7 cm solar flux"),
    ("kindex",      ("kp",),          "hamhill_k_index",           "Planetary K index"),
    ("hamqsl",      ("sfi",),         "hamhill_solar_flux",        "10.7 cm solar flux"),
    ("hamqsl",      ("aindex",),      "hamhill_a_index",           "Planetary A index"),
    ("xray",        ("flux",),        "hamhill_xray_flux_wm2",     "GOES X-ray flux, W/m^2"),
    ("propagation", ("muf_mhz",),     "hamhill_muf_mhz",           "Maximum usable frequency"),
    ("propagation", ("luf_mhz",),     "hamhill_luf_mhz",           "Lowest usable frequency"),
    ("propagation", ("absorption_db",), "hamhill_absorption_db",   "D-layer absorption"),
    ("aurora",      ("power_gw",),    "hamhill_aurora_power_gw",   "Hemispheric auroral power"),
)
# fmt: on


def collect(data_dir: Path, sources: tuple[str, ...], *, now: datetime | None = None) -> Registry:
    """Read every snapshot once and turn it into samples.

    Reads rather than subscribes, on the scrape, because that is the whole
    architecture: the numbers are already on disk and the cost of a scrape is
    the cost of reading a few small JSON files.
    """
    now = now or datetime.now(UTC)
    registry = Registry()

    registry.gauge("hamhill_up", "Always 1. Present so a scrape failure is distinguishable.", 1)

    # --- per-source liveness, which is what an operator actually alerts on
    for source_id in sources:
        snapshot = read_snapshot(data_dir, source_id)
        if snapshot is None:
            registry.gauge(
                "hamhill_snapshot_present",
                "1 if this source has ever written a snapshot.",
                0,
                {"source": source_id},
            )
            continue
        registry.gauge(
            "hamhill_snapshot_present",
            "1 if this source has ever written a snapshot.",
            1,
            {"source": source_id},
        )
        registry.gauge(
            "hamhill_snapshot_age_seconds",
            "Seconds since this source last wrote.",
            _age_seconds(snapshot, now),
            {"source": source_id},
        )
        registry.gauge(
            "hamhill_snapshot_failed",
            "1 if the last cycle for this source failed.",
            1 if snapshot.get("error") else 0,
            {"source": source_id},
        )
        stale_after = _number(snapshot.get("stale_after_seconds"))
        age = _age_seconds(snapshot, now)
        if stale_after is not None and age is not None:
            registry.gauge(
                "hamhill_snapshot_stale",
                "1 if this snapshot is older than its own staleness window. "
                "A window of 0 means the data does not age.",
                1 if stale_after > 0 and age > stale_after else 0,
                {"source": source_id},
            )

    # --- the numbers worth trending
    for source_id, path, name, help_text in SCALARS:
        snapshot = read_snapshot(data_dir, source_id)
        if snapshot is None:
            continue
        value: Any = snapshot.get("data") or {}
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        registry.gauge(name, help_text, _number(value))

    _collect_activity(registry, data_dir)
    _collect_satellites(registry, data_dir, now)
    return registry


def _collect_activity(registry: Registry, data_dir: Path) -> None:
    """Band activity from the RBN tally.

    Labelled by band and mode, both bounded -- never by callsign, which is the
    unbounded label that would make this a liability rather than a feature.
    """
    snapshot = read_snapshot(data_dir, "rbn")
    if snapshot is None:
        # No RBN source configured. Reporting zero reports of your callsign
        # would be a claim about the bands rather than about the config, and
        # the rule everywhere else here is that missing is not zero.
        return
    data = snapshot.get("data") or {}
    for row in data.get("activity") or []:
        if not isinstance(row, dict):
            continue
        labels = {"band": str(row.get("band", "")), "mode": str(row.get("mode", ""))}
        registry.gauge(
            "hamhill_rbn_spots",
            "Skimmer decodes on this band and mode in the collector's window.",
            _number(row.get("spots")),
            labels,
        )
        registry.gauge(
            "hamhill_rbn_stations",
            "Distinct callsigns decoded on this band and mode in the window.",
            _number(row.get("calls")),
            labels,
        )
        registry.gauge(
            "hamhill_rbn_skimmers",
            "Distinct skimmers reporting on this band and mode in the window.",
            _number(row.get("spotters")),
            labels,
        )
        registry.gauge(
            "hamhill_rbn_best_snr_db",
            "Best signal-to-noise reported on this band and mode in the window.",
            _number(row.get("best_snr")),
            labels,
        )

    heard = data.get("heard_me") or []
    registry.gauge(
        "hamhill_rbn_reports_of_me",
        "Skimmer reports of a watched callsign currently held.",
        len(heard) if isinstance(heard, list) else None,
    )
    if isinstance(heard, list) and heard:
        snrs = [_number(item.get("snr_db")) for item in heard if isinstance(item, dict)]
        usable = [value for value in snrs if value is not None]
        if usable:
            registry.gauge(
                "hamhill_rbn_best_snr_of_me_db",
                "Best signal-to-noise any skimmer has reported for a watched callsign.",
                max(usable),
            )


def _collect_satellites(registry: Registry, data_dir: Path, now: datetime) -> None:
    snapshot = read_snapshot(data_dir, "satellites")
    if snapshot is None:
        # Same rule: nothing configured is not the same as configured and
        # unavailable, and only the second is worth a series.
        return
    data = snapshot.get("data") or {}
    if not data.get("available"):
        registry.gauge(
            "hamhill_satellite_prediction_available",
            "1 when pass prediction is configured and working.",
            0,
        )
        return
    registry.gauge(
        "hamhill_satellite_prediction_available",
        "1 when pass prediction is configured and working.",
        1,
    )
    passes = data.get("passes") or []
    registry.gauge(
        "hamhill_satellite_passes",
        "Passes predicted in the collector's window.",
        len(passes) if isinstance(passes, list) else None,
    )
    registry.gauge(
        "hamhill_satellites_tracked",
        "Satellites with usable elements.",
        _number(data.get("tracked")),
    )
    # Seconds to the next one, which is the number a person would alert on.
    # Deliberately not one series per satellite: a catalog is an unbounded
    # label in exactly the way a callsign is.
    upcoming = []
    for item in passes if isinstance(passes, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            rise = datetime.fromisoformat(str(item.get("rise", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        seconds = (rise - now).total_seconds()
        if seconds >= 0:
            upcoming.append(seconds)
    if upcoming:
        registry.gauge(
            "hamhill_next_satellite_pass_seconds",
            "Seconds until the next predicted pass.",
            min(upcoming),
        )


def render(data_dir: Path, sources: tuple[str, ...], *, now: datetime | None = None) -> str:
    return collect(data_dir, sources, now=now).render()

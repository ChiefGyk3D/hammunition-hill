# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Active weather alerts from the US National Weather Service.

Why a station dashboard cares about the weather at all: a severe thunderstorm
warning is a reason to disconnect the feedline, a winter storm is a reason to
check the guys before it arrives, and a tornado watch is the thing that turns a
club net into an actual SKYWARN activation. This is the one panel that is about
the antenna rather than the ionosphere.

The endpoint is api.weather.gov's GeoJSON alert feed. No key, no account, and
the filter goes in the URL the operator writes in config -- ``?area=CO``,
``?point=39.74,-104.98``, ``?zone=COZ040``. That matters more than it looks:
because the full URL is config, this source constructs no URL at all. It parses
a response and returns data. Nothing it reads can change what gets fetched next
cycle, which is the property the whole collector is built on and the one that a
"just append the query string here" convenience would have quietly broken.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..config import SourceConfig
from .base import FetchError, get_bounded

# A county-level area query during a big outbreak returns hundreds. The panel
# shows a handful and counts the rest; keeping them all would bloat every
# snapshot for information nobody reads off a wall display.
MAX_ALERTS = 40
MAX_TEXT_CHARS = 500

_WS = re.compile(r"\s+")

# NWS severity, mapped onto the three levels the dials and the status ramp use.
#
# "Minor" and "Unknown" land on `good` -- which reads oddly for something called
# an alert, and is still right. The ramp is about how much attention this needs
# right now, and a small craft advisory is genuinely not the same class of thing
# as a tornado warning. Colouring them alike would make the ramp mean nothing on
# the day it matters.
_SEVERITY_LEVEL = {
    "extreme": "critical",
    "severe": "critical",
    "moderate": "warn",
    "minor": "good",
    "unknown": "good",
}

_LEVEL_RANK = {"good": 0, "warn": 1, "critical": 2}

# Sort order uses NWS's own five levels, NOT the three above.
#
# This distinction is load-bearing, and it took looking at a rendered panel to
# see why. Extreme and Severe both colour `critical`, because the status ramp
# has three colours and both of them mean "red". Sorting on that collapsed
# value put a Severe Thunderstorm Warning above a Tornado Warning -- same level,
# same urgency, so the tie fell through to alphabetical order.
#
# During an outbreak this panel shows the first handful of many. Pushing the
# tornado warning below the fold because "Severe" sorts before "Tornado" is the
# kind of failure that is invisible in a test and unforgivable in a shack.
# Colour collapses; order must not.
_SEVERITY_RANK = {"extreme": 0, "severe": 1, "moderate": 2, "minor": 3, "unknown": 4}

# Urgency is a separate axis from severity: an Extreme/Future alert is a heads-up
# and an Extreme/Immediate alert is happening now. Kept as data, not folded into
# the level, because the panel wants to sort by it.
_URGENCY_RANK = {"immediate": 0, "expected": 1, "future": 2, "past": 3, "unknown": 4}


def _clean(raw: Any, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(raw, str):
        return ""
    text = _WS.sub(" ", raw).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


def _alert(properties: dict[str, Any]) -> dict[str, Any]:
    severity = str(properties.get("severity") or "Unknown").strip()
    urgency = str(properties.get("urgency") or "Unknown").strip()
    level = _SEVERITY_LEVEL.get(severity.lower(), "warn")

    return {
        "event": _clean(properties.get("event"), 80) or "Alert",
        "headline": _clean(properties.get("headline"), 200),
        "area": _clean(properties.get("areaDesc"), 200),
        "severity": severity,
        "certainty": _clean(properties.get("certainty"), 40),
        "urgency": urgency,
        "level": level,
        "onset": properties.get("onset") or properties.get("effective"),
        "expires": properties.get("ends") or properties.get("expires"),
        "sender": _clean(properties.get("senderName"), 120),
        "description": _clean(properties.get("description")),
        "instruction": _clean(properties.get("instruction")),
    }


def _sort_key(alert: dict[str, Any]) -> tuple[int, int, str]:
    """Worst and soonest first, on NWS's severity rather than our colour.

    An unrecognised severity sorts as `severe` (1) rather than last: a category
    NWS adds later should land near the top where somebody will notice it, not
    silently at the bottom of a truncated list.

    Ties break by name so two dashboards on the same LAN cannot disagree about
    the order.
    """
    return (
        _SEVERITY_RANK.get(alert["severity"].lower(), 1),
        _URGENCY_RANK.get(alert["urgency"].lower(), 4),
        alert["event"],
    )


class NwsAlertsSource:
    """Watches, warnings and advisories in force for the configured area."""

    kind = "nws_alerts"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc
        if not isinstance(payload, dict):
            raise FetchError(f"{cfg.url}: expected a GeoJSON FeatureCollection")

        features = payload.get("features")
        if not isinstance(features, list):
            raise FetchError(f"{cfg.url}: no features array")

        alerts: list[dict[str, Any]] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties")
            if isinstance(properties, dict):
                alerts.append(_alert(properties))

        alerts.sort(key=_sort_key)

        # Count by event before truncating, so "12 of 60" is honest about what
        # was dropped and the summary line still names everything in force.
        counts: dict[str, int] = {}
        for alert in alerts:
            counts[alert["event"]] = counts.get(alert["event"], 0) + 1

        worst = "good"
        for alert in alerts:
            if _LEVEL_RANK[alert["level"]] > _LEVEL_RANK[worst]:
                worst = alert["level"]

        return {
            "alerts": alerts[:MAX_ALERTS],
            "count": len(alerts),
            "shown": min(len(alerts), MAX_ALERTS),
            "truncated": len(alerts) > MAX_ALERTS,
            "worst": worst,
            "by_event": [
                {"event": event, "count": n}
                for event, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "updated": payload.get("updated"),
        }

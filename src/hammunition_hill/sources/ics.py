# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""iCalendar feeds, used for the contest calendar.

Kept generic rather than hardcoding one publisher: contest calendars move, and
an operator who follows a regional or club calendar should be able to point this
at it without a code change.

The parser handles the subset of RFC 5545 a published calendar actually uses --
folded lines, escaped text, DATE and DATE-TIME values. It is not a general
iCalendar implementation and does not try to be.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from ..config import SourceConfig
from .base import FetchError, get_bounded

MAX_EVENTS = 60
# How far ahead to look. A contest calendar a year out is not a dashboard panel.
DEFAULT_HORIZON_DAYS = 21

_ESCAPES = ((r"\n", "\n"), (r"\N", "\n"), (r"\,", ","), (r"\;", ";"), ("\\\\", "\\"))
_PROPERTY = re.compile(r"^(?P<name>[A-Za-z0-9-]+)(?P<params>;[^:]*)?:(?P<value>.*)$")


def unfold(text: str) -> list[str]:
    """Join RFC 5545 continuation lines.

    A line beginning with a space or tab continues the previous one. Publishers
    wrap at 75 octets, so almost every SUMMARY of interest is folded.
    """
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def unescape(value: str) -> str:
    for encoded, plain in _ESCAPES:
        value = value.replace(encoded, plain)
    return value.strip()


def parse_dt(value: str, params: str) -> datetime | None:
    """Parse DTSTART/DTEND in the forms calendars actually publish."""
    value = value.strip()
    try:
        if "VALUE=DATE" in params.upper() and len(value) == 8:
            return datetime.combine(
                date(int(value[0:4]), int(value[4:6]), int(value[6:8])),
                datetime.min.time(),
                tzinfo=UTC,
            )
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if "T" in value:
            # A local-time value with no zone. Treating it as UTC is wrong by up
            # to a day, but a contest calendar without a zone is ambiguous at
            # source and UTC is the convention the hobby uses.
            return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return None


def parse_ics(text: str, *, horizon_days: int = DEFAULT_HORIZON_DAYS) -> list[dict[str, Any]]:
    """Extract upcoming events, soonest first."""
    now = datetime.now(UTC)
    horizon = now + timedelta(days=horizon_days)

    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in unfold(text):
        stripped = line.strip()
        if stripped == "BEGIN:VEVENT":
            current = {}
            continue
        if stripped == "END:VEVENT":
            if current and current.get("start"):
                events.append(current)
            current = None
            continue
        if current is None:
            continue

        match = _PROPERTY.match(stripped)
        if not match:
            continue
        name = match.group("name").upper()
        params = match.group("params") or ""
        value = match.group("value")

        if name == "SUMMARY":
            current["name"] = unescape(value)[:120]
        elif name == "DTSTART":
            current["start"] = parse_dt(value, params)
        elif name == "DTEND":
            current["end"] = parse_dt(value, params)
        elif name == "URL" and value.startswith(("http://", "https://")):
            current["url"] = value.strip()

    upcoming = [
        {
            "name": event.get("name") or "(untitled)",
            "start": event["start"].isoformat().replace("+00:00", "Z"),
            "end": event["end"].isoformat().replace("+00:00", "Z") if event.get("end") else None,
            "url": event.get("url"),
            "active": bool(
                event.get("end") and event["start"] <= now <= event["end"]
            ),
        }
        for event in events
        if event.get("start") and event["start"] <= horizon
        # Keep an event that is running right now even though it started earlier.
        and (event["start"] >= now or (event.get("end") and event["end"] >= now))
    ]
    upcoming.sort(key=lambda item: item["start"])
    return upcoming[:MAX_EVENTS]


class IcsSource:
    kind = "ics"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        text = response.text
        if "BEGIN:VCALENDAR" not in text.upper():
            raise FetchError(f"{cfg.url}: does not look like an iCalendar feed")

        horizon = int(cfg.options.get("horizon_days", DEFAULT_HORIZON_DAYS))
        events = parse_ics(text, horizon_days=horizon)
        return {
            "label": cfg.options.get("label", "Calendar"),
            "events": events,
            "count": len(events),
            "horizon_days": horizon,
        }

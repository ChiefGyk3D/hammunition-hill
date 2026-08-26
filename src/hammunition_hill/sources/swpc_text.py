# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""NOAA's formal storm scales and alert bulletins.

The dials elsewhere say what the numbers mean by our reading. These two sources
say what NOAA itself is calling it -- the official R (radio blackout), S
(radiation storm) and G (geomagnetic storm) scales, and the watches and warnings
the Space Weather Prediction Center actually issues.

Worth having both. Our thresholds are a reasonable interpretation; NOAA's are
the ones the rest of the world is working from.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..config import SourceConfig
from .base import FetchError, get_bounded

MAX_ALERTS = 12
MAX_MESSAGE_CHARS = 400

# NOAA's own severity wording, mapped onto our three levels.
_SCALE_LEVEL = {0: "good", 1: "warn", 2: "warn", 3: "critical", 4: "critical", 5: "critical"}

_WHITESPACE = re.compile(r"[ \t]+")
_BLANKLINES = re.compile(r"\n{3,}")


def _clean(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    text = _BLANKLINES.sub("\n\n", _WHITESPACE.sub(" ", text)).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


class NoaaScalesSource:
    """The current and forecast R/S/G scale numbers."""

    kind = "noaa_scales"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc
        if not isinstance(payload, dict):
            raise FetchError(f"{cfg.url}: expected an object keyed by day offset")

        # SWPC keys by day offset as a string: "-1" yesterday, "0" today.
        today = payload.get("0") or {}
        scales = {}
        for letter in ("R", "S", "G"):
            entry = today.get(letter) or {}
            try:
                number = int(entry.get("Scale") or 0)
            except (TypeError, ValueError):
                number = 0
            scales[letter] = {
                "scale": number,
                "text": (entry.get("Text") or "none").strip(),
                "level": _SCALE_LEVEL.get(number, "critical"),
                "label": f"{letter}{number}" if number else f"{letter}0",
            }

        return {
            "scales": scales,
            "worst": max(s["scale"] for s in scales.values()),
            "date": today.get("DateStamp"),
        }


class SwpcAlertsSource:
    """Watches, warnings and alerts as SWPC issues them."""

    kind = "swpc_alerts"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        try:
            rows = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc
        if not isinstance(rows, list):
            raise FetchError(f"{cfg.url}: expected a list of alerts")

        alerts = []
        for row in rows[:MAX_ALERTS]:
            if not isinstance(row, dict):
                continue
            message = _clean(str(row.get("message") or ""))
            if not message:
                continue
            # The first line is the human summary; the rest is detail.
            headline = message.split("\n", 1)[0].strip()
            alerts.append(
                {
                    "id": row.get("product_id"),
                    "issued": row.get("issue_datetime"),
                    "headline": headline[:160],
                    "message": message,
                }
            )

        return {"alerts": alerts, "count": len(alerts)}

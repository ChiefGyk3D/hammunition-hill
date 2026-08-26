# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Summits on the Air spots.

SOTA reports frequency in MHz as a string, unlike POTA and the DX clusters which
both use kHz. We normalize to kHz here so every spot in the system speaks the
same units -- mixing them is exactly the kind of thing that produces a spot on
"14 kHz".
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import SourceConfig
from .base import FetchError, get_bounded

MAX_SPOTS = 100


class SotaSource:
    kind = "sota"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        try:
            rows = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc
        if not isinstance(rows, list):
            raise FetchError(f"{cfg.url}: expected a list of spots")

        spots = []
        for row in rows[:MAX_SPOTS]:
            if not isinstance(row, dict):
                continue
            call = (row.get("activatorCallsign") or row.get("callsign") or "").strip().upper()
            if not call:
                continue

            khz: float | None
            try:
                khz = round(float(row["frequency"]) * 1000.0, 2)
            except (KeyError, TypeError, ValueError):
                khz = None

            association = row.get("associationCode") or ""
            summit = row.get("summitCode") or ""
            spots.append(
                {
                    "call": call,
                    "khz": khz,
                    "mode": (row.get("mode") or "").strip().upper() or None,
                    "reference": f"{association}/{summit}".strip("/") or None,
                    "summit": row.get("summitDetails"),
                    "spotter": row.get("callsign"),
                    "comment": (row.get("comments") or "")[:60],
                    "at": row.get("timeStamp"),
                }
            )

        return {"program": "SOTA", "spots": spots, "count": len(spots)}

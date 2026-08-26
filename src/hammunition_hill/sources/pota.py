"""Parks on the Air activator spots.

POTA publishes current activator spots as plain JSON with no key and no auth.
The feed carries real park coordinates, which makes these spots better located
than a cluster spot resolved to an entity centroid.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import SourceConfig
from .base import FetchError, get_bounded

MAX_SPOTS = 200


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PotaSource:
    kind = "pota"

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
            # POTA marks superseded spots rather than removing them.
            if row.get("invalid"):
                continue
            call = (row.get("activator") or "").strip().upper()
            if not call:
                continue
            spots.append(
                {
                    "call": call,
                    "khz": _float_or_none(row.get("frequency")),
                    "mode": (row.get("mode") or "").strip().upper() or None,
                    "reference": row.get("reference"),
                    "park": row.get("name") or row.get("parkName"),
                    "location": row.get("locationDesc"),
                    "grid": row.get("grid6") or row.get("grid4"),
                    "lat": _float_or_none(row.get("latitude")),
                    "lon": _float_or_none(row.get("longitude")),
                    "spotter": row.get("spotter"),
                    "comment": (row.get("comments") or "")[:60],
                    "at": row.get("spotTime"),
                }
            )

        return {"program": "POTA", "spots": spots, "count": len(spots)}

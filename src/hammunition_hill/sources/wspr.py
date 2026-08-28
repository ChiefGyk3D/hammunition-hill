# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""WSPR reception reports from wspr.live: who heard your beacon, and how well.

WSPR is the propagation instrument of the hobby: milliwatt beacons on a
two-minute cycle, decoded ten dB below the noise floor, every decode
uploaded. wspr.live mirrors the wsprnet database into ClickHouse and exposes
it read-only over HTTP -- you send a SELECT in the query string, it answers
JSON. Free for non-commercial use, with fair-use quotas and a cooldown
between requests, which is why this kind shares the five-minute interval
floor (KIND_INTERVAL_FLOORS).

Same honesty note as the pskreporter source: the query carries your callsign
to wspr.live, because "reports where tx_sign is me" *is* the query. It is set
in ``options``, never inherited from [station].

Yes, this interpolates a string into SQL. The callsign has already passed a
pattern that admits only ``A-Z 0-9 /`` -- no quote, no backslash, no way out
of the single-quoted literal -- and the window and limit are ints we format
ourselves. A callsign that fails the pattern never reaches the query; there
is a test that tries.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ..bands import band_for
from ..config import SourceConfig
from .base import FetchError, get_bounded
from .pskreporter import required_callsign

MAX_REPORTS = 200

# WSPR cycles are two minutes and many beacons only transmit a few slots an
# hour, so the window is wider than PSK Reporter's or the panel would be
# empty more often than not.
DEFAULT_WINDOW_MIN = 30
WINDOW_MIN, WINDOW_MAX = 5, 240

_COLUMNS = "time, rx_sign, rx_lat, rx_lon, rx_loc, distance, snr, power, frequency"


def _window_minutes(options: dict[str, Any]) -> int:
    try:
        window = int(options.get("window_minutes", DEFAULT_WINDOW_MIN))
    except (TypeError, ValueError):
        window = DEFAULT_WINDOW_MIN
    return max(WINDOW_MIN, min(WINDOW_MAX, window))


def build_query(call: str, window: int) -> str:
    """The SELECT sent to wspr.live, exposed for the tests to read."""
    return (
        f"SELECT {_COLUMNS} FROM wspr.rx "  # noqa: S608 - call is pattern-validated, ints ours
        f"WHERE tx_sign = '{call}' AND time > subtractMinutes(now(), {int(window)}) "
        f"ORDER BY time DESC LIMIT {MAX_REPORTS} FORMAT JSON"
    )


class WsprSource:
    kind = "wspr"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        call = required_callsign(cfg.options, self.kind, "wspr.live")
        window = _window_minutes(cfg.options)
        sql = build_query(call, window)
        sep = "&" if "?" in cfg.url else "?"
        response = await get_bounded(client, f"{cfg.url}{sep}query={quote(sql)}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise FetchError(f"{cfg.url}: expected ClickHouse JSON with a data array")

        spots = []
        for row in rows[:MAX_REPORTS]:
            if not isinstance(row, dict):
                continue
            receiver = str(row.get("rx_sign") or "").strip().upper()
            if not receiver:
                continue
            # ClickHouse quotes 64-bit integers in JSON output by default, so
            # every numeric field is coerced rather than trusted to be a number.
            khz = _hz_to_khz(row.get("frequency"))
            spots.append(
                {
                    "call": receiver,
                    "grid": str(row.get("rx_loc") or "").strip() or None,
                    "lat": _float_or_none(row.get("rx_lat")),
                    "lon": _float_or_none(row.get("rx_lon")),
                    "khz": khz,
                    "band": band_for(khz) if khz else None,
                    "mode": "WSPR",
                    "snr": _int_or_none(row.get("snr")),
                    "power_dbm": _int_or_none(row.get("power")),
                    "distance_km": _float_or_none(row.get("distance")),
                    "at": _clickhouse_iso(row.get("time")),
                }
            )

        return {
            "program": "WSPR",
            "call": call,
            "window_minutes": window,
            "spots": spots,
            "count": len(spots),
        }


def _hz_to_khz(value: Any) -> float | None:
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clickhouse_iso(value: Any) -> str | None:
    """ClickHouse DateTime renders as '2026-08-28 14:02:00', already UTC."""
    text = str(value or "").strip()
    if not text:
        return None
    return text.replace(" ", "T") + ("" if text.endswith("Z") else "Z")

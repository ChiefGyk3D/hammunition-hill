# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""PSK Reporter reception reports: every station that heard YOU.

The Reverse Beacon Network answers "who is hearing me" for CW. PSK Reporter
answers it for the digital modes -- every WSJT-X, JS8Call and fldigi station
with reporting on uploads a report for each decode, and the retrieval API at
retrieve.pskreporter.info hands back the recent window of them as XML.

Honesty about what this sends: the query carries your callsign to
pskreporter.info, because that *is* the query -- "reports where the sender is
me". Nothing else identifies the station (no account, no key, no position).
The callsign is set here in ``options``, never inherited from ``[station]``,
so the promise in config.example.toml -- station numbers are used on this
machine and nowhere else -- stays exactly true.

Their developer page asks retrievers to poll gently; the aggregate only
settles about five minutes after a transmission anyway. Config enforces a
five-minute interval floor for this kind (KIND_INTERVAL_FLOORS).

Parsed with defusedxml, same as HamQSL: remote XML, and stock ElementTree
will happily follow entity declarations into places we do not want to go.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from defusedxml import ElementTree as DefusedET

from ..bands import band_for
from ..config import SourceConfig
from .base import FetchError, get_bounded

MAX_REPORTS = 300

# Window defaults to 15 minutes: long enough to survive two polls with no new
# decodes, short enough that the globes show propagation, not history.
DEFAULT_WINDOW_MIN = 15
WINDOW_MIN, WINDOW_MAX = 5, 60

# The strings this pattern admits are what we are willing to put in a query
# string aimed at someone else's server: bare calls and portable suffixes.
_CALL = re.compile(r"^[A-Z0-9]{3,10}(?:/[A-Z0-9]{1,4})?$")


def _window_minutes(options: dict[str, Any]) -> int:
    try:
        window = int(options.get("window_minutes", DEFAULT_WINDOW_MIN))
    except (TypeError, ValueError):
        window = DEFAULT_WINDOW_MIN
    return max(WINDOW_MIN, min(WINDOW_MAX, window))


def required_callsign(options: dict[str, Any], kind: str, host: str) -> str:
    """The operator's callsign, validated, or a FetchError that says how.

    Shared by the reception-report sources because the contract is shared:
    the callsign is the query, it goes to a third party, and it must be
    declared per-source rather than borrowed from [station].
    """
    call = str(options.get("callsign") or "").strip().upper()
    if not call:
        raise FetchError(
            f"{kind}: set options.callsign -- this callsign is sent to {host} "
            f"as the query (reports where the sender is you). It is deliberately "
            f"not taken from [station], which is never sent anywhere."
        )
    if not _CALL.match(call):
        raise FetchError(f"{kind}: options.callsign {call!r} does not look like a callsign")
    return call


class PskReporterSource:
    kind = "pskreporter"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        call = required_callsign(cfg.options, self.kind, "pskreporter.info")
        window = _window_minutes(cfg.options)
        params = {
            "senderCallsign": call,
            # Negative means "this many seconds back from now".
            "flowStartSeconds": str(-window * 60),
            # Reports only: without this the response also carries the full
            # active-monitor list, thousands of entries we would just discard.
            "rronly": "1",
        }
        sep = "&" if "?" in cfg.url else "?"
        response = await get_bounded(client, f"{cfg.url}{sep}{urlencode(params)}")

        try:
            root = DefusedET.fromstring(response.content)
        except DefusedET.ParseError as exc:
            raise FetchError(f"{cfg.url}: response was not XML ({exc})") from exc

        spots = []
        for report in root.iter("receptionReport"):
            attr = report.attrib
            # rronly filters server-side, but trust the data over the flag:
            # keep only reports whose sender is the queried station.
            if (attr.get("senderCallsign") or "").strip().upper() != call:
                continue
            receiver = (attr.get("receiverCallsign") or "").strip().upper()
            if not receiver:
                continue
            khz = _hz_to_khz(attr.get("frequency"))
            spots.append(
                {
                    "call": receiver,
                    "grid": (attr.get("receiverLocator") or "").strip() or None,
                    "khz": khz,
                    "band": band_for(khz) if khz else None,
                    "mode": (attr.get("mode") or "").strip().upper() or None,
                    "snr": _int_or_none(attr.get("sNR")),
                    "at": _epoch_iso(attr.get("flowStartSeconds")),
                }
            )

        spots.sort(key=lambda s: s["at"] or "", reverse=True)
        del spots[MAX_REPORTS:]
        return {
            "program": "PSK Reporter",
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


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _epoch_iso(value: Any) -> str | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

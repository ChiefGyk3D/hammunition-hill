# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The Reverse Beacon Network: who is hearing whom, measured rather than judged.

A DX cluster tells you what other operators chose to spot. RBN tells you what
several hundred unattended receivers actually decoded, with a signal-to-noise
figure and a sending speed attached. That is a different kind of information,
and it supports two things a cluster cannot:

  - **Who is hearing me.** Call CQ and the skimmers report you, from where they
    are, with an SNR. It is the only feedback loop in amateur radio that tells
    you your own signal is getting out before anyone answers.
  - **Where the bands are actually open.** Thousands of automated decodes a
    minute is a propagation measurement, not an opinion.

## Volume, and what this does about it

RBN emits far more than a dashboard can hold or a person can read -- several
thousand spots a minute across all bands. Keeping them all would fill a Pi's
memory to no purpose.

So this keeps two things and discards the rest as it arrives:

  - every spot of a callsign the operator asked to watch, capped;
  - a rolling per-band, per-mode **tally** of everything else -- counts, unique
    callsigns, unique skimmers, best SNR.

The tally is bounded by the number of bands times the number of modes, which is
a few dozen entries no matter how hard the network works. Nothing here grows
with traffic.

**We only ever send what the operator configured.** As with the cluster client,
no command is constructed from anything the peer sent.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from ..bands import band_for
from .base import with_reconnect
from .cluster import MAX_LINE_BYTES, login

log = logging.getLogger(__name__)

# 7000 is CW/RTTY, 7001 is the digital feed. Neither is a default worth
# guessing at, so the URL carries it.
DEFAULT_PORT = 7000

# A zero or negative flush interval is a spin: asyncio.wait_for with a timeout
# of zero never lets the read start, so the loop turns forever without consuming
# a byte. Clamp rather than reject -- a config typo should cost a tenth of a
# second of latency, not the collector.
MIN_FLUSH_SECONDS = 0.1

# Spots of a watched callsign. A busy contest hour might produce a few hundred
# of your own; anything past that is history, not a dashboard.
MAX_WATCHED = 200

# How far back the activity tally reaches. Ten minutes is long enough to be a
# propagation statement and short enough to still be about now.
DEFAULT_WINDOW_SECONDS = 600

# DX de W3LPL-#:   14025.0  DL1ABC    CW    23 dB  28 WPM  CQ      1234Z
#
# The '-#' suffix marks a skimmer, which is every spotter on this feed. The
# fields after the callsign are structured here, unlike a cluster's free-text
# comment, and that structure is the entire reason for a separate parser.
_RBN_SPOT = re.compile(
    r"^DX\s+de\s+(?P<spotter>[A-Z0-9/#\-]{3,20}?):?\s+"
    r"(?P<khz>\d{3,9}(?:\.\d+)?)\s+"
    r"(?P<call>[A-Z0-9/]{3,20})\s+"
    r"(?P<mode>[A-Z0-9]{2,8})\s+"
    r"(?P<snr>-?\d{1,3})\s*dB\s+"
    r"(?P<wpm>\d{1,3})\s*(?:WPM|BPS)\s+"
    r"(?P<kind>[A-Z0-9]{1,10})\s+"
    r"(?P<time>\d{4})Z?\s*$",
    re.IGNORECASE,
)


def parse_rbn_line(line: str) -> dict[str, Any] | None:
    """Parse one RBN spot, or None if the line is not one.

    The feed carries plenty besides spots -- the login banner, keepalives,
    occasional notices. Anything that does not match is dropped rather than
    guessed at, the same call the cluster parser makes.
    """
    match = _RBN_SPOT.match(line.strip())
    if not match:
        return None

    try:
        khz = float(match.group("khz"))
        snr = int(match.group("snr"))
        wpm = int(match.group("wpm"))
    except ValueError:  # pragma: no cover - the regex guarantees these parse
        return None

    if not 100.0 <= khz <= 30_000_000.0:
        return None
    # A skimmer reporting +90 dB or -90 dB has a problem, and so would any
    # average computed from it.
    if not -40 <= snr <= 90:
        return None

    return {
        "spotter": match.group("spotter").upper(),
        "khz": khz,
        "call": match.group("call").upper(),
        "band": band_for(khz),
        "mode": match.group("mode").upper(),
        "snr_db": snr,
        "wpm": wpm,
        "kind": match.group("kind").upper(),
        "time": match.group("time"),
        "spotted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


class _Tally:
    """A rolling count per band and mode, bounded by the band plan.

    Deliberately not a list of spots with a time filter: that would grow with
    traffic, which is the thing this whole module exists to avoid. Each bucket
    holds counters and two sets of identifiers, and the sets are capped.
    """

    # Enough to say "seventy different stations" without holding a contest log.
    MAX_TRACKED = 400

    def __init__(self, window_seconds: float) -> None:
        self.window = timedelta(seconds=window_seconds)
        self.buckets: dict[tuple[str, str], dict[str, Any]] = {}
        self.total = 0

    def add(self, spot: dict[str, Any], now: datetime) -> None:
        band = spot["band"]
        if band is None:
            return
        key = (band, spot["mode"])
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = {
                "band": band,
                "mode": spot["mode"],
                "spots": 0,
                "calls": set(),
                "spotters": set(),
                "best_snr": None,
                "best_call": None,
                "since": now,
                "last": now,
            }
        bucket["spots"] += 1
        bucket["last"] = now
        if len(bucket["calls"]) < self.MAX_TRACKED:
            bucket["calls"].add(spot["call"])
        if len(bucket["spotters"]) < self.MAX_TRACKED:
            bucket["spotters"].add(spot["spotter"])
        if bucket["best_snr"] is None or spot["snr_db"] > bucket["best_snr"]:
            bucket["best_snr"] = spot["snr_db"]
            bucket["best_call"] = spot["call"]
        self.total += 1

    def expire(self, now: datetime) -> None:
        """Drop buckets nothing has landed in for a whole window.

        Coarse on purpose. A per-spot expiry would need the spots kept, and
        keeping them is what this avoids. The cost is that a band which went
        quiet keeps its counts for up to one window, which the panel labels
        with the time of the last spot so nobody has to guess.
        """
        cutoff = now - self.window
        stale = [key for key, bucket in self.buckets.items() if bucket["last"] < cutoff]
        for key in stale:
            self.total -= self.buckets[key]["spots"]
            del self.buckets[key]

    def to_list(self) -> list[dict[str, Any]]:
        rows = []
        for bucket in self.buckets.values():
            rows.append(
                {
                    "band": bucket["band"],
                    "mode": bucket["mode"],
                    "spots": bucket["spots"],
                    "calls": len(bucket["calls"]),
                    "spotters": len(bucket["spotters"]),
                    "best_snr": bucket["best_snr"],
                    "best_call": bucket["best_call"],
                    "last": bucket["last"].isoformat().replace("+00:00", "Z"),
                }
            )
        rows.sort(key=lambda row: -row["spots"])
        return rows


class RbnStream:
    """Holds an RBN connection open, watching for one callsign and tallying the rest."""

    kind = "rbn"

    def __init__(self) -> None:
        self.watched: deque[dict[str, Any]] = deque(maxlen=MAX_WATCHED)
        # Built here rather than in run() so it is never None: an Optional the
        # code then asserts away is a type that lies, and `assert` vanishes
        # under -O anyway. run() replaces it once the window is known.
        self.tally = _Tally(DEFAULT_WINDOW_SECONDS)

    async def run(self, cfg: Any, emit: Any) -> None:
        parts = urlsplit(cfg.url)
        host = parts.hostname or ""
        port = parts.port or DEFAULT_PORT

        callsign = str(cfg.options.get("callsign", "")).strip().upper()
        if not callsign:
            raise ValueError(
                f"source {cfg.id!r}: rbn needs options.callsign -- the network "
                f"requires a login and will not accept an anonymous one"
            )

        # Watching your own callsign is the point, so it is the default. An
        # operator running two calls, or curious about a friend, can say so.
        watch = cfg.options.get("watch") or [callsign]
        watch_set = {str(item).strip().upper() for item in watch if str(item).strip()}

        window = float(cfg.options.get("window_seconds", DEFAULT_WINDOW_SECONDS))
        self.tally = _Tally(window)
        commands = [str(c) for c in cfg.options.get("commands", [])]

        async def connect() -> None:
            log.info("%s: connecting to %s:%d as %s", cfg.id, host, port, callsign)
            reader, writer = await asyncio.open_connection(host, port)
            try:
                await login(reader, writer, callsign, commands)
                await self._read(reader, cfg, emit, watch_set, window)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (TimeoutError, OSError):
                    pass

        await with_reconnect(cfg.id, connect)

    def payload(self, watch: set[str], window: float) -> dict[str, Any]:
        return {
            "watching": sorted(watch),
            "heard_me": list(self.watched)[::-1],
            "activity": self.tally.to_list(),
            "spots_in_window": self.tally.total,
            "window_seconds": window,
        }

    async def _read(
        self,
        reader: asyncio.StreamReader,
        cfg: Any,
        emit: Any,
        watch: set[str],
        window: float,
    ) -> None:
        """Read until the peer closes, emitting on a timer rather than per spot.

        Per-spot emission would mean thousands of snapshot writes a minute on a
        busy evening, which is a great deal of disk for a panel nobody can read
        that fast.
        """
        dirty = False
        flush_interval = max(MIN_FLUSH_SECONDS, float(cfg.options.get("flush_seconds", 10)))
        last_flush = asyncio.get_running_loop().time()

        while True:
            try:
                raw = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=flush_interval)
            except TimeoutError:
                raw = b""
            except asyncio.LimitOverrunError:
                # A line longer than the buffer is not a spot. Drop and resync.
                await reader.read(MAX_LINE_BYTES)
                continue
            except asyncio.IncompleteReadError as exc:
                if not exc.partial:
                    return  # Clean close.
                raw = exc.partial

            if raw:
                spot = parse_rbn_line(raw.decode("utf-8", errors="replace")[:MAX_LINE_BYTES])
                if spot is not None:
                    if spot["call"] in watch:
                        self.watched.append(spot)
                    self.tally.add(spot, datetime.now(UTC))
                    dirty = True

            now = asyncio.get_running_loop().time()
            if dirty and now - last_flush >= flush_interval:
                self.tally.expire(datetime.now(UTC))
                await emit(self.payload(watch, window))
                dirty = False
                last_flush = now

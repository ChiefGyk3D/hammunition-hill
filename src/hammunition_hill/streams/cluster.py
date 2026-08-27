# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""DX cluster over telnet.

Clusters speak a line protocol that has barely changed since packet radio. We
log in with a callsign, optionally send a few setup commands, and then read
spot lines until the connection drops.

**We only ever send what the operator configured.** No command is ever
constructed from data the cluster sent us -- a hostile or compromised node can
fill the spot list with nonsense, which the UI treats as untrusted text, but it
cannot make this client do anything.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from .base import with_reconnect

log = logging.getLogger(__name__)

DEFAULT_PORT = 7300
MAX_SPOTS = 500
MAX_LINE_BYTES = 4096

# A zero or negative flush interval is a spin: asyncio.wait_for with a timeout
# of zero never lets the read start, so the loop turns forever without
# consuming a byte. Clamp rather than reject.
MIN_FLUSH_SECONDS = 0.1

# DX de W1ABC:     14074.0  JA1XYZ       FT8 -12 dB              1234Z
#
# The spotter field allows '#' because RBN skimmer nodes identify themselves as
# e.g. EA5ABC-#, and those are a large share of the spots on a busy cluster.
_SPOT = re.compile(
    r"^DX\s+de\s+(?P<spotter>[A-Z0-9/#\-]{3,20}?):?\s+"
    r"(?P<khz>\d{3,9}(?:\.\d+)?)\s+"
    r"(?P<call>[A-Z0-9/]{3,20})\s*"
    r"(?P<comment>.*?)\s*"
    r"(?P<time>\d{4})Z?\s*$",
    re.IGNORECASE,
)

# Cluster login prompts vary by software; these cover DXSpider, AR-Cluster, CC.
_LOGIN_PROMPT = re.compile(rb"(login|call ?sign|your call|enter your call)\s*[:>]?", re.IGNORECASE)

# A mode word appearing in the comment is worth more than frequency inference.
_MODE_WORDS = re.compile(
    r"\b(FT8|FT4|JS8|CW|SSB|USB|LSB|RTTY|PSK31|PSK|AM|FM|SSTV|JT65|JT9|Q65|MSK144|OLIVIA)\b",
    re.IGNORECASE,
)


def parse_spot_line(line: str) -> dict[str, Any] | None:
    """Parse one 'DX de' line into raw spot fields, or None if it is not one.

    Clusters emit plenty of other traffic -- announcements, WWV bulletins, chat.
    Anything that is not a spot is dropped rather than guessed at.
    """
    match = _SPOT.match(line.strip())
    if not match:
        return None

    try:
        khz = float(match.group("khz"))
    except ValueError:  # pragma: no cover - the regex guarantees a number
        return None
    if not 100.0 <= khz <= 30_000_000.0:
        return None

    comment = match.group("comment").strip()
    mode_hit = _MODE_WORDS.search(comment)

    return {
        "spotter": match.group("spotter").upper(),
        "khz": khz,
        "call": match.group("call").upper(),
        "comment": comment[:60],
        "time": match.group("time"),
        "mode_from_comment": mode_hit.group(1).upper() if mode_hit else None,
        "spotted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


class ClusterStream:
    """Holds a cluster connection open and keeps a rolling window of spots."""

    kind = "dxcluster"

    def __init__(self) -> None:
        self.spots: deque[dict[str, Any]] = deque(maxlen=MAX_SPOTS)

    async def run(self, cfg: Any, emit: Any) -> None:
        parts = urlsplit(cfg.url)
        host = parts.hostname or ""
        port = parts.port or DEFAULT_PORT
        callsign = str(cfg.options.get("callsign", "")).strip().upper()
        if not callsign:
            raise ValueError(
                f"source {cfg.id!r}: dxcluster needs options.callsign -- "
                f"clusters require a login and will not accept an anonymous one"
            )
        commands = [str(c) for c in cfg.options.get("commands", [])]

        async def connect() -> None:
            log.info("%s: connecting to %s:%d as %s", cfg.id, host, port, callsign)
            reader, writer = await asyncio.open_connection(host, port)
            try:
                await self._login(reader, writer, callsign, commands)
                await self._read_spots(reader, cfg, emit)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (TimeoutError, OSError):
                    pass

        await with_reconnect(cfg.id, connect)

    async def _login(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        callsign: str,
        commands: list[str],
    ) -> None:
        await login(reader, writer, callsign, commands)

    async def _read_spots(self, reader: asyncio.StreamReader, cfg: Any, emit: Any) -> None:
        """Read lines until the peer closes. Flush a snapshot when spots change."""
        dirty = False
        last_flush = asyncio.get_running_loop().time()
        flush_interval = max(MIN_FLUSH_SECONDS, float(cfg.options.get("flush_seconds", 5)))

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
                line = raw.decode("utf-8", errors="replace")[:MAX_LINE_BYTES]
                spot = parse_spot_line(line)
                if spot is not None:
                    self.spots.append(spot)
                    dirty = True

            now = asyncio.get_running_loop().time()
            if dirty and now - last_flush >= flush_interval:
                await emit(list(self.spots))
                dirty = False
                last_flush = now


async def login(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    callsign: str,
    commands: list[str],
) -> None:
    """Wait for a login prompt, then send the configured callsign and setup.

    Shared with the RBN client, which speaks the same dialect: a prompt, a
    callsign, then lines. Module level rather than a method because the two
    clients have nothing else in common and a base class for one function would
    be more structure than the problem has.

    **Only ever sends what the operator configured.** No command is constructed
    from anything the peer sent.
    """
    deadline = asyncio.get_running_loop().time() + 30.0
    while asyncio.get_running_loop().time() < deadline:
        chunk = await asyncio.wait_for(reader.read(1024), timeout=10.0)
        if not chunk:
            raise ConnectionError("closed before a login prompt")
        if _LOGIN_PROMPT.search(chunk):
            break
    else:
        raise TimeoutError("no login prompt within 30s")

    writer.write(f"{callsign}\r\n".encode("ascii", "ignore"))
    await writer.drain()

    for command in commands:
        await asyncio.sleep(0.5)
        writer.write(f"{command}\r\n".encode("ascii", "ignore"))
        await writer.drain()

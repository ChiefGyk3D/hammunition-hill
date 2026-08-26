# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Rig state from Hamlib's rigctld.

Start ``rigctld`` on the shack machine and this reports the dial frequency and
mode a few times a second, which is what lets the spot list scope itself to the
band you are actually on.

**Read-only.** We send exactly two queries, ``f`` and ``m``, both of which are
gets. This client has no code path that changes frequency, mode, PTT, or
anything else -- a dashboard should never be able to key your transmitter, and
the way to guarantee that is to never implement it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

from ..bands import band_for
from .base import with_reconnect

log = logging.getLogger(__name__)

DEFAULT_PORT = 4532
RESPONSE_TIMEOUT = 3.0

# Hamlib reports an error as a negative RPRT code.
_ERROR_PREFIX = "RPRT "


class RigctlError(Exception):
    """rigctld answered, but with an error."""


async def _query(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, command: str
) -> list[str]:
    """Send one get command and read its reply lines."""
    writer.write(f"{command}\n".encode("ascii"))
    await writer.drain()

    lines: list[str] = []
    while True:
        raw = await asyncio.wait_for(reader.readline(), timeout=RESPONSE_TIMEOUT)
        if not raw:
            raise ConnectionError("rigctld closed the connection")
        line = raw.decode("utf-8", errors="replace").strip()
        if line.startswith(_ERROR_PREFIX):
            code = line[len(_ERROR_PREFIX) :].strip()
            if code not in ("0", ""):
                raise RigctlError(f"{command}: rigctld returned {line}")
            break
        lines.append(line)
        # `f` returns one line, `m` returns mode then passband. Neither sends
        # an RPRT on success, so stop once we have what the command yields.
        if command == "f" and len(lines) >= 1:
            break
        if command == "m" and len(lines) >= 2:
            break
    return lines


def parse_state(freq_lines: list[str], mode_lines: list[str]) -> dict[str, Any]:
    """Turn rigctld's replies into the fields a panel renders."""
    khz: float | None = None
    if freq_lines:
        try:
            khz = round(float(freq_lines[0]) / 1000.0, 2)
        except ValueError:
            khz = None

    mode = mode_lines[0].strip().upper() if mode_lines else None
    passband: int | None = None
    if len(mode_lines) > 1:
        try:
            passband = int(mode_lines[1])
        except ValueError:
            passband = None

    return {
        "khz": khz,
        "band": band_for(khz) if khz is not None else None,
        "mode": mode or None,
        "passband_hz": passband,
    }


class RigctlStream:
    """Polls rigctld over a persistent socket."""

    kind = "rigctl"

    async def run(self, cfg: Any, emit: Any) -> None:
        parts = urlsplit(cfg.url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or DEFAULT_PORT
        # The rig is on the other side of a socket on the same box; polling it
        # twice a second is cheap and makes the band readout feel live.
        interval = max(0.2, float(cfg.options.get("poll_seconds", 1.0)))

        async def connect() -> None:
            reader, writer = await asyncio.open_connection(host, port)
            log.info("%s: connected to rigctld at %s:%d", cfg.id, host, port)
            try:
                while True:
                    try:
                        state = parse_state(
                            await _query(reader, writer, "f"),
                            await _query(reader, writer, "m"),
                        )
                    except RigctlError as exc:
                        # The rig is off or the backend is unhappy. Report it
                        # rather than tearing down a working connection.
                        log.debug("%s: %s", cfg.id, exc)
                        state = {"khz": None, "band": None, "mode": None, "error": str(exc)}
                    await emit(state)
                    await asyncio.sleep(interval)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (TimeoutError, OSError):
                    pass

        await with_reconnect(cfg.id, connect)

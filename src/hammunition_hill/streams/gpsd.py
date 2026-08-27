# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""gpsd, over its JSON protocol on localhost.

The recommended way to read a receiver on Linux: gpsd is already running on
most handhelds that have one, it has done the hard parsing, it handles the
receiver's quirks, and it can share one device between this and whatever else
wants it. Reading the serial line directly means taking the device exclusively,
which would stop the operator's logging software from seeing it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlsplit

from ..gps import parse_gpsd_tpv
from .base import with_reconnect

log = logging.getLogger(__name__)

DEFAULT_PORT = 2947

# gpsd's own handshake. Fixed text, sent once: this is a protocol greeting, not
# the stream taking instruction from anything. Nothing gpsd sends back changes
# what is written here or what the collector fetches -- the one-directional
# property the whole stream design rests on holds.
WATCH = b'?WATCH={"enable":true,"json":true}\n'

# A receiver reports once a second. Flushing a snapshot that often would be
# churn for a browser polling every ten.
FLUSH_SECONDS = 10.0

# Longest a single JSON line may be. gpsd's reports are a few hundred bytes;
# anything approaching this is a fault, not a fix.
MAX_LINE_BYTES = 64 * 1024


class GpsdStream:
    kind = "gpsd"

    def __init__(self) -> None:
        self._latest: Any = None

    async def run(self, cfg: Any, emit: Any) -> None:
        parts = urlsplit(cfg.url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or DEFAULT_PORT

        async def connect() -> None:
            reader, writer = await asyncio.open_connection(host, port)
            log.info("gpsd %s: connected to %s:%d", cfg.id, host, port)
            try:
                writer.write(WATCH)
                await writer.drain()
                await asyncio.gather(
                    self._read(reader, cfg),
                    self._flush(cfg, emit),
                )
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (OSError, asyncio.CancelledError):
                    pass

        await with_reconnect(f"gpsd {cfg.id}", connect)

    async def _read(self, reader: asyncio.StreamReader, cfg: Any) -> None:
        while True:
            line = await reader.readline()
            if not line:
                return  # Far end closed; with_reconnect backs off and retries.
            if len(line) > MAX_LINE_BYTES:
                continue
            try:
                payload = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            fix = parse_gpsd_tpv(payload)
            if fix is not None:
                self._latest = fix

    async def _flush(self, cfg: Any, emit: Any) -> None:
        from .position import publish

        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            await emit(publish(self._latest, cfg, source="gpsd"))

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A GPS receiver read directly from its serial device.

For the case where gpsd is not running -- a bare USB puck on a machine that
does not have it, or an operator who would rather not add a daemon. Prefer
gpsd where it exists: it shares the device, and this takes it exclusively, so
running both means whichever opens first wins and the other silently sees
nothing.

**No new dependency.** pyserial is the usual answer and it is one more package
on a project that has deliberately kept to two. A serial port is a character
device, and the standard library's ``termios`` configures one -- so this opens
the device, sets the line discipline, and reads. About forty lines instead of a
dependency, on a project whose dependency list is part of its argument.

The read runs in a thread. A serial device is a blocking read that can sit idle
for a second between sentences, and doing that on the event loop would stall
every other source behind it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import termios
from typing import Any

from ..gps import parse_sentence
from .base import with_reconnect

log = logging.getLogger(__name__)

DEFAULT_BAUD = 4800  # The NMEA 0183 standard rate. USB pucks often use 9600.

# Baud rates termios can name. A receiver outside this set is unusual enough
# that saying so beats guessing.
BAUD_CONSTANTS = {
    4800: termios.B4800,
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}

FLUSH_SECONDS = 10.0
MAX_LINE_BYTES = 4096


def configure(fd: int, baud: int) -> None:
    """Put the port into the line discipline NMEA expects.

    8N1, no flow control, canonical mode off, and a read timeout so a receiver
    that stops talking does not wedge the thread forever.
    """
    if baud not in BAUD_CONSTANTS:
        raise ValueError(
            f"unsupported baud {baud}; try one of {', '.join(map(str, sorted(BAUD_CONSTANTS)))}"
        )
    speed = BAUD_CONSTANTS[baud]

    attrs = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs

    iflag = termios.IGNPAR  # Drop bytes with parity errors rather than marking them.
    oflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL  # 8 data bits, ignore modem lines.
    lflag = 0  # Raw: no echo, no line editing, no signal characters.

    cc = list(cc)
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 10  # Tenths of a second: a 1s read timeout.

    termios.tcsetattr(
        fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, speed, speed, cc]
    )
    termios.tcflush(fd, termios.TCIFLUSH)


class NmeaStream:
    kind = "nmea"

    def __init__(self) -> None:
        self._latest: Any = None
        self._stop = False

    async def run(self, cfg: Any, emit: Any) -> None:
        device = cfg.path
        if not device:
            raise ValueError(
                f"source {cfg.id!r}: kind 'nmea' needs path = \"/dev/ttyUSB0\", not a url"
            )
        baud = int((getattr(cfg, "options", {}) or {}).get("baud", DEFAULT_BAUD))

        async def connect() -> None:
            reader = asyncio.create_task(asyncio.to_thread(self._read_forever, device, baud))
            flusher = asyncio.create_task(self._flush(cfg, emit))
            try:
                await asyncio.gather(reader, flusher)
            finally:
                self._stop = True
                reader.cancel()
                flusher.cancel()

        await with_reconnect(f"nmea {cfg.id}", connect)

    def _read_forever(self, device: str, baud: int) -> None:
        """Blocking read loop. Runs in a thread; see the module docstring."""
        fd = os.open(device, os.O_RDONLY | os.O_NOCTTY)
        try:
            configure(fd, baud)
            log.info("nmea: reading %s at %d baud", device, baud)
            buffer = b""
            while not self._stop:
                chunk = os.read(fd, 512)
                if not chunk:
                    continue  # VTIME timeout, not end of stream.
                buffer += chunk
                # A partial sentence at the tail is normal; keep it for the
                # next chunk rather than parsing half a line.
                *lines, buffer = buffer.split(b"\n")
                if len(buffer) > MAX_LINE_BYTES:
                    buffer = b""  # A device emitting no newlines is not a GPS.
                for raw in lines:
                    try:
                        text = raw.decode("ascii", errors="ignore")
                    except UnicodeDecodeError:
                        continue
                    fix = parse_sentence(text)
                    if fix is not None:
                        self._latest = fix
        finally:
            os.close(fd)

    async def _flush(self, cfg: Any, emit: Any) -> None:
        from .position import publish

        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            await emit(publish(self._latest, cfg, source="nmea"))

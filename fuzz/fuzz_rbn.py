# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fuzz the Reverse Beacon Network client: the line parser, the tally and the read loop.

The feed is a TCP stream from a third party, so every byte of it is hostile
input. Line parsing is a regular expression plus range checks; the read loop
adds the line-length guard, UTF-8 decoding and the bounded tally.
"""

import sys

import atheris

with atheris.instrument_imports():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from hammunition_hill.streams.rbn import DEFAULT_WINDOW_SECONDS, RbnStream, parse_rbn_line

import _support

SEEDS = [
    b"",
    b"\x00DX de W3LPL-#:   14025.0  DL1ABC    CW    23 dB  28 WPM  CQ      1234Z\r\n",
    b"\x01DX de W3LPL-#:   14025.0  DL1ABC    CW    23 dB  28 WPM  CQ      1234Z\r\nDX de",
    b"\x00Welcome to the Reverse Beacon Network\r\n",
]

_CFG = SimpleNamespace(id="fuzz-rbn", options={"flush_seconds": 0.1})


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    mode = fdp.ConsumeIntInRange(0, 2)
    if mode == 2:
        # A spot line with fuzzed fields in the real order, several of them,
        # so the parser's range checks and the tally see plausible input.
        raw = "".join(_support.spot_line(fdp) + "\r\n" for _ in range(fdp.ConsumeIntInRange(1, 8)))
        mode = 1
        raw = raw.encode("utf-8", errors="replace")
    else:
        raw = fdp.ConsumeBytes(fdp.remaining_bytes())
    if mode == 0:
        # One line at a time, the way the parser is unit tested.
        spot = parse_rbn_line(raw.decode("utf-8", errors="replace"))
        if spot is not None:
            stream = RbnStream()
            stream.tally.add(spot, datetime.now(UTC))
            stream.tally.to_list()
        return

    # The real read loop, fed from memory, until the stream closes.
    stream = RbnStream()

    async def emit(_payload: object) -> None:
        return None

    async def drive(reader: object) -> None:
        await stream._read(reader, _CFG, emit, {"N0CALL"}, DEFAULT_WINDOW_SECONDS)

    _support.feed_stream(drive, raw)
    stream.payload({"N0CALL"}, DEFAULT_WINDOW_SECONDS)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()

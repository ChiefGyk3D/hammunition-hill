# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fuzz the DX cluster client: the spot parser and the read loop.

A cluster node is a stranger's server; spots, announcements and chat all arrive
on one stream. Nothing it sends may raise, and a line that is not a spot is
dropped.
"""

import sys

import atheris

with atheris.instrument_imports():
    from types import SimpleNamespace

    from hammunition_hill.streams.cluster import ClusterStream, parse_spot_line

import _support

SEEDS = [
    b"",
    b"\x00DX de W1ABC:     14074.0  JA1XYZ       FT8 -12 dB              1234Z\r\n",
    b"\x01DX de EA5ABC-#:   7011.5  K1TTT        CW 18 WPM CQ              0001Z\r\nDX de W1",
    b"\x01To ALL de W1ABC: WWV de BOU <18> : SFI=150\r\n",
]

_CFG = SimpleNamespace(id="fuzz-cluster", options={"flush_seconds": 0.1})


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    mode = fdp.ConsumeIntInRange(0, 2)
    if mode == 2:
        raw = "".join(_support.spot_line(fdp) + "\r\n" for _ in range(fdp.ConsumeIntInRange(1, 8)))
        mode = 1
        raw = raw.encode("utf-8", errors="replace")
    else:
        raw = fdp.ConsumeBytes(fdp.remaining_bytes())
    if mode == 0:
        parse_spot_line(raw.decode("utf-8", errors="replace"))
        return

    stream = ClusterStream()

    async def emit(_spots: object) -> None:
        return None

    async def drive(reader: object) -> None:
        await stream._read_spots(reader, _CFG, emit)

    _support.feed_stream(drive, raw)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()

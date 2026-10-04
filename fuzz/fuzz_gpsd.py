# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fuzz the gpsd JSON stream, and the NMEA sentence parser that shares its Fix type.

gpsd is local, but whatever speaks on port 2947 is not trusted: a line that is
not JSON, not an object, or an object with the wrong types must cost nothing.
The raw serial path (`parse_sentence`) takes bytes straight off a receiver.
"""

import sys

import atheris

with atheris.instrument_imports():
    from types import SimpleNamespace

    from hammunition_hill.gps import parse_sentence
    from hammunition_hill.streams.gpsd import GpsdStream

import _support

SEEDS = [
    b"",
    b'\x00{"class":"TPV","mode":3,"lat":39.0,"lon":-77.0,"time":"2026-01-01T00:00:00.000Z"}\n',
    b'\x00{"class":"TPV","mode":3,"lat":39.0,\n',
    b"\x01$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A",
    b"\x01$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47",
]

_TPV_KEYS = ["class", "mode", "lat", "lon", "time", "alt", "speed", "track"]
_CFG = SimpleNamespace(id="fuzz-gpsd", options={})


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    mode = fdp.ConsumeIntInRange(0, 2)
    if mode == 2:
        # Reports shaped like gpsd's: TPV objects with wrong types in each field.
        raw = (
            "\n".join(
                _support.json_text(
                    fdp, _TPV_KEYS, ["TPV", "SKY", "VERSION", "2026-01-01T00:00:00Z"]
                )
                for _ in range(fdp.ConsumeIntInRange(1, 6))
            )
            + "\n"
        ).encode()
    else:
        raw = fdp.ConsumeBytes(fdp.remaining_bytes())
    if mode == 1:
        parse_sentence(raw.decode("utf-8", errors="replace"))
        return

    stream = GpsdStream()

    async def drive(reader: object) -> None:
        await stream._read(reader, _CFG)

    _support.feed_stream(drive, raw)


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fuzz the satellite element-set parser, and the TLE source that wraps it.

Celestrak's text is third-party input. `parse_tles` skips a bad set unless
`strict`, in which case `TleError` (a `ValueError`) is its documented rejection.
When the optional propagator is installed, a parsed set is also propagated, so
a checksum-valid but absurd element set cannot crash the pass predictor.
"""

import sys
from datetime import UTC, datetime

import atheris

with atheris.instrument_imports():
    from hammunition_hill.config import SourceConfig
    from hammunition_hill.satellites import (
        Observer,
        TleError,
        parse_tles,
        propagator_available,
        upcoming,
    )
    from hammunition_hill.sources.base import FetchError
    from hammunition_hill.sources.tle import TleSource

import _support

_ISS_1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9005"
_ISS_2 = "2 25544  51.6400 208.9163 0006317  69.9862  25.2906 15.49560000    10"

SEEDS = [
    b"",
    b"\x00ISS (ZARYA)\n" + _ISS_1.encode() + b"\n" + _ISS_2.encode() + b"\n",
    b"\x01" + _ISS_1.encode() + b"\n" + _ISS_2.encode(),
    b"\x00ISS\n1 25544U",
]

_CFG = SourceConfig("tle", "tle", "https://celestrak.org/fuzz.txt")
_OBSERVER = Observer(lat=39.0, lon=-77.0)
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _with_checksum(line: str) -> str:
    """Pad to 68 columns and append the true checksum, so validation passes and the fields matter."""
    body = line[:68].ljust(68)
    return body + str(sum(int(c) if c in "0123456789" else 1 if c == "-" else 0 for c in body) % 10)


def _element_sets(fdp: atheris.FuzzedDataProvider) -> str:
    """Element sets whose checksums are right and whose fields are whatever the fuzzer likes."""
    out = []
    for _ in range(fdp.ConsumeIntInRange(1, 4)):
        number = f"{fdp.ConsumeIntInRange(0, 99999):05d}"
        field1 = fdp.ConsumeUnicodeNoSurrogates(60)
        field2 = fdp.ConsumeUnicodeNoSurrogates(60)
        out.append(fdp.ConsumeUnicodeNoSurrogates(20))
        out.append(_with_checksum(f"1 {number}U {field1}"))
        out.append(_with_checksum(f"2 {number} {field2}"))
    return "\n".join(out)


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    mode = fdp.ConsumeIntInRange(0, 2)
    if fdp.ConsumeBool():
        text = _element_sets(fdp)
    else:
        text = fdp.ConsumeBytes(fdp.remaining_bytes()).decode("utf-8", errors="replace")
    if mode == 0:
        sets = parse_tles(text)
        if propagator_available():
            # The collector's real path. A set SGP4 rejects is skipped by design
            # ("one satellite with unusable elements must not cost the other
            # ninety-nine"); anything else escaping here is a bug.
            upcoming(sets[:3], _OBSERVER, _NOW, hours=0.5)
    elif mode == 1:
        try:
            parse_tles(text, strict=True)
        except TleError:
            pass
    else:
        try:
            _support.fetch_with_body(TleSource(), _CFG, text.encode())
        except FetchError:
            pass


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()

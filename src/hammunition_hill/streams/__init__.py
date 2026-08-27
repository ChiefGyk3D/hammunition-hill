# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Stream registry.

Static, like the polled source registry, and for the same reason: a config file
must not be able to make the collector import arbitrary code.
"""

from __future__ import annotations

from typing import Any

from .cluster import ClusterStream
from .gpsd import GpsdStream
from .nmea import NmeaStream
from .rbn import RbnStream
from .rigctl import RigctlStream
from .wsjtx import WsjtxStream

STREAM_KINDS: dict[str, Any] = {
    ClusterStream.kind: ClusterStream,
    RbnStream.kind: RbnStream,
    WsjtxStream.kind: WsjtxStream,
    RigctlStream.kind: RigctlStream,
    GpsdStream.kind: GpsdStream,
    NmeaStream.kind: NmeaStream,
}


def is_stream(kind: str) -> bool:
    return kind in STREAM_KINDS


def build_stream(kind: str) -> Any:
    """A fresh instance per source -- streams hold per-connection state."""
    try:
        return STREAM_KINDS[kind]()
    except KeyError:
        raise ValueError(
            f"unknown stream kind {kind!r}; available: {', '.join(sorted(STREAM_KINDS))}"
        ) from None


__all__ = ["STREAM_KINDS", "build_stream", "is_stream"]

"""Stream registry.

Static, like the polled source registry, and for the same reason: a config file
must not be able to make the collector import arbitrary code.
"""

from __future__ import annotations

from typing import Any

from .cluster import ClusterStream
from .rigctl import RigctlStream
from .wsjtx import WsjtxStream

STREAM_KINDS: dict[str, Any] = {
    ClusterStream.kind: ClusterStream,
    WsjtxStream.kind: WsjtxStream,
    RigctlStream.kind: RigctlStream,
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

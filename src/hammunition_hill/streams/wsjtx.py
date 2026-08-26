"""WSJT-X UDP broadcasts.

WSJT-X can multicast every decode, status change, and logged QSO to a UDP port
on the local machine. Enable it under Settings -> Reporting -> UDP Server; the
default port is 2237.

This is a *listener*. It binds a socket and never sends -- WSJT-X's protocol has
reply messages that can change the running instance's state, and this project
has no business doing that. If a panel ever wants to drive WSJT-X, that is a
different program with a different threat model.

The wire format is Qt's QDataStream: big-endian, length-prefixed UTF-8 strings,
with 0xffffffff meaning null. Parsing is strictly bounded -- a malformed or
hostile datagram costs us that datagram and nothing else.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from collections import deque
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

MAGIC = 0xADBCCBDA
DEFAULT_PORT = 2237
MAX_DECODES = 100
MAX_DATAGRAM = 8192

# Message types we act on. The rest (heartbeat, clear, close, and the reply
# family we deliberately do not implement) are ignored.
TYPE_STATUS = 1
TYPE_DECODE = 2
TYPE_LOGGED = 5


class _Reader:
    """Bounded big-endian reader over one datagram."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def _take(self, count: int) -> bytes:
        if self._pos + count > len(self._data):
            raise ValueError("datagram truncated")
        chunk = self._data[self._pos : self._pos + count]
        self._pos += count
        return chunk

    def uint32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def int32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def uint64(self) -> int:
        return struct.unpack(">Q", self._take(8))[0]

    def double(self) -> float:
        return struct.unpack(">d", self._take(8))[0]

    def boolean(self) -> bool:
        return self._take(1) != b"\x00"

    def string(self) -> str | None:
        length = self.uint32()
        if length == 0xFFFFFFFF:
            return None
        if length > MAX_DATAGRAM:
            raise ValueError(f"string length {length} exceeds datagram size")
        return self._take(length).decode("utf-8", errors="replace")


def _ms_to_utc(ms_since_midnight: int) -> str:
    """WSJT-X sends time as milliseconds since UTC midnight."""
    seconds = (ms_since_midnight // 1000) % 86400
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def parse_datagram(data: bytes) -> dict[str, Any] | None:
    """Parse one WSJT-X datagram into a dict, or None if it is not one we use."""
    reader = _Reader(data)
    try:
        if reader.uint32() != MAGIC:
            return None
        reader.uint32()  # schema version; the fields we read are stable across it
        message_type = reader.uint32()
        client_id = reader.string()

        if message_type == TYPE_DECODE:
            is_new = reader.boolean()
            time_ms = reader.uint32()
            snr = reader.int32()
            delta_t = reader.double()
            delta_f = reader.uint32()
            mode = reader.string()
            message = reader.string()
            return {
                "type": "decode",
                "client": client_id,
                "new": is_new,
                "at": _ms_to_utc(time_ms),
                "snr": snr,
                "delta_t": round(delta_t, 1),
                "delta_f": delta_f,
                "mode": mode,
                "message": (message or "")[:64],
                "received_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }

        if message_type == TYPE_STATUS:
            dial_hz = reader.uint64()
            mode = reader.string()
            dx_call = reader.string()
            report = reader.string()
            tx_mode = reader.string()
            tx_enabled = reader.boolean()
            transmitting = reader.boolean()
            decoding = reader.boolean()
            return {
                "type": "status",
                "client": client_id,
                "khz": round(dial_hz / 1000.0, 2),
                "mode": mode,
                "dx_call": dx_call,
                "report": report,
                "tx_mode": tx_mode,
                "tx_enabled": tx_enabled,
                "transmitting": transmitting,
                "decoding": decoding,
            }

        if message_type == TYPE_LOGGED:
            reader.uint64()  # QDateTime off: date
            reader.uint32()  # QDateTime off: time
            reader.boolean()  # QDateTime off: timespec
            dx_call = reader.string()
            dx_grid = reader.string()
            dial_hz = reader.uint64()
            mode = reader.string()
            return {
                "type": "logged",
                "client": client_id,
                "call": dx_call,
                "grid": dx_grid,
                "khz": round(dial_hz / 1000.0, 2),
                "mode": mode,
                "received_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
    except (ValueError, struct.error) as exc:
        log.debug("ignoring malformed WSJT-X datagram: %s", exc)
        return None
    return None


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, on_message: Any) -> None:
        self._on_message = on_message

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) > MAX_DATAGRAM:
            return
        parsed = parse_datagram(data)
        if parsed is not None:
            self._on_message(parsed)


class WsjtxStream:
    """Listens for WSJT-X broadcasts and keeps recent decodes plus current status."""

    kind = "wsjtx"

    def __init__(self) -> None:
        self.decodes: deque[dict[str, Any]] = deque(maxlen=MAX_DECODES)
        self.status: dict[str, Any] | None = None
        self.last_logged: dict[str, Any] | None = None
        self._dirty = False

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.pop("type")
        if kind == "decode":
            self.decodes.append(message)
        elif kind == "status":
            self.status = message
        elif kind == "logged":
            self.last_logged = message
            log.info("WSJT-X logged %s on %s", message.get("call"), message.get("mode"))
        self._dirty = True

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decodes": list(self.decodes)[::-1],  # newest first, as the panel shows them
            "decode_count": len(self.decodes),
            "last_logged": self.last_logged,
        }

    async def run(self, cfg: Any, emit: Any) -> None:
        parts = urlsplit(cfg.url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or DEFAULT_PORT
        flush_interval = float(cfg.options.get("flush_seconds", 5))

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(self._handle), local_addr=(host, port), reuse_port=False
        )
        log.info("%s: listening for WSJT-X on %s:%d", cfg.id, host, port)

        try:
            while True:
                await asyncio.sleep(flush_interval)
                if self._dirty:
                    await emit(self.snapshot())
                    self._dirty = False
        finally:
            transport.close()

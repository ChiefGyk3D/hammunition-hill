# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Long-lived sources.

A polled source answers "what is the value now". A stream source holds a
connection open and produces events as they arrive: a DX cluster over telnet,
WSJT-X broadcasting decodes over UDP, rigctld reporting VFO state.

The shape is deliberately one-directional. A stream *emits*; nothing it receives
from the network can change what the collector fetches or where from. That is
the same property the polled sources have, and it is why adding streams does not
widen the design's security posture.

Snapshots are flushed on a timer rather than per event. A busy cluster produces
several spots a second; rewriting a file that often would be pointless churn
when the browser only polls every ten seconds.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)

# How long to wait before reconnecting, and the ceiling for the backoff.
RECONNECT_BASE_SECONDS = 5.0
RECONNECT_MAX_SECONDS = 300.0


class StreamSource(Protocol):
    """A source that holds a connection open."""

    kind: str

    async def run(self, cfg: Any, emit: Any) -> None:
        """Connect and emit until cancelled. Must not return on its own."""
        ...


async def with_reconnect(name: str, connect: Any) -> None:
    """Run ``connect()`` forever, backing off exponentially between failures.

    A cluster node going down should not take the panel with it, and it should
    not turn into a reconnect storm against someone else's server either.
    """
    delay = RECONNECT_BASE_SECONDS
    while True:
        try:
            await connect()
            # A clean return means the far end closed. Treat it as a failure
            # for backoff purposes; a node that drops us repeatedly deserves
            # the same patience as one that refuses us.
            log.info("%s: connection closed by peer", name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a stream must never kill the collector
            log.warning("%s: %s: %s", name, type(exc).__name__, exc)

        log.info("%s: reconnecting in %.0fs", name, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX_SECONDS)

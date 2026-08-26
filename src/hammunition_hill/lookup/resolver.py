# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Resolving the callsigns you are already seeing.

This is the mode that keeps the architecture intact. The collector resolves
callsigns that appear in your own data -- cluster spots, WSJT-X decodes -- on
its normal schedule, caps how many it does per cycle, and publishes the results.
No request causes a fetch, because nothing here is triggered by a request.

It answers "who is this station I am looking at", which is the question a
dashboard is actually asked. It does not answer "tell me about an arbitrary
callsign"; see docs/CALLSIGN-LOOKUP.md for why that needs an endpoint and how to
turn one on.

**With a network provider, the callsigns you are watching go to that provider.**
That is inherent, not incidental, and the docs say so plainly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..egress import EgressDenied, EgressGuard
from .base import LookupError, LookupProvider
from .cache import LookupCache

log = logging.getLogger(__name__)

# Be a good guest. Free services are run by volunteers, and a busy cluster can
# produce hundreds of new callsigns an hour.
DEFAULT_MAX_PER_CYCLE = 20
DEFAULT_CYCLE_SECONDS = 60
BETWEEN_REQUESTS_SECONDS = 1.0


class Resolver:
    """Drains seen callsigns, resolves the unknown ones, fills the cache."""

    def __init__(
        self,
        provider: LookupProvider,
        cache: LookupCache,
        guard: EgressGuard,
        *,
        max_per_cycle: int = DEFAULT_MAX_PER_CYCLE,
        cycle_seconds: int = DEFAULT_CYCLE_SECONDS,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.guard = guard
        self.max_per_cycle = max(1, max_per_cycle)
        self.cycle_seconds = max(10, cycle_seconds)
        self.resolved = 0
        self.failed = 0

    def _allowed(self) -> bool:
        """Confirm the provider's hosts pass egress policy before we start."""
        for host in self.provider.hosts:
            try:
                self.guard.check(f"https://{host}/")
            except EgressDenied as exc:
                log.error("lookup provider %s refused: %s", self.provider.name, exc)
                return False
        return True

    async def resolve_batch(self, client: httpx.AsyncClient, callsigns: list[str]) -> int:
        """Resolve up to the per-cycle cap. Returns how many were attempted."""
        pending = [call for call in callsigns if not self.cache.knows(call)]
        if not pending:
            return 0

        attempted = 0
        for callsign in pending[: self.max_per_cycle]:
            try:
                result = await self.provider.resolve(client, callsign)
            except (LookupError, httpx.HTTPError) as exc:
                # A failure is not cached: a rate limit or a network blip should
                # not lock in a miss for a day.
                self.failed += 1
                log.warning("lookup %s failed: %s", callsign, exc)
                attempted += 1
                continue

            self.cache.put(callsign, result)
            self.resolved += 1 if result else 0
            attempted += 1
            await asyncio.sleep(BETWEEN_REQUESTS_SECONDS)

        if attempted:
            self.cache.save()
            log.info(
                "lookup: %d attempted, %d pending (%s)",
                attempted,
                max(0, len(pending) - attempted),
                self.provider.name,
            )
        return attempted

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name,
            "worldwide": self.provider.worldwide,
            "results": self.cache.hits(),
            "resolved_this_run": self.resolved,
            "failed_this_run": self.failed,
            **self.cache.stats(),
        }

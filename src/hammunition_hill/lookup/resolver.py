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
That is inherent, not incidental, and the docs say so plainly. An offline
provider does not have this property, which is one of the reasons to put one
first in the chain.

## Chains, and going off the air

Providers are tried in order. A provider that answers wins; one that says "not
on file" falls through to the next, which is what makes an offline US index a
good first link -- it declines every non-US callsign instantly and for free, and
the network provider behind it only ever sees the calls it is actually needed
for.

When the network goes -- at a park, in a field, on a hilltop, which is the
normal condition for a portable station rather than an exception -- network
providers are skipped rather than waited on. Without that, a cycle with a full
batch of callsigns spends the timeout on every one of them, in sequence, and a
dashboard that should have answered instantly from a local index instead does
nothing for minutes. The offline links carry on untouched.
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

# Consecutive network failures before we conclude the WAN is gone and stop
# waiting on network providers. Two rather than one: a single timeout is a blip,
# and marking the network down on one bad response would make a busy cluster
# flap in and out of offline mode.
OFFLINE_AFTER_FAILURES = 2

# How long to stay in that conclusion before trying the network again. Long
# enough that a genuinely dead link is not retried every cycle; short enough
# that coming back into coverage is noticed within a few minutes.
OFFLINE_RETRY_SECONDS = 300


class Resolver:
    """Drains seen callsigns, resolves the unknown ones, fills the cache."""

    def __init__(
        self,
        providers: LookupProvider | list[LookupProvider],
        cache: LookupCache,
        guard: EgressGuard,
        *,
        max_per_cycle: int = DEFAULT_MAX_PER_CYCLE,
        cycle_seconds: int = DEFAULT_CYCLE_SECONDS,
    ) -> None:
        # A single provider is still accepted: a chain of one is the same thing,
        # and every caller that predates chains keeps working.
        self.providers = list(providers) if isinstance(providers, list) else [providers]
        self.cache = cache
        self.guard = guard
        self.max_per_cycle = max(1, max_per_cycle)
        self.cycle_seconds = max(10, cycle_seconds)
        self.resolved = 0
        self.failed = 0

        self._network_failures = 0
        self._offline_until = 0.0
        self.by_provider: dict[str, int] = {}

    @property
    def provider(self) -> LookupProvider:
        """The head of the chain, for messages and snapshots that name one."""
        return self.providers[0]

    @property
    def offline_providers(self) -> list[LookupProvider]:
        return [p for p in self.providers if p.offline]

    @property
    def network_is_down(self) -> bool:
        return asyncio.get_event_loop().time() < self._offline_until

    def _allowed(self) -> bool:
        """Confirm every provider's hosts pass egress policy before we start.

        A provider whose hosts are refused is dropped from the chain rather than
        disabling lookup entirely -- if the FCC index is configured alongside a
        blocked network provider, the offline half should still work.
        """
        kept: list[LookupProvider] = []
        for provider in self.providers:
            refused = None
            for host in provider.hosts:
                try:
                    self.guard.check(f"https://{host}/")
                except EgressDenied as exc:
                    refused = exc
                    break
            if refused is not None:
                log.error("lookup provider %s refused: %s", provider.name, refused)
                continue
            kept.append(provider)

        self.providers = kept
        return bool(kept)

    def _usable(self) -> list[LookupProvider]:
        """The chain as it stands right now, minus anything we cannot reach."""
        if self.network_is_down:
            return self.offline_providers
        return self.providers

    def _note_network_failure(self) -> None:
        self._network_failures += 1
        if self._network_failures < OFFLINE_AFTER_FAILURES:
            return
        if self.network_is_down:
            return
        self._offline_until = asyncio.get_event_loop().time() + OFFLINE_RETRY_SECONDS
        offline = [p.name for p in self.offline_providers]
        log.warning(
            "lookup: network providers unreachable, skipping them for %ds%s",
            OFFLINE_RETRY_SECONDS,
            f" (still resolving from {', '.join(offline)})" if offline else "",
        )

    def _note_network_success(self) -> None:
        if self._network_failures or self._offline_until:
            log.info("lookup: network providers reachable again")
        self._network_failures = 0
        self._offline_until = 0.0

    async def _resolve_one(self, client: httpx.AsyncClient, callsign: str) -> tuple[Any, bool]:
        """Walk the chain for one callsign.

        Returns ``(result, decided)``. ``decided`` is False when every provider
        errored -- as opposed to answering "not on file" -- because those are
        different facts and only one of them is worth caching. Caching a miss
        because the WAN was down would hide that callsign for a day after it
        came back.
        """
        chain = self._usable()
        errored = False

        for provider in chain:
            try:
                result = await provider.resolve(client, callsign)
            except (LookupError, httpx.HTTPError) as exc:
                errored = True
                if not provider.offline:
                    self._note_network_failure()
                log.debug("lookup %s via %s failed: %s", callsign, provider.name, exc)
                continue

            if not provider.offline:
                self._note_network_success()

            if result is not None:
                self.by_provider[provider.name] = self.by_provider.get(provider.name, 0) + 1
                return result, True

            # "Not on file" here is a real answer, and it is why an offline US
            # index makes a good first link: it declines every non-US callsign
            # for free, so the paid provider behind it only sees what it is
            # actually needed for.

        # Every provider declined and none errored -- the callsign is genuinely
        # not on file anywhere we asked, which is worth remembering.
        return None, not errored

    async def resolve_batch(self, client: httpx.AsyncClient, callsigns: list[str]) -> int:
        """Resolve up to the per-cycle cap. Returns how many were attempted."""
        pending = [call for call in callsigns if not self.cache.knows(call)]
        if not pending:
            return 0
        if not self._usable():
            return 0

        attempted = 0
        for callsign in pending[: self.max_per_cycle]:
            result, decided = await self._resolve_one(client, callsign)
            attempted += 1

            if not decided:
                # A rate limit or a dead link must not lock in a miss for a day.
                self.failed += 1
                continue

            self.cache.put(callsign, result)
            self.resolved += 1 if result else 0

            # Only pause for providers that actually went out to the network.
            # Sleeping a second per callsign against a local SQLite index would
            # make an offline lookup slower than a networked one, which is the
            # wrong way round.
            if result is not None and not self._is_offline_source(result.source):
                await asyncio.sleep(BETWEEN_REQUESTS_SECONDS)

        if attempted:
            self.cache.save()
            log.info(
                "lookup: %d attempted, %d pending (%s)",
                attempted,
                max(0, len(pending) - attempted),
                ", ".join(p.name for p in self._usable()),
            )
        return attempted

    def _is_offline_source(self, source: str) -> bool:
        return any(p.name == source and p.offline for p in self.providers)

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name if self.providers else "none",
            "providers": [
                {"name": p.name, "offline": p.offline, "worldwide": p.worldwide}
                for p in self.providers
            ],
            "worldwide": any(p.worldwide for p in self.providers),
            "offline_capable": bool(self.offline_providers),
            "network_down": self.network_is_down,
            "resolved_by": dict(sorted(self.by_provider.items())),
            "results": self.cache.hits(),
            "resolved_this_run": self.resolved,
            "failed_this_run": self.failed,
            **self.cache.stats(),
        }

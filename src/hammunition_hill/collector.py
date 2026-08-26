"""The collector: fixed schedule in, snapshot files out.

Each source gets its own task looping on its own interval. Nothing here reacts
to an inbound request -- there is no code path from the HTTP server into this
module, which is the property the whole design rests on.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime

import httpx

from .config import Config, SourceConfig
from .egress import EgressDenied, EgressGuard
from .snapshot import Snapshot, read_snapshot, write_snapshot
from .sources import FetchError, get_source
from .sources.base import USER_AGENT

log = logging.getLogger(__name__)

# A source is considered stale at twice its interval. One missed cycle is a
# blip; two means the panel should say so rather than keep showing the number.
STALE_MULTIPLIER = 2

REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0)


def build_client(guard: EgressGuard) -> httpx.AsyncClient:
    """An HTTP client with the policy we want everywhere.

    Redirects are not followed. An upstream that moves should be fixed in config,
    not chased at runtime -- following a redirect would let an upstream send us
    to a host the allowlist never approved.
    """
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        timeout=REQUEST_TIMEOUT,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        trust_env=False,  # No surprise proxying from ambient environment variables.
    )


async def run_once(
    client: httpx.AsyncClient, guard: EgressGuard, cfg: SourceConfig, config: Config
) -> Snapshot:
    """Fetch one source and persist the result. Never raises for upstream failure."""
    now = datetime.now(UTC)
    stale_after = cfg.interval * STALE_MULTIPLIER

    try:
        guard.check(cfg.url)
        source = get_source(cfg.kind)
        data = await source.fetch(client, cfg)
    except (EgressDenied, FetchError, httpx.HTTPError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        log.warning("source %s failed: %s", cfg.id, reason)

        # Keep the last good reading and mark it failed, so a panel can show
        # "20 minutes old, last fetch failed" rather than going blank. A blank
        # panel and a stale panel are different problems for an operator.
        previous = read_snapshot(config.data_dir, cfg.id)
        if previous and previous.get("data") is not None:
            snapshot = Snapshot(
                source_id=cfg.id,
                kind=cfg.kind,
                fetched_at=datetime.fromisoformat(
                    previous["fetched_at"].replace("Z", "+00:00")
                ),
                stale_after_seconds=stale_after,
                data=previous["data"],
                error=reason,
            )
        else:
            snapshot = Snapshot(cfg.id, cfg.kind, now, stale_after, None, error=reason)
        write_snapshot(config.data_dir, snapshot)
        return snapshot

    snapshot = Snapshot(cfg.id, cfg.kind, now, stale_after, data)
    write_snapshot(config.data_dir, snapshot)
    log.info("source %s updated", cfg.id)
    return snapshot


async def _source_loop(
    client: httpx.AsyncClient, guard: EgressGuard, cfg: SourceConfig, config: Config
) -> None:
    # Stagger the first fetch so a restart does not fire every source at once.
    await asyncio.sleep(random.uniform(0, min(5.0, cfg.interval / 4)))  # noqa: S311
    while True:
        await run_once(client, guard, cfg, config)
        await asyncio.sleep(cfg.interval)


async def run_collector(config: Config, guard: EgressGuard) -> None:
    """Run every source loop until cancelled."""
    if not config.sources:
        log.warning("no sources configured; the dashboard will show tier 0 panels only")
        return

    async with build_client(guard) as client:
        async with asyncio.TaskGroup() as group:
            for source in config.sources:
                group.create_task(
                    _source_loop(client, guard, source, config), name=f"source:{source.id}"
                )

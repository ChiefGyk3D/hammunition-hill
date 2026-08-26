# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The collector: fixed schedule in, snapshot files out.

Three kinds of work, all writing the same snapshot files:

- **polled** sources fetch a URL on an interval;
- **stream** sources hold a socket open and flush on a timer;
- **file** sources read something on this disk, such as the ADIF log.

None of them react to an inbound request. There is no code path from the HTTP
server into this module, which is the property the whole design rests on.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from typing import Any

import httpx

from .config import Config, SourceConfig
from .egress import EgressDenied, EgressGuard
from .enrich import Enricher
from .snapshot import Snapshot, read_snapshot, write_snapshot
from .sources import FetchError, get_local, get_source, is_local
from .sources.base import USER_AGENT
from .streams import build_stream, is_stream

log = logging.getLogger(__name__)

# A source is considered stale at twice its interval. One missed cycle is a
# blip; two means the panel should say so rather than keep showing the number.
STALE_MULTIPLIER = 2

# Streams have no interval, so their snapshots carry a fixed staleness budget.
STREAM_STALE_SECONDS = 120

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


def _now() -> datetime:
    return datetime.now(UTC)


def _write(config: Config, cfg: SourceConfig, data: Any, stale: int) -> Snapshot:
    snapshot = Snapshot(cfg.id, cfg.kind, _now(), stale, data)
    write_snapshot(config.data_dir, snapshot)
    return snapshot


def _write_failure(config: Config, cfg: SourceConfig, reason: str, stale: int) -> Snapshot:
    """Record a failure without discarding the last good reading.

    A panel can then show "20 minutes old, last fetch failed" rather than going
    blank. A blank panel and a stale panel are different problems for an
    operator, and with the WAN down that distinction is the point.
    """
    previous = read_snapshot(config.data_dir, cfg.id)
    if previous and previous.get("data") is not None:
        snapshot = Snapshot(
            source_id=cfg.id,
            kind=cfg.kind,
            fetched_at=datetime.fromisoformat(previous["fetched_at"].replace("Z", "+00:00")),
            stale_after_seconds=stale,
            data=previous["data"],
            error=reason,
        )
    else:
        snapshot = Snapshot(cfg.id, cfg.kind, _now(), stale, None, error=reason)
    write_snapshot(config.data_dir, snapshot)
    return snapshot


# --- polled sources -------------------------------------------------------
async def run_once(
    client: httpx.AsyncClient, guard: EgressGuard, cfg: SourceConfig, config: Config
) -> Snapshot:
    """Fetch one source and persist the result. Never raises for upstream failure."""
    stale = cfg.interval * STALE_MULTIPLIER
    try:
        guard.check(cfg.url)
        data = await get_source(cfg.kind).fetch(client, cfg)
    except (EgressDenied, FetchError, httpx.HTTPError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        log.warning("source %s failed: %s", cfg.id, reason)
        return _write_failure(config, cfg, reason, stale)

    log.info("source %s updated", cfg.id)
    return _write(config, cfg, data, stale)


async def _polled_loop(
    client: httpx.AsyncClient, guard: EgressGuard, cfg: SourceConfig, config: Config
) -> None:
    # Stagger the first fetch so a restart does not fire every source at once.
    await asyncio.sleep(random.uniform(0, min(5.0, cfg.interval / 4)))  # noqa: S311
    while True:
        await run_once(client, guard, cfg, config)
        await asyncio.sleep(cfg.interval)


# --- file sources ---------------------------------------------------------
async def _file_loop(cfg: SourceConfig, config: Config, enricher: Enricher) -> None:
    """Re-read a local file on an interval.

    Runs in a thread: a large ADIF log is a blocking read and a blocking parse,
    and blocking the event loop would stall every other source behind it.
    """
    source = get_local(cfg.kind)
    while True:
        try:
            data = await asyncio.to_thread(source.load, cfg, enricher)
            _write(config, cfg, data, cfg.interval * STALE_MULTIPLIER)
            log.info("source %s reloaded", cfg.id)
        except Exception as exc:  # noqa: BLE001 - a bad log must not stop the collector
            reason = f"{type(exc).__name__}: {exc}"
            log.warning("source %s failed: %s", cfg.id, reason)
            _write_failure(config, cfg, reason, cfg.interval * STALE_MULTIPLIER)
        await asyncio.sleep(cfg.interval)


# --- stream sources -------------------------------------------------------
async def _stream_loop(
    guard: EgressGuard, cfg: SourceConfig, config: Config, enricher: Enricher
) -> None:
    """Hold a connection open, writing a snapshot each time the stream flushes."""
    try:
        guard.check_stream(cfg.url)
    except EgressDenied as exc:
        log.error("stream %s refused: %s", cfg.id, exc)
        _write_failure(config, cfg, f"EgressDenied: {exc}", STREAM_STALE_SECONDS)
        return

    stream = build_stream(cfg.kind)

    async def emit(payload: Any) -> None:
        # Cluster spots arrive raw and are enriched here, at flush time, so a
        # log reload is picked up by the next flush without the stream knowing
        # anything about the log.
        if cfg.kind == "dxcluster":
            payload = {
                "spots": enricher.enrich_spots(payload),
                "count": len(payload),
                "station": enricher.station.callsign,
                "has_log": enricher.log_index is not None,
            }
        _write(config, cfg, payload, STREAM_STALE_SECONDS)

    try:
        await stream.run(cfg, emit)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - one bad stream must not end the run
        # Streams retry internally; reaching here means setup failed in a way
        # retrying cannot fix (a bad config, an unusable address). Record it and
        # let every other source carry on -- and the dashboard keep serving.
        reason = f"{type(exc).__name__}: {exc}"
        log.error("stream %s stopped: %s", cfg.id, reason)
        _write_failure(config, cfg, reason, STREAM_STALE_SECONDS)


# --- entry point ----------------------------------------------------------
async def run_collector(config: Config, guard: EgressGuard, enricher: Enricher) -> None:
    """Run every source until cancelled."""
    if not config.sources:
        log.warning("no sources configured; the dashboard will show tier 0 panels only")
        return

    # Load the log before anything else, so the first flush of spots already
    # knows what is needed rather than colouring everything as unknown.
    for cfg in config.sources:
        if is_local(cfg.kind):
            try:
                await asyncio.to_thread(get_local(cfg.kind).load, cfg, enricher)
            except Exception as exc:  # noqa: BLE001
                log.warning("initial load of %s failed: %s", cfg.id, exc)

    async with build_client(guard) as client:
        async with asyncio.TaskGroup() as group:
            for cfg in config.sources:
                if is_local(cfg.kind):
                    coro = _file_loop(cfg, config, enricher)
                elif is_stream(cfg.kind):
                    coro = _stream_loop(guard, cfg, config, enricher)
                else:
                    coro = _polled_loop(client, guard, cfg, config)
                group.create_task(coro, name=f"source:{cfg.id}")

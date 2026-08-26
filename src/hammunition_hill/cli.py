"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .collector import run_collector
from .config import Config, ConfigError, ServerConfig, load_config
from .egress import EgressDenied, EgressGuard
from .enrich import Enricher, Station
from .prefix import PrefixTable
from .server import build_csp, build_server
from .snapshot import Snapshot, write_snapshot
from .streams import is_stream

log = logging.getLogger("hammunition_hill")

LAN_WARNING = """
  ┌──────────────────────────────────────────────────────────────────────┐
  │  LISTENING BEYOND LOOPBACK: {bind:<40} │
  │                                                                      │
  │  Hammunition Hill has no authentication, by design. Anyone who can   │
  │  reach this port sees your dashboard, your QTH, and your rig state.  │
  │  The network is the only access control there is.                    │
  │                                                                      │
  │  Never expose this to the internet. Reach it over ZTNA or a VPN --   │
  │  Twingate, NetBird, Tailscale, Headscale, WireGuard. Do not port     │
  │  forward. See docs/SECURITY.md.                                      │
  └──────────────────────────────────────────────────────────────────────┘
"""


def _parse_listen(value: str) -> ServerConfig:
    """Accept HOST, :PORT, or HOST:PORT. IPv6 needs brackets."""
    raw = value.strip()
    host, port = raw, 8073
    if raw.startswith("["):  # [::1]:8073
        close = raw.index("]")
        host, rest = raw[1:close], raw[close + 1 :]
        if rest.startswith(":"):
            port = int(rest[1:])
    elif ":" in raw:
        host_part, port_part = raw.rsplit(":", 1)
        host, port = host_part or "127.0.0.1", int(port_part)
    return ServerConfig(host=host, port=port)


def _publish_station(config: Config) -> None:
    """Write station details as a snapshot so web/ needs no templating.

    Callsign and grid never leave the browser -- tier 0 panels use them for
    bearing, distance, and greyline entirely client-side.
    """
    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="station",
            kind="station",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data=dict(config.station),
        ),
    )


def build_enricher(config: Config) -> Enricher:
    """Prefix table plus station location, shared by every source that needs it."""
    table = PrefixTable(config.cty_dat)
    station = Station.from_config(config.station)
    if not station.located:
        log.warning(
            "[station] has no grid or lat/lon: bearings and distances will be omitted"
        )
    return Enricher(table, station)


def _serve(config: Config, guard: EgressGuard, enricher: Enricher) -> int:
    _publish_station(config)
    server = build_server(config)
    bind = f"{config.server.host}:{config.server.port}"

    if not config.server.is_loopback_only:
        print(LAN_WARNING.format(bind=bind), file=sys.stderr)

    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    log.info("dashboard on http://%s  (%d sources)", bind, len(config.sources))

    try:
        asyncio.run(run_collector(config, guard, enricher))
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.shutdown()
        server.server_close()
    return 0


def _check(config: Config, guard: EgressGuard, enricher: Enricher) -> int:
    """Validate config and egress policy without fetching anything."""
    print(f"config       : {len(config.sources)} source(s)")
    print(f"data dir     : {config.data_dir}")
    print(f"web dir      : {config.web_dir}")
    print(f"bind         : {config.server.host}:{config.server.port}", end="")
    print("  (loopback only)" if config.server.is_loopback_only else "  ** LAN EXPOSED **")

    station = enricher.station
    location = f"{station.lat:.3f},{station.lon:.3f}" if station.located else "NOT SET"
    print(f"station      : {station.callsign or '?'} {station.grid or ''} -> {location}")
    caveat = ""
    if enricher.table.approximate:
        caveat = "  (approximate -- set [log] cty_dat for accuracy)"
    print(f"prefixes     : {enricher.table.source}{caveat}")
    print(f"csp          : {build_csp(config.embed_hosts)}")
    print()

    failures = 0
    for source in config.sources:
        if source.is_file_source:
            exists = Path(source.path).expanduser().is_file()  # type: ignore[arg-type]
            marker = "file" if exists else "MISSING"
            if not exists:
                failures += 1
            print(f"  {marker:<7} {source.id:<20} {source.kind:<10} {source.path}")
            continue

        check = guard.check_stream if is_stream(source.kind) else guard.check
        try:
            check(source.url)
        except EgressDenied as exc:
            failures += 1
            print(f"  DENIED  {source.id:<20} {exc}")
        else:
            marker = "local" if source.local else ("stream" if is_stream(source.kind) else "ok")
            print(f"  {marker:<7} {source.id:<20} {source.kind:<10} {source.host}")

    if failures:
        print(f"\n{failures} source(s) need attention.", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hamhill",
        description="Local-first ham radio dashboard. Loopback by default; never expose it.",
    )
    parser.add_argument("--version", action="version", version=f"hammunition-hill {__version__}")
    parser.add_argument(
        "-c", "--config", type=Path, default=Path("config.toml"), help="path to config.toml"
    )
    parser.add_argument(
        "-l",
        "--listen",
        metavar="HOST[:PORT]",
        help="override the bind address. Anything but loopback prints the network warning.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument(
        "command", nargs="?", default="serve", choices=("serve", "check"), help="default: serve"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.listen:
        config = dataclasses.replace(config, server=_parse_listen(args.listen))

    allowed, local = config.allowlist()
    guard = EgressGuard.build(allowed, local)
    enricher = build_enricher(config)

    if args.command == "check":
        return _check(config, guard, enricher)
    return _serve(config, guard, enricher)

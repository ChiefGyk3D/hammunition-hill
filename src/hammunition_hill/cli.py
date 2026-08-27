# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import errno
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
from .snapshot import Snapshot, read_snapshot, write_snapshot
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


def _publish_station(config: Config, enricher: Enricher) -> None:
    """Write station details as a snapshot so web/ needs no templating.

    Publishes the *derived* station, including the coordinates worked out from
    the grid square -- panels that compute bearings need lat/lon, and making
    each of them re-parse the grid would be three copies of the same maths.

    None of this leaves the machine. It is used here and in the browser.
    """
    station = enricher.station
    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="station",
            kind="station",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data={
                "callsign": station.callsign,
                "grid": station.grid,
                "lat": station.lat,
                "lon": station.lon,
                "located": station.located,
                "license_class": station.license_class,
                "license_certain": station.license_certain,
                "license_reason": station.license_reason,
            },
        ),
    )


def build_enricher(config: Config) -> Enricher:
    """Prefix table plus station location, shared by every source that needs it."""
    table = PrefixTable(config.cty_dat)
    station = Station.from_config(config.station, table)
    if not station.located:
        log.warning("[station] has no grid or lat/lon: bearings and distances will be omitted")
    return Enricher(table, station)


def _publish_prefixes(config: Config, enricher: Enricher) -> None:
    """Publish the prefix table so the browser can resolve callsigns itself.

    Written once at startup: the table only changes when cty.dat does, and a
    restart is the natural moment to pick that up.
    """
    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="prefixes",
            kind="prefixes",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data=enricher.table.export(),
        ),
    )


def _publish_imagery(config: Config) -> None:
    """Publish the tile list so the imagery panel needs no config of its own.

    Written once at startup like the prefix table: it is config, and a restart
    is the moment config changes. Nothing here is fetched -- the collector is
    publishing a list of URLs it will never request, for the browser to request
    instead. That asymmetry is the whole point of the tier 2 label the panel
    puts on every tile.
    """
    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="imagery",
            kind="imagery",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data={
                "tiles": [dataclasses.asdict(tile) for tile in config.imagery],
                "groups": sorted({tile.group for tile in config.imagery}),
                "hosts": list(config.csp_hosts()),
            },
        ),
    )


def _web_dir_problem(config: Config) -> str | None:
    """Why the web directory cannot serve a dashboard, if it cannot.

    The supported install is a git clone, where `web/` sits next to the config.
    Someone who instead `pip install`s the package gets the CLI and no web
    assets -- they are not in the wheel -- and without this check the symptom is
    a dashboard that returns 404 for everything, with nothing in the log saying
    why. An empty page is a bad way to learn about a packaging boundary.
    """
    if not config.web_dir.is_dir():
        return f"no web directory at {config.web_dir}"
    if not (config.web_dir / "index.html").is_file():
        return f"{config.web_dir} has no index.html"
    if not (config.web_dir / "panels" / "index.json").is_file():
        return f"{config.web_dir} has no panels/index.json"
    return None


WEB_DIR_HELP = """
  The dashboard's files are not where this expects them.

  hammunition-hill is installed from a git clone -- the web/ directory lives in
  the repository, not in the Python package. If you installed with pip alone,
  clone the repository instead:

      git clone https://github.com/ChiefGyk3D/hammunition-hill
      cd hammunition-hill && pip install -e .

  Or point [paths] web_dir at a checkout you already have.
"""


def _publish_morse(config: Config) -> None:
    """Publish the Morse reference tables.

    Written once at startup, like the prefix table, and for the same reason:
    the canonical tables live in Python where they are tested, and the browser
    receives them as data. A panel cannot then disagree with a test about what
    `..-.` means.
    """
    from . import cwpractice
    from .morse import reference

    # One snapshot rather than two. The tables and the curriculum are both
    # startup-time reference data read by the same panel, and splitting them
    # would buy a second source id and nothing else.
    data = reference()
    data["practice"] = cwpractice.reference()

    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="morse",
            kind="morse",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data=data,
        ),
    )


def _publish_antenna(config: Config) -> None:
    """Publish the antenna, feedline and SWR tables.

    Written once at startup like the Morse tables and for the same reason: the
    numbers live in Python where they are checked against datasheets and rules
    of thumb, and the browser receives them as data. A panel cannot then
    disagree with a test about how long a 40 m dipole is.
    """
    from .antenna import reference

    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="antenna",
            kind="antenna",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data=reference(),
        ),
    )


def _publish_exams(config: Config) -> None:
    """Publish the question pools that ship with this package.

    Shipped rather than imported, because a pool changes every four years and
    making every operator run a command to get one would mean most of them never
    do. They are the official releases, parsed once by `hamhill exam-import` and
    checked in with their provenance and their effective dates.

    An operator who imports a newer pool keeps it. The shipped copy is written
    only when there is no snapshot for that element, or when the snapshot on
    disk is itself a shipped one -- so upgrading the package refreshes what it
    shipped and never overwrites what somebody imported.
    """
    from .exam import shipped_pools

    for element_id, payload in shipped_pools().items():
        source_id = f"exam-{element_id}"
        existing = read_snapshot(config.data_dir, source_id)
        if existing is not None and not (existing.get("data") or {}).get("shipped"):
            continue
        write_snapshot(
            config.data_dir,
            Snapshot(
                source_id=source_id,
                kind="exam",
                fetched_at=datetime.now(UTC),
                stale_after_seconds=0,
                data=payload,
            ),
        )


def _publish_part97(config: Config) -> None:
    """Publish 47 CFR Part 97, so a rules answer can show the rule.

    Its own snapshot rather than a field on each pool: it is 154 kB and all
    three elements cite the same regulation, so attaching it to each would ship
    it three times and make every pool fetch carry it whether or not the reader
    ever opens an explanation.

    Written unconditionally, unlike the pools. There is no `part97-import` that
    an operator's copy could be overwritten by -- the importer exists, but what
    it produces is checked in, and the CFR is not something anybody is expected
    to hold a personal edition of.
    """
    from .part97 import shipped

    payload = shipped()
    if not payload:
        return
    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="part97",
            kind="part97",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data=payload,
        ),
    )


def _serve(config: Config, guard: EgressGuard, enricher: Enricher) -> int:
    if (problem := _web_dir_problem(config)) is not None:
        print(f"cannot serve: {problem}", file=sys.stderr)
        print(WEB_DIR_HELP, file=sys.stderr)
        return 1

    _publish_station(config, enricher)
    _publish_prefixes(config, enricher)
    _publish_imagery(config)
    _publish_morse(config)
    _publish_antenna(config)
    _publish_exams(config)
    _publish_part97(config)

    bind = f"{config.server.host}:{config.server.port}"
    try:
        server = build_server(config)
    except OSError as exc:
        # "Address already in use" is the common one, and a traceback is a poor
        # way to say "something else is on that port" -- especially since the
        # something else is usually another copy of this.
        print(f"cannot listen on {bind}: {exc.strerror or exc}", file=sys.stderr)
        if exc.errno == errno.EADDRINUSE:
            print(
                "  another process is using that port — stop it, or pick another with --listen",
                file=sys.stderr,
            )
        return 1

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


def _check(config: Config, guard: EgressGuard, enricher: Enricher, *, offline: bool = False) -> int:
    """Validate config and egress policy without fetching anything.

    ``offline`` additionally skips DNS. The egress guard resolves every host to
    check it is not a private address, which is the right thing to do and makes
    this command depend on working DNS -- awkward on a shack machine with the
    WAN down, and worse in CI, where a transient resolver blip would fail a
    build for a reason that has nothing to do with the change under test.
    """
    print(f"config       : {len(config.sources)} source(s)")
    print(f"data dir     : {config.data_dir}")
    web_problem = _web_dir_problem(config)
    web_note = "" if web_problem is None else f"  ** {web_problem} **"
    print(f"web dir      : {config.web_dir}{web_note}")
    print(f"bind         : {config.server.host}:{config.server.port}", end="")
    print("  (loopback only)" if config.server.is_loopback_only else "  ** LAN EXPOSED **")

    station = enricher.station
    location = f"{station.lat:.3f},{station.lon:.3f}" if station.located else "NOT SET"
    print(f"station      : {station.callsign or '?'} {station.grid or ''} -> {location}")
    if station.license_class:
        mark = "" if station.license_certain else "  (guess — set [station] license_class)"
        print(f"licence      : {station.license_class}{mark}")
    caveat = ""
    if enricher.table.approximate:
        caveat = "  (approximate -- set [log] cty_dat for accuracy)"
    print(f"prefixes     : {enricher.table.source}{caveat}")
    if config.lookup.enabled:
        # Do not report this as ENABLED. The flag parses, nothing reads it, and
        # an operator who believes they switched on an endpoint that does not
        # exist has been told something false by their own tooling.
        endpoint = (
            "  + query_endpoint set, but NOT IMPLEMENTED (see docs/STATUS.md)"
            if config.lookup.query_endpoint
            else ""
        )
        chain = " -> ".join(config.lookup.providers)
        print(f"lookup       : {chain}{endpoint}")
        _report_uls(config)
    else:
        print("lookup       : none (prefix table only)")
    print(f"csp          : {build_csp(config.embed_hosts, config.csp_hosts())}")
    print()

    if offline:
        print("mode         : offline (skipping DNS; hosts checked against the allowlist only)")

    allowed_hosts, _ = config.allowlist()
    failures = 0
    for source in config.sources:
        if source.is_file_source:
            exists = Path(source.path).expanduser().is_file()  # type: ignore[arg-type]
            marker = "file" if exists else "MISSING"
            if not exists:
                failures += 1
            print(f"  {marker:<7} {source.id:<20} {source.kind:<10} {source.path}")
            continue

        marker = "local" if source.local else ("stream" if is_stream(source.kind) else "ok")
        if offline:
            # Structure only: the kind is registered, the URL parses, the host
            # is on the allowlist. What is skipped is name resolution.
            if source.host and source.host not in allowed_hosts:
                failures += 1
                print(f"  DENIED  {source.id:<20} {source.host} is not on the allowlist")
            else:
                print(f"  {marker:<7} {source.id:<20} {source.kind:<10} {source.host}")
            continue

        check = guard.check_stream if is_stream(source.kind) else guard.check
        try:
            check(source.url)
        except EgressDenied as exc:
            failures += 1
            print(f"  DENIED  {source.id:<20} {exc}")
        else:
            print(f"  {marker:<7} {source.id:<20} {source.kind:<10} {source.host}")

    if config.imagery:
        # Listed separately from sources, and deliberately not checked against
        # the egress guard: the guard governs what *this process* may contact,
        # and it never contacts these. Printing them under the same heading
        # would imply a check that is not happening.
        print("\n  tier 2 imagery — fetched by each viewer's browser, not by this collector:")
        for tile in config.imagery:
            print(f"  browser {tile.id:<20} {tile.group:<10} {tile.host}  every {tile.refresh}s")

    if web_problem is not None:
        print(WEB_DIR_HELP, file=sys.stderr)
        failures += 1

    if failures:
        print(f"\n{failures} problem(s) need attention.", file=sys.stderr)
    return 1 if failures else 0


def _report_uls(config: Config) -> None:
    """Say whether the offline index actually exists.

    "fcc_uls is configured" and "fcc_uls can answer" are different states, and
    the gap between them is a command the operator has not run yet. Worth
    catching here rather than as silent non-resolution later.
    """
    if "fcc_uls" not in config.lookup.providers:
        return
    from .lookup.uls import DEFAULT_DB_NAME, UlsIndex

    index = UlsIndex(config.lookup.uls_db or (config.data_dir / DEFAULT_DB_NAME))
    if not index.available:
        print(f"  fcc_uls    : NO INDEX at {index.path} — run 'hamhill fcc-import'")
        return
    meta = index.meta()
    index.close()
    count = meta.get("callsigns", "?")
    when = meta.get("imported_at", "unknown")
    print(f"  fcc_uls    : {count} callsigns, imported {when}  (offline, no network)")


EXAM_POOL_SOURCES = (
    "https://www.arrl.org/question-pools",
    "https://www.ncvec.org/page.php?id=356",
)


def _exam_import(config: Config, sources: list[Path] | None) -> int:
    """Turn a downloaded NCVEC pool into the JSON the panel serves.

    A deliberate command and not a source, for a different reason than the FCC
    importer: the pools are not fetched here at all. They change once every four
    years, they are published as a plain-text file behind a page rather than at
    a stable URL, and vendoring somebody else's copy of an exam syllabus into
    this repository would mean shipping study material nobody here verified.

    So the operator downloads the file and points this at it. One command every
    four years, against the authoritative copy, is the right trade.
    """
    from .exam import ELEMENT_BY_ID, check_pool, parse_pool, read_source

    if not sources:
        print(
            "usage: hamhill exam-import --file <pool.pdf> [--file <part2.pdf> ...]", file=sys.stderr
        )
        print(file=sys.stderr)
        print("Download the pool for the element you want from:", file=sys.stderr)
        for url in EXAM_POOL_SOURCES:
            print(f"  {url}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "Each element is a separate file, and each is valid for four years.",
            file=sys.stderr,
        )
        print(
            "Repeat --file, in order, if you have one pool split across several "
            "documents; they are joined before parsing.",
            file=sys.stderr,
        )
        return 2

    chunks = []
    for path in sources:
        try:
            chunks.append(read_source(path))
        except OSError as exc:
            print(f"cannot read {path}: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 1
    # Joined in the order given. A pool split across documents is split
    # mid-pool, so the order is the operator's to get right and there is no way
    # to check it beyond the reconciliation below noticing the hole.
    text = "\n".join(chunks)
    source = sources[0]

    try:
        pool = parse_pool(text, source=source.name)
    except ValueError as exc:
        print(f"{source}: {exc}", file=sys.stderr)
        print(
            "  Expected the plain-text pool as published, not a PDF or a Word file.",
            file=sys.stderr,
        )
        return 1

    for problem in check_pool(pool):
        print(f"warning: {problem}")

    status = pool.status()
    if status == "expired":
        print(f"warning: this pool expired after {pool.valid_until} — check for a newer release")
    elif status == "unknown":
        print("warning: no validity years in the header; the panel will say so")

    target = config.data_dir / f"exam-{pool.element_id}.json"
    config.data_dir.mkdir(parents=True, exist_ok=True)
    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id=f"exam-{pool.element_id}",
            kind="exam",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data=pool.to_dict(),
        ),
    )
    element = ELEMENT_BY_ID[pool.element_id]
    print(
        f"{pool.name}: {len(pool.questions)} questions in {len(pool.groups)} groups "
        f"(element {element['element']}, {pool.exam_length}-question exam, "
        f"pass at {pool.pass_mark})"
    )
    print(f"wrote {target}")
    return 0


def _part97_import(config: Config, sources: list[Path] | None) -> int:
    """Turn the published CFR into the JSON the exam panel quotes from.

    Run once an edition, against the annual CFR volume, the same shape of
    command as `exam-import` and for the same reason: the regulation is
    published as a PDF behind a page rather than at a stable URL, and the
    result is checked in so nobody has to run this to get it.

    Writes to the package data directory, not the snapshot directory. What this
    produces is source material for the repository rather than state for one
    installation.
    """
    import json

    from .part97 import Part97Error, parse, read_source

    if not sources:
        print("usage: hamhill part97-import --file <CFR-part-97.pdf>", file=sys.stderr)
        print(file=sys.stderr)
        print("The annual volume is published at:", file=sys.stderr)
        print("  https://www.govinfo.gov/app/collection/cfr", file=sys.stderr)
        print("Title 47, volume 5, which is where Part 97 lives.", file=sys.stderr)
        return 2

    chunks = []
    for path in sources:
        try:
            chunks.append(read_source(path))
        except OSError as exc:
            print(f"cannot read {path}: {exc}", file=sys.stderr)
            return 1
        except Part97Error as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 1

    try:
        part = parse("\n".join(chunks), source=str(sources[0].name))
    except Part97Error as exc:
        print(f"{sources[0]}: {exc}", file=sys.stderr)
        return 1

    target = Path(__file__).resolve().parent / "data" / "part97.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(part.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{len(part.sections)} sections")
    print(f"wrote {target}")
    return 0


def _fcc_import(config: Config, guard: EgressGuard, source: Path | None) -> int:
    """Build the offline FCC ULS index.

    A deliberate command rather than a scheduled source. It is a ~160 MB fetch
    and a few hundred MB of text to chew through, and doing that unattended on
    a metered hotspot -- which is exactly the connection a portable station is
    likely to have -- would be a poor surprise. The FCC rebuilds the file weekly;
    running this monthly is plenty.
    """
    from .lookup.uls import DEFAULT_DB_NAME, ULS_COMPLETE_URL, build_index

    db_path = config.lookup.uls_db or (config.data_dir / DEFAULT_DB_NAME)

    if source is None:
        print(f"downloading {ULS_COMPLETE_URL}")
        print("  (~160 MB. Use --file if you have already downloaded it.)")
        try:
            guard.check(ULS_COMPLETE_URL)
        except EgressDenied as exc:
            print(f"refused by egress policy: {exc}", file=sys.stderr)
            print(
                "  The FCC host is allowlisted only while this command runs, so this "
                "usually means a private-address or DNS problem.",
                file=sys.stderr,
            )
            return 1
        source = config.data_dir / "l_amat.zip"
        if (rc := _download(ULS_COMPLETE_URL, source)) != 0:
            return rc
    elif not source.is_file():
        print(f"no such file: {source}", file=sys.stderr)
        return 1

    print(f"reading {source}")
    try:
        stats = build_index(source, db_path)
    except (ValueError, OSError) as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return 1

    print(stats.report())
    print(f"\nindex written to {db_path}")

    if stats.indexed == 0:
        # A positional parser against a format we cannot re-verify should shout
        # rather than leave an empty database that silently resolves nothing.
        print(
            "\nNo callsigns were indexed. The record layout may have changed — "
            "please open an issue with the counts above.",
            file=sys.stderr,
        )
        return 1

    if "fcc_uls" not in config.lookup.providers:
        print("Add fcc_uls to [lookup] providers to use it.")
    return 0


def _download(url: str, target: Path) -> int:
    """Stream a large file to disk with visible progress."""
    import httpx

    from .collector import build_client

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")

    async def run() -> int:
        # A 160 MB body over a slow link needs a read timeout measured in
        # minutes, not the 20 seconds a JSON source gets.
        timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=10.0)
        try:
            async with build_client(EgressGuard.build({_host_of(url)}, set())) as client:
                async with client.stream("GET", url, timeout=timeout) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length") or 0)
                    done = 0
                    with tmp.open("wb") as handle:
                        async for chunk in response.aiter_bytes(1 << 20):
                            handle.write(chunk)
                            done += len(chunk)
                            if total:
                                pct = 100 * done / total
                                print(f"\r  {done >> 20} / {total >> 20} MiB ({pct:.0f}%)", end="")
                            else:
                                print(f"\r  {done >> 20} MiB", end="")
                    print()
        except httpx.HTTPError as exc:
            print(f"\ndownload failed: {exc}", file=sys.stderr)
            tmp.unlink(missing_ok=True)
            return 1
        tmp.replace(target)
        return 0

    return asyncio.run(run())


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower()


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
        "--offline",
        action="store_true",
        help="check: validate config without DNS, for a machine with no WAN (or CI)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        metavar="PATH",
        action="append",
        help=(
            "fcc-import: use an already-downloaded l_amat.zip instead of fetching it. "
            "exam-import: the pool file to read; repeat for a pool split across "
            "several documents. part97-import: the CFR volume containing Part 97."
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=("serve", "check", "fcc-import", "exam-import", "part97-import"),
        help="default: serve",
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
        return _check(config, guard, enricher, offline=args.offline)
    if args.command == "fcc-import":
        return _fcc_import(config, guard, args.file[0] if args.file else None)
    if args.command == "exam-import":
        return _exam_import(config, args.file)

    if args.command == "part97-import":
        return _part97_import(config, args.file)
    return _serve(config, guard, enricher)

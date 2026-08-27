# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Configuration loading.

Config is a TOML file the operator edits with a text editor. There is no write
endpoint and no settings API in v0.1 -- presentation state (layout, filters,
which panels are shown) lives in the browser's localStorage, and everything that
touches the network lives here, on disk, under the operator's control.

That split is deliberate. It means there is no request that can reconfigure the
collector, so there is no CSRF surface and nothing to authenticate.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_INTERVAL = 300
MIN_INTERVAL = 30  # Be a good neighbour to free upstream APIs.


class ConfigError(Exception):
    """Raised for a config the operator needs to fix. Message says how."""


@dataclass(frozen=True)
class SourceConfig:
    """One upstream the collector reads.

    Exactly one of ``url`` or ``path`` is set. A ``path`` source reads a local
    file and never touches the network, which is how the ADIF log works.
    """

    id: str
    kind: str
    url: str = ""
    path: str | None = None
    interval: int = DEFAULT_INTERVAL
    local: bool = False
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower() if self.url else ""

    @property
    def is_file_source(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class ServerConfig:
    """How the dashboard is served.

    The default is loopback. Binding to a LAN address is a deliberate act that
    requires an explicit host in config or ``--listen`` on the command line, and
    it prints the network-stance warning every time.
    """

    host: str = "127.0.0.1"
    port: int = 8073

    @property
    def is_loopback_only(self) -> bool:
        return self.host in {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True)
class LookupConfig:
    """Callsign lookup. Off by default -- see docs/CALLSIGN-LOOKUP.md.

    Every provider except ``none`` costs something: an account, money, or a
    request per callsign to a third party. Which cost is acceptable is the
    operator's call, so it is a choice rather than a default.
    """

    provider: str = "none"
    username: str | None = None
    password: str | None = None
    max_per_cycle: int = 20
    cycle_seconds: int = 60
    cache_hours: int = 720
    max_entries: int = 5000
    query_endpoint: bool = False

    @property
    def enabled(self) -> bool:
        return self.provider not in ("", "none")


@dataclass(frozen=True)
class LoggingConfig:
    """The one place the server accepts input, and it is off by default."""

    enabled: bool = False


@dataclass(frozen=True)
class Config:
    server: ServerConfig
    sources: tuple[SourceConfig, ...]
    data_dir: Path
    web_dir: Path
    station: dict[str, Any] = field(default_factory=dict)
    embed_hosts: tuple[str, ...] = ()
    cty_dat: Path | None = None
    lookup: LookupConfig = field(default_factory=LookupConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    logbooks: tuple[Any, ...] = ()

    def primary_logbook(self) -> Any | None:
        """The book that drives needed-slot colouring."""
        for book in self.logbooks:
            if book.primary:
                return book
        return self.logbooks[0] if self.logbooks else None

    def logbook(self, book_id: str) -> Any | None:
        for book in self.logbooks:
            if book.id == book_id:
                return book
        return None

    def allowlist(self) -> tuple[set[str], set[str]]:
        """(all hosts the collector may contact, hosts explicitly marked local)."""
        from .lookup import provider_hosts

        allowed = {s.host for s in self.sources if s.host}
        allowed |= {h.lower() for h in self.embed_hosts}
        # A lookup provider declares its own hosts; nothing else grants it reach.
        allowed |= set(provider_hosts(self.lookup.provider))
        local = {s.host for s in self.sources if s.local and s.host}
        return allowed, local


def _require(table: dict[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise ConfigError(f"{where}: missing required key {key!r}")
    return table[key]


def parse_config(raw: dict[str, Any], *, base_dir: Path) -> Config:
    """Turn parsed TOML into a validated Config, or raise ConfigError."""
    server_tbl = raw.get("server", {})
    if not isinstance(server_tbl, dict):
        raise ConfigError("[server] must be a table")
    server = ServerConfig(
        host=str(server_tbl.get("host", "127.0.0.1")),
        port=int(server_tbl.get("port", 8073)),
    )
    if not 1 <= server.port <= 65535:
        raise ConfigError(f"[server] port {server.port} is out of range")

    raw_sources = raw.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ConfigError("[[sources]] must be an array of tables")

    seen: set[str] = set()
    sources: list[SourceConfig] = []
    for idx, entry in enumerate(raw_sources):
        where = f"[[sources]] #{idx + 1}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: must be a table")
        sid = str(_require(entry, "id", where))
        if not sid.replace("_", "").replace("-", "").isalnum():
            raise ConfigError(
                f"{where}: id {sid!r} must be alphanumeric with - or _ "
                f"(it becomes a filename under the data directory)"
            )
        if sid in seen:
            raise ConfigError(f"{where}: duplicate id {sid!r}; ids map 1:1 to snapshot files")
        seen.add(sid)

        interval = int(entry.get("interval", DEFAULT_INTERVAL))
        if interval < MIN_INTERVAL:
            raise ConfigError(
                f"{where}: interval {interval}s is below the {MIN_INTERVAL}s floor. "
                f"These are free upstream services; do not hammer them."
            )

        options = entry.get("options", {})
        if not isinstance(options, dict):
            raise ConfigError(f"{where}: options must be a table")

        url = entry.get("url")
        source_path = entry.get("path")
        if bool(url) == bool(source_path):
            raise ConfigError(
                f"{where}: set exactly one of url or path "
                f"(url for anything fetched, path for a local file such as an ADIF log)"
            )

        sources.append(
            SourceConfig(
                id=sid,
                kind=str(_require(entry, "kind", where)),
                url=str(url) if url else "",
                path=str(source_path) if source_path else None,
                interval=interval,
                local=bool(entry.get("local", False)),
                options=options,
            )
        )

    paths = raw.get("paths", {})
    data_dir = Path(paths.get("data_dir", base_dir / "data")).expanduser()
    web_dir = Path(paths.get("web_dir", base_dir / "web")).expanduser()

    embed = raw.get("embeds", {}).get("allow_hosts", [])
    if not isinstance(embed, list):
        raise ConfigError("[embeds] allow_hosts must be an array of hostnames")

    # AD1C's country file, if the operator has one. Without it we fall back to
    # a compact built-in prefix table that is documented as approximate.
    cty_raw = raw.get("log", {}).get("cty_dat")
    cty_dat = Path(str(cty_raw)).expanduser() if cty_raw else None

    from .logbook import Logbook

    raw_books = raw.get("logbooks", [])
    if not isinstance(raw_books, list):
        raise ConfigError("[[logbooks]] must be an array of tables")

    books: list[Logbook] = []
    seen_books: set[str] = set()
    for idx, entry in enumerate(raw_books):
        where = f"[[logbooks]] #{idx + 1}"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: must be a table")
        book_id = str(_require(entry, "id", where))
        if not book_id.replace("_", "").replace("-", "").isalnum():
            raise ConfigError(f"{where}: id {book_id!r} must be alphanumeric with - or _")
        if book_id in seen_books:
            raise ConfigError(f"{where}: duplicate id {book_id!r}")
        seen_books.add(book_id)
        books.append(
            Logbook(
                id=book_id,
                name=str(entry.get("name") or book_id),
                path=Path(str(_require(entry, "path", where))).expanduser(),
                primary=bool(entry.get("primary", False)),
                station_callsign=(
                    str(entry["station_callsign"]).upper()
                    if entry.get("station_callsign")
                    else None
                ),
            )
        )

    if sum(1 for b in books if b.primary) > 1:
        raise ConfigError("[[logbooks]]: only one logbook may be marked primary")

    logging_tbl = raw.get("logging", {})
    if not isinstance(logging_tbl, dict):
        raise ConfigError("[logging] must be a table")
    log_cfg = LoggingConfig(enabled=bool(logging_tbl.get("enabled", False)))
    if log_cfg.enabled and not books:
        raise ConfigError("[logging] enabled but no [[logbooks]] are configured")

    lookup_tbl = raw.get("lookup", {})
    if not isinstance(lookup_tbl, dict):
        raise ConfigError("[lookup] must be a table")
    lookup = LookupConfig(
        provider=str(lookup_tbl.get("provider", "none")).strip().lower(),
        username=str(lookup_tbl["username"]) if lookup_tbl.get("username") else None,
        password=str(lookup_tbl["password"]) if lookup_tbl.get("password") else None,
        max_per_cycle=int(lookup_tbl.get("max_per_cycle", 20)),
        cycle_seconds=int(lookup_tbl.get("cycle_seconds", 60)),
        cache_hours=int(lookup_tbl.get("cache_hours", 720)),
        max_entries=int(lookup_tbl.get("max_entries", 5000)),
        query_endpoint=bool(lookup_tbl.get("query_endpoint", False)),
    )
    if lookup.max_per_cycle < 1:
        raise ConfigError("[lookup] max_per_cycle must be at least 1")

    return Config(
        server=server,
        sources=tuple(sources),
        data_dir=data_dir,
        web_dir=web_dir,
        station=raw.get("station", {}),
        embed_hosts=tuple(str(h) for h in embed),
        cty_dat=cty_dat,
        lookup=lookup,
        logging=log_cfg,
        logbooks=tuple(books),
    )


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(
            f"No config at {path}. Copy config.example.toml to {path.name} and edit it."
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_config(raw, base_dir=path.parent)

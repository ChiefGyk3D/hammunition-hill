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
    """One upstream the collector polls."""

    id: str
    kind: str
    url: str
    interval: int = DEFAULT_INTERVAL
    local: bool = False
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def host(self) -> str:
        return (urlsplit(self.url).hostname or "").lower()


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
class Config:
    server: ServerConfig
    sources: tuple[SourceConfig, ...]
    data_dir: Path
    web_dir: Path
    station: dict[str, Any] = field(default_factory=dict)
    embed_hosts: tuple[str, ...] = ()

    def allowlist(self) -> tuple[set[str], set[str]]:
        """(all hosts the collector may contact, hosts explicitly marked local)."""
        allowed = {s.host for s in self.sources if s.host}
        allowed |= {h.lower() for h in self.embed_hosts}
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

        sources.append(
            SourceConfig(
                id=sid,
                kind=str(_require(entry, "kind", where)),
                url=str(_require(entry, "url", where)),
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

    return Config(
        server=server,
        sources=tuple(sources),
        data_dir=data_dir,
        web_dir=web_dir,
        station=raw.get("station", {}),
        embed_hosts=tuple(str(h) for h in embed),
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

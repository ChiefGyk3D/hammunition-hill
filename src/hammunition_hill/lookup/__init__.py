# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Callsign lookup providers.

Static registry, like every other registry here: a config file must not be able
to make the collector import arbitrary code.

Providers are configured as an ordered **chain** rather than a single choice,
because no one source is right for every callsign. The offline FCC index is
authoritative for US calls and answers with no network at all; QRZ knows the
rest of the world but costs a subscription and a request per callsign. Neither
is a strictly better default, so the operator orders them and the resolver walks
the list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import CredentialsRequired, LookupError, LookupProvider, LookupResult
from .callook import CallookProvider
from .fcc import FccUlsProvider
from .session_xml import HamQthProvider, QrzProvider
from .uls import DEFAULT_DB_NAME

# name -> class. "none" is absent on purpose: it is not a provider, it is the
# absence of one, and the config layer strips it before we ever see it.
PROVIDERS: dict[str, Any] = {
    CallookProvider.name: CallookProvider,
    FccUlsProvider.name: FccUlsProvider,
    HamQthProvider.name: HamQthProvider,
    QrzProvider.name: QrzProvider,
}


def provider_hosts(name: str) -> tuple[str, ...]:
    """Hosts a provider may contact, for the egress allowlist.

    ``fcc_uls`` returns nothing: its import is a separate command with its own
    egress check, so being configured as a provider grants the collector no
    reach at all.
    """
    cls = PROVIDERS.get(name)
    return tuple(cls.hosts) if cls else ()


def build_provider(
    name: str,
    username: str | None,
    password: str | None,
    *,
    data_dir: Path | None = None,
    uls_db: Path | None = None,
) -> LookupProvider | None:
    """Instantiate one provider, or None for 'none'."""
    if not name or name == "none":
        return None
    cls = PROVIDERS.get(name)
    if cls is None:
        available = ", ".join(["none", *sorted(PROVIDERS)])
        raise ValueError(f"unknown lookup provider {name!r}; available: {available}")

    if cls is FccUlsProvider:
        path = uls_db or ((data_dir or Path(".")) / DEFAULT_DB_NAME)
        return cls(path)
    return cls(username, password) if cls.needs_credentials else cls()


def build_chain(
    names: tuple[str, ...] | list[str],
    username: str | None,
    password: str | None,
    *,
    data_dir: Path | None = None,
    uls_db: Path | None = None,
) -> list[LookupProvider]:
    """Build every provider in the chain, in order.

    A provider that cannot be constructed -- missing credentials, an unknown
    name -- raises. Failing loudly at startup beats a chain that silently has
    one fewer link than the operator configured, because the symptom of that is
    "some callsigns do not resolve" weeks later.
    """
    return [
        provider
        for name in names
        if (provider := build_provider(name, username, password, data_dir=data_dir, uls_db=uls_db))
        is not None
    ]


__all__ = [
    "PROVIDERS",
    "CredentialsRequired",
    "FccUlsProvider",
    "LookupError",
    "LookupProvider",
    "LookupResult",
    "build_chain",
    "build_provider",
    "provider_hosts",
]

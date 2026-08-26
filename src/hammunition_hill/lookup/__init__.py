# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Callsign lookup providers.

Static registry, like every other registry here: a config file must not be able
to make the collector import arbitrary code.
"""

from __future__ import annotations

from typing import Any

from .base import CredentialsRequired, LookupError, LookupProvider, LookupResult
from .callook import CallookProvider
from .session_xml import HamQthProvider, QrzProvider

# name -> (class, needs_credentials). "none" is absent on purpose: it is not a
# provider, it is the absence of one.
PROVIDERS: dict[str, Any] = {
    CallookProvider.name: CallookProvider,
    HamQthProvider.name: HamQthProvider,
    QrzProvider.name: QrzProvider,
}

# Declared but not implemented yet -- documented so the error message can say so
# rather than "unknown provider".
PLANNED: dict[str, str] = {
    "fcc_uls": (
        "the local FCC ULS import is designed but not built yet; "
        "see docs/CALLSIGN-LOOKUP.md. Use 'callook' for the same US data today."
    ),
}


def provider_hosts(name: str) -> tuple[str, ...]:
    """Hosts a provider may contact, for the egress allowlist."""
    cls = PROVIDERS.get(name)
    return tuple(cls.hosts) if cls else ()


def build_provider(name: str, username: str | None, password: str | None) -> LookupProvider | None:
    """Instantiate a provider, or None for 'none'."""
    if not name or name == "none":
        return None
    if name in PLANNED:
        raise ValueError(f"lookup provider {name!r}: {PLANNED[name]}")
    cls = PROVIDERS.get(name)
    if cls is None:
        available = ", ".join(["none", *sorted(PROVIDERS)])
        raise ValueError(f"unknown lookup provider {name!r}; available: {available}")
    return cls(username, password) if cls.needs_credentials else cls()


__all__ = [
    "PLANNED",
    "PROVIDERS",
    "CredentialsRequired",
    "LookupError",
    "LookupProvider",
    "LookupResult",
    "build_provider",
    "provider_hosts",
]

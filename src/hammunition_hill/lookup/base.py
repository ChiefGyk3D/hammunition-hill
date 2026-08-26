# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""What a callsign lookup provider looks like.

Providers differ in what they cost you -- an account, money, a request to a
third party, a large download -- but they all answer the same question and
return the same shape, so the panel does not care which one is configured.

See docs/CALLSIGN-LOOKUP.md for the trade-offs and how to choose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx


class LookupError(Exception):
    """A lookup failed. Never fatal -- the entity is still known from the prefix."""


class CredentialsRequired(LookupError):
    """The provider needs a username and password that were not configured."""


@dataclass(frozen=True)
class LookupResult:
    """One resolved callsign, normalized across providers.

    Every field except ``callsign`` and ``source`` is optional, because coverage
    varies wildly: callook has no name for a club station, HamQTH's grid is
    user-supplied, QRZ has almost everything.
    """

    callsign: str
    source: str
    name: str | None = None
    grid: str | None = None
    country: str | None = None
    state: str | None = None
    license_class: str | None = None
    expires: str | None = None
    status: str | None = None
    fetched_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "callsign": self.callsign,
            "source": self.source,
            "name": self.name,
            "grid": self.grid,
            "country": self.country,
            "state": self.state,
            "license_class": self.license_class,
            "expires": self.expires,
            "status": self.status,
            "fetched_at": self.fetched_at,
        }


class LookupProvider(Protocol):
    """Resolves one callsign at a time."""

    name: str
    hosts: tuple[str, ...]
    """Hosts this provider contacts. Added to the egress allowlist, so a
    provider cannot reach anywhere it has not declared."""

    needs_credentials: bool
    worldwide: bool

    async def resolve(self, client: httpx.AsyncClient, callsign: str) -> LookupResult | None:
        """Return what is known, or None if the callsign is simply not on file."""
        ...

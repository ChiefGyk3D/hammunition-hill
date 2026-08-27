# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The offline link in a lookup chain: the imported FCC ULS index."""

from __future__ import annotations

from pathlib import Path

import httpx

from .base import LookupError, LookupResult
from .uls import UlsIndex


class FccUlsProvider:
    """Resolves US callsigns from a local SQLite index. No network, ever.

    ``resolve`` takes a client like every other provider and ignores it. Keeping
    the signature identical is what lets the resolver walk a chain without
    knowing or caring which links touch the network -- the difference is
    declared in ``offline``, not discovered by inspecting the call.
    """

    name = "fcc_uls"
    hosts: tuple[str, ...] = ()  # Nothing at lookup time. The import is separate.
    needs_credentials = False
    worldwide = False
    offline = True

    def __init__(self, db_path: Path) -> None:
        self.index = UlsIndex(db_path)

    @property
    def available(self) -> bool:
        return self.index.available

    async def resolve(self, client: httpx.AsyncClient, callsign: str) -> LookupResult | None:
        if not self.index.available:
            # A missing index is a configuration problem, not "not on file".
            # Raising means the chain falls through to a network provider rather
            # than caching a miss that would be wrong for a month.
            raise LookupError(
                f"no ULS index at {self.index.path}; run 'hamhill fcc-import' to build it"
            )

        row = self.index.lookup(callsign)
        if row is None:
            return None

        # City and state are what a dashboard can use; the street address is in
        # the source file and is deliberately not carried into the index or the
        # snapshot. A wall display in a shack does not need someone's house
        # number, and anything published here is readable by everyone on the LAN.
        location = ", ".join(part for part in (row.get("city"), row.get("state")) if part)

        return LookupResult(
            callsign=callsign.upper(),
            source=self.name,
            name=row.get("name") or None,
            country="United States",
            state=row.get("state") or None,
            license_class=row.get("operator_class") or None,
            expires=row.get("expires") or None,
            status=location or None,
        )

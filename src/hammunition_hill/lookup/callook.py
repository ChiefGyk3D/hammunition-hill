# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""callook.info -- free, no account, US only.

The simplest real provider: a GET returns JSON with current FCC data. No
registration, no key, no session. Its data comes from the same ULS database the
``fcc_uls`` provider downloads, so the two agree -- callook trades a request per
lookup for not having to hold 160 MB on your disk.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..sources.base import get_bounded
from .base import LookupError, LookupResult

BASE_URL = "https://callook.info"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class CallookProvider:
    name = "callook"
    hosts = ("callook.info",)
    needs_credentials = False
    worldwide = False
    offline = False

    async def resolve(self, client: httpx.AsyncClient, callsign: str) -> LookupResult | None:
        url = f"{BASE_URL}/{callsign.upper()}/json"
        try:
            response = await get_bounded(client, url)
            payload = response.json()
        except ValueError as exc:
            raise LookupError(f"callook: response was not JSON ({exc})") from exc

        status = str(payload.get("status", "")).upper()
        if status in ("INVALID", "UPDATING", ""):
            # Not an error -- the callsign is simply not a current US licence.
            return None

        current = payload.get("current") or {}
        location = payload.get("location") or {}
        other = payload.get("otherInfo") or {}
        address = payload.get("address") or {}

        return LookupResult(
            callsign=_text(payload.get("callsign")) or callsign.upper(),
            source=self.name,
            name=_text(payload.get("name")),
            grid=_text(location.get("gridsquare")),
            country="United States",
            # callook puts "CITY, ST ZIP" in line2; the state is the useful part.
            state=_text(address.get("line2")),
            license_class=_text(current.get("operClass")),
            expires=_text(other.get("expiryDate")),
            status=status,
        )

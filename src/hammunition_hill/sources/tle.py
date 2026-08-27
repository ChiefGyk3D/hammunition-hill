# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Two-line elements for the amateur satellites.

Celestrak publishes grouped element sets as plain text with no key and no auth.
This fetches one group and stores the lines verbatim -- the pass prediction is a
derived source that reads them off disk, so this file's only job is to get a
listing safely and refuse a corrupted one.

Elements age slowly. A set a week old still predicts a pass to within seconds,
which is why the panel keeps working through a WAN outage and why fetching this
more than daily is wasted traffic on somebody else's volunteer bandwidth.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import SourceConfig
from ..satellites import parse_tles
from .base import FetchError, get_bounded

# The amateur group is about a hundred satellites; the full catalog is thirty
# thousand and is not what anyone should point this at. The cap is a guard
# against a URL that quietly became the whole catalog, not a limit anyone
# should hit.
MAX_SATELLITES = 500


class TleSource:
    kind = "tle"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        text = response.text

        tles = parse_tles(text)
        if not tles:
            # An empty listing is always a problem: either the URL moved, or
            # every checksum failed, and both should keep the last good
            # snapshot rather than replacing it with nothing.
            raise FetchError(f"{cfg.url}: no usable element sets in {len(text)} bytes")

        if len(tles) > MAX_SATELLITES:
            raise FetchError(
                f"{cfg.url}: {len(tles)} satellites, more than the {MAX_SATELLITES} cap "
                "-- this looks like the full catalog rather than a group"
            )

        return {
            "satellites": [
                {"name": tle.name, "line1": tle.line1, "line2": tle.line2} for tle in tles
            ],
            "count": len(tles),
        }

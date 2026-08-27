# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Source registry.

Adding a source means adding it here. There is no plugin autoloader and no
dynamic import by name from config -- a config file should not be able to make
the collector execute arbitrary code paths.
"""

from __future__ import annotations

from .aurora import AuroraSource
from .base import FetchError, Source
from .hamqsl import HamQslSource
from .ics import IcsSource
from .local import LOCAL_KINDS, get_local, is_local
from .pota import PotaSource
from .rss import RssSource
from .sota import SotaSource
from .swpc import SwpcSource
from .swpc_text import NoaaScalesSource, SwpcAlertsSource
from .tle import TleSource
from .weather import NwsAlertsSource

REGISTRY: dict[str, Source] = {
    src.kind: src()  # type: ignore[operator]
    for src in (
        SwpcSource,
        HamQslSource,
        RssSource,
        PotaSource,
        SotaSource,
        IcsSource,
        AuroraSource,
        NoaaScalesSource,
        SwpcAlertsSource,
        NwsAlertsSource,
        TleSource,
    )
}


def get_source(kind: str) -> Source:
    try:
        return REGISTRY[kind]
    except KeyError:
        raise FetchError(
            f"unknown source kind {kind!r}; available: {', '.join(sorted(REGISTRY))}"
        ) from None


__all__ = [
    "LOCAL_KINDS",
    "REGISTRY",
    "FetchError",
    "Source",
    "get_local",
    "get_source",
    "is_local",
]

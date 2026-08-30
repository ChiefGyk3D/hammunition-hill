# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Sources that read a local file rather than making a request.

The ADIF log is the obvious one, and the reason the project exists in this
shape: the log is on this disk, so we read it. No upload, no third party, no
account.

Local sources never touch the network, so they bypass the egress guard by
construction rather than by exception -- there is no URL involved at all.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from ..adif import US_STATES, load_index
from ..config import SourceConfig
from ..enrich import Enricher

log = logging.getLogger(__name__)


class LocalSource(Protocol):
    kind: str

    def load(self, cfg: SourceConfig, enricher: Enricher) -> Any: ...


class AdifLogSource:
    """Re-reads the operator's log and republishes the worked/needed index.

    Re-reading the whole file each cycle rather than tailing it is deliberate.
    Logging programs rewrite, reorder, and back-fill; an incremental reader
    would drift out of sync in ways that are invisible until a spot is coloured
    wrong. A 50,000 QSO log parses in well under a second, and this runs every
    few minutes.
    """

    kind = "adif"

    def load(self, cfg: SourceConfig, enricher: Enricher) -> Any:
        path = Path(cfg.path).expanduser()  # type: ignore[arg-type]
        if not path.is_file():
            log.warning("source %s: no log at %s", cfg.id, path)
            enricher.set_log_index(None)
            return {"path": str(path), "found": False, "qso_count": 0}

        index = load_index(path, enricher.table)
        enricher.set_log_index(index)

        return {
            "path": str(path),
            "found": True,
            "qso_count": index.qso_count,
            "entities": len(index.entities),
            "confirmed_entities": len(index.confirmed_entities),
            "band_slots": len(index.entity_band),
            "mode_slots": len(index.entity_mode),
            "unresolved": index.unresolved,
            "states": len(index.states),
            "confirmed_states": len(index.confirmed_states),
            "states_missing": sorted(US_STATES - index.states),
            "entity_total": enricher.table.entity_count,
            "prefix_source": "cty.dat" if not enricher.table.approximate else "built-in",
            "worked": index.worked_summary(),
        }


LOCAL_KINDS: dict[str, LocalSource] = {AdifLogSource.kind: AdifLogSource()}


def is_local(kind: str) -> bool:
    return kind in LOCAL_KINDS


def get_local(kind: str) -> LocalSource:
    return LOCAL_KINDS[kind]

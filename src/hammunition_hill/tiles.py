# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Opaque imagery: the collector fetches the tile, the browser never does.

Tier 2's one exception to the architecture, folded back into it. A tile marked
``mode = "opaque"`` is fetched by the collector on its refresh interval and
served same-origin as a plain file -- exactly what every other source does,
with a binary payload instead of JSON. The upstream sees one machine on a
timer instead of every viewer on every dashboard load, and the CSP stops
naming the host at all.

The reason this took discipline rather than an afternoon, per IMAGERY.md: an
upstream that serves SVG instead of PNG would be handing us a document that
can run script, now on our own origin where the CSP trusts 'self'. So the
payload is identified by its own bytes -- magic numbers, not the upstream's
Content-Type header, which is exactly the thing an evil or broken upstream
controls -- and only raster formats are written to disk, under an extension
chosen by us from what the bytes are.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TILE_DIR = "tiles"

# A tile bigger than this is not a dashboard tile. Radar mosaics run tens to a
# few hundred kB; the cap exists so a misconfigured URL pointing at an archive
# cannot fill the data directory on a Pi.
MAX_TILE_BYTES = 10 * 1024 * 1024

# Format -> (extension, magic prefix test). The test is over the payload's own
# bytes: headers lie, magic numbers do not.
_PNG = b"\x89PNG\r\n\x1a\n"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"
_JPEG = b"\xff\xd8\xff"


class TileError(ValueError):
    """A payload that must not be written, with the reason."""


def sniff(payload: bytes) -> str:
    """The file extension for a raster payload, from its magic bytes.

    Raises for anything that is not PNG, JPEG, GIF or WebP -- including SVG,
    which is the format this gate exists for. ``<svg`` anywhere near the front
    of a rejected payload is called out by name, because "not a raster" is a
    puzzle and "the upstream sent SVG" is a finding.
    """
    if payload.startswith(_PNG):
        return "png"
    if payload.startswith((_GIF87, _GIF89)):
        return "gif"
    if payload.startswith(_JPEG):
        return "jpg"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp"
    head = payload[:256].lstrip().lower()
    if head.startswith((b"<svg", b"<?xml", b"<!doctype")):
        raise TileError(
            "upstream sent a document, not a raster image -- SVG can carry script "
            "and will not be served from this origin"
        )
    raise TileError("payload is not PNG, JPEG, GIF or WebP")


def write_tile(data_dir: Path, tile_id: str, payload: bytes, extension: str) -> dict[str, Any]:
    """Atomically write the image and its metadata; return the metadata.

    The metadata sidecar is what the panel reads: the image's current name
    (the extension follows the bytes, so it can change if an upstream switches
    format), its size, and when it was fetched. Stale copies under other
    extensions are removed so a format change does not leave both behind.
    """
    from datetime import UTC, datetime

    directory = data_dir / TILE_DIR
    directory.mkdir(parents=True, exist_ok=True)

    name = f"{tile_id}.{extension}"
    target = directory / name
    tmp = directory / f".{name}.tmp"
    tmp.write_bytes(payload)
    tmp.replace(target)

    for other in ("png", "gif", "jpg", "webp"):
        if other != extension:
            (directory / f"{tile_id}.{other}").unlink(missing_ok=True)

    meta = {
        "src": f"data/{TILE_DIR}/{name}",
        "content_type": {
            "png": "image/png",
            "gif": "image/gif",
            "jpg": "image/jpeg",
            "webp": "image/webp",
        }[extension],
        "bytes": len(payload),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    meta_tmp = directory / f".{tile_id}.json.tmp"
    import json

    meta_tmp.write_text(json.dumps(meta), encoding="utf-8")
    meta_tmp.replace(directory / f"{tile_id}.json")
    return meta


def write_tile_failure(data_dir: Path, tile_id: str, reason: str) -> None:
    """Record why there is no fresh image, without destroying the last good one.

    The image file is deliberately left in place: a stale radar frame with an
    honest timestamp beats a broken-image icon, which is the same trade every
    JSON snapshot makes.
    """
    import json
    from datetime import UTC, datetime

    directory = data_dir / TILE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    try:
        existing = json.loads((directory / f"{tile_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    existing["error"] = reason
    existing["failed_at"] = datetime.now(UTC).isoformat()
    tmp = directory / f".{tile_id}.json.tmp"
    tmp.write_text(json.dumps(existing), encoding="utf-8")
    tmp.replace(directory / f"{tile_id}.json")

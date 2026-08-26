# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The contract every source implements."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from ..config import SourceConfig

# Upstreams are free services run by volunteers and government agencies. Identify
# ourselves so their operators can tell what is hitting them and reach us.
USER_AGENT = "hammunition-hill/0.1 (+https://github.com/ChiefGyk3D/hammunition-hill)"

# A response larger than this is a bug, a redirect to something unexpected, or a
# hostile upstream. None of those should be allowed to fill a Pi's disk.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class FetchError(Exception):
    """A source could not produce data this cycle. The last snapshot stands."""


class Source(Protocol):
    """A source turns one HTTP response into snapshot data.

    Sources never decide *when* they run and never construct their own client --
    the scheduler owns the timer and the guard owns the connection policy.
    """

    kind: str

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any: ...


async def get_bounded(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET with a hard size cap, streaming so an oversized body is cut off early."""
    async with client.stream("GET", url) as response:
        response.raise_for_status()

        declared = response.headers.get("content-length")
        if declared and int(declared) > MAX_RESPONSE_BYTES:
            raise FetchError(f"{url}: content-length {declared} exceeds cap")

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise FetchError(f"{url}: response exceeded {MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)

        response._content = b"".join(chunks)  # noqa: SLF001 - stream() defers this
        return response

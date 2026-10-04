# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Helpers the fuzz targets share. Not a target: the name does not match `fuzz_*.py`.

Everything here is offline. A source's `fetch` is driven through an
`httpx.MockTransport` that answers with the fuzzer's bytes, so the real
`get_bounded`, the real JSON/XML decoding and the real reducer run, and no
socket is ever opened.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

import httpx

_LOOP = asyncio.new_event_loop()


def run(coro: Awaitable[Any]) -> Any:
    """Run a coroutine to completion on one long-lived loop (a loop per input is slow)."""
    return _LOOP.run_until_complete(coro)


def fetch_with_body(source: Any, cfg: Any, body: bytes) -> Any:
    """Call `source.fetch` with a client whose only answer is `body`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async def go() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await source.fetch(client, cfg)

    return run(go())


def feed_stream(reader_user: Any, data: bytes) -> None:
    """Hand `data` to a coroutine that takes a `StreamReader`, then close the stream."""

    async def go() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        await reader_user(reader)

    run(go())


def json_text(fdp: Any, keys: list[str], strings: list[str] | None = None, depth: int = 0) -> str:
    """A JSON document built from the fuzzer's bytes, shaped like the feeds it feeds.

    Random bytes almost never form valid JSON, and coverage of the parser behind
    the decoder is the point, so this assembles values the way the real feeds do:
    objects keyed from `keys`, lists, numbers (large, tiny, NaN-adjacent),
    numeric strings, nulls and booleans. `strings` are values worth hitting
    exactly, such as a feed's `energy` labels.
    """
    import json

    return json.dumps(_json_value(fdp, keys, strings or [], depth), allow_nan=True)


def _json_value(fdp: Any, keys: list[str], strings: list[str], depth: int) -> Any:
    kind = fdp.ConsumeIntInRange(0, 9 if depth < 4 else 6)
    if kind == 0:
        return None
    if kind == 1:
        return fdp.ConsumeBool()
    if kind == 2:
        return fdp.ConsumeIntInRange(-(10**6), 10**6)
    if kind == 3:
        return fdp.ConsumeFloat()
    if kind == 4:
        return str(fdp.ConsumeIntInRange(-1000, 100000)) + (".5" if fdp.ConsumeBool() else "")
    if kind == 5 and strings:
        return strings[fdp.ConsumeIntInRange(0, len(strings) - 1)]
    if kind in (5, 6):
        return fdp.ConsumeUnicodeNoSurrogates(24)
    if kind in (7, 8):
        return [
            _json_value(fdp, keys, strings, depth + 1) for _ in range(fdp.ConsumeIntInRange(0, 4))
        ]
    return {
        keys[fdp.ConsumeIntInRange(0, len(keys) - 1)]: _json_value(fdp, keys, strings, depth + 1)
        for _ in range(fdp.ConsumeIntInRange(0, 6))
    }


def _xml_safe(text: str) -> str:
    return text.replace('"', "").replace("<", "").replace("&", "")


def xml_text(fdp: Any, tags: list[str], depth: int = 0) -> str:
    """An XML document from `tags`, with namespaces, attributes and text from the fuzzer."""
    tag = tags[fdp.ConsumeIntInRange(0, len(tags) - 1)]
    attrs = ""
    if fdp.ConsumeBool():
        attrs += f' name="{_xml_safe(fdp.ConsumeUnicodeNoSurrogates(8))}"'
    if fdp.ConsumeBool():
        attrs += f' time="{_xml_safe(fdp.ConsumeUnicodeNoSurrogates(8))}"'
    if depth == 0 and fdp.ConsumeBool():
        attrs += ' xmlns="https://example.invalid/ns"'
    text = _xml_safe(fdp.ConsumeUnicodeNoSurrogates(12))
    kids = ""
    if depth < 5:
        kids = "".join(xml_text(fdp, tags, depth + 1) for _ in range(fdp.ConsumeIntInRange(0, 4)))
    return f"<{tag}{attrs}>{text}{kids}</{tag}>"


def spot_line(fdp: Any, prefix: str = "DX de ") -> str:
    """A cluster or RBN spot line with every field drawn from the fuzzer, in the real order."""
    spotter = fdp.ConsumeUnicodeNoSurrogates(8)
    khz = fdp.ConsumeIntInRange(0, 40_000_000)
    frac = f".{fdp.ConsumeIntInRange(0, 99)}" if fdp.ConsumeBool() else ""
    call = fdp.ConsumeUnicodeNoSurrogates(10)
    middle = fdp.ConsumeUnicodeNoSurrogates(40)
    snr = fdp.ConsumeIntInRange(-60, 120)
    wpm = fdp.ConsumeIntInRange(0, 999)
    hhmm = f"{fdp.ConsumeIntInRange(0, 9999):04d}"
    if fdp.ConsumeBool():  # RBN's structured tail
        tail = f"{middle[:6]} {snr} dB {wpm} WPM CQ {hhmm}Z"
    else:  # a cluster's free-text comment
        tail = f"{middle} {hhmm}Z"
    return f"{prefix}{spotter}: {khz}{frac} {call} {tail}"

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""RSS and Atom feeds, parsed here rather than in the browser.

VA3HDL's dashboard routes feeds through api.rss2json.com. That hands a third
party the list of everything you read and injects their output into your page.
We fetch the feed ourselves, parse it, and strip it to plain text before it ever
reaches a snapshot -- so the browser receives titles and links, not markup.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree as DefusedET

from ..config import SourceConfig
from .base import FetchError, get_bounded

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

MAX_ITEMS = 30
MAX_SUMMARY_CHARS = 400

_ATOM = "{http://www.w3.org/2005/Atom}"


def to_text(raw: str | None, *, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Strip markup and collapse whitespace.

    The frontend renders these with textContent, so this is belt-and-braces --
    but a snapshot file should not contain markup that a future panel might be
    tempted to innerHTML.
    """
    if not raw:
        return ""
    text = _WS.sub(" ", html.unescape(_TAG.sub(" ", raw))).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


def safe_link(raw: str | None) -> str | None:
    """Keep only http(s) links. A feed is not allowed to hand us javascript:."""
    if not raw:
        return None
    link = raw.strip()
    if urlsplit(link).scheme.lower() not in {"http", "https"}:
        return None
    return link


def gather(parent: Any, tag: str) -> str | None:
    """All text inside a child element, including text after nested tags.

    ``findtext`` stops at the first child element, so a feed that writes
    ``<title>AO-91 &amp; the <b>new</b> schedule</title>`` as real markup rather
    than escaped text would silently lose everything from ``<b>`` onward. Both
    forms occur in the wild; this handles them the same way.
    """
    node = parent.find(tag)
    if node is None:
        return None
    return "".join(node.itertext()) or None


def _parse_rss(root: Any) -> list[dict[str, Any]]:
    items = []
    for item in root.findall(".//item")[:MAX_ITEMS]:
        items.append(
            {
                "title": to_text(gather(item, "title"), limit=200),
                "link": safe_link(gather(item, "link")),
                "summary": to_text(gather(item, "description")),
                "published": (item.findtext("pubDate") or "").strip() or None,
            }
        )
    return items


def _parse_atom(root: Any) -> list[dict[str, Any]]:
    items = []
    for entry in root.findall(f"{_ATOM}entry")[:MAX_ITEMS]:
        link = None
        for candidate in entry.findall(f"{_ATOM}link"):
            rel = candidate.get("rel", "alternate")
            if rel == "alternate":
                link = safe_link(candidate.get("href"))
                break
        items.append(
            {
                "title": to_text(gather(entry, f"{_ATOM}title"), limit=200),
                "link": link,
                "summary": to_text(
                    gather(entry, f"{_ATOM}summary") or gather(entry, f"{_ATOM}content")
                ),
                "published": (
                    entry.findtext(f"{_ATOM}updated") or entry.findtext(f"{_ATOM}published") or ""
                ).strip()
                or None,
            }
        )
    return items


class RssSource:
    kind = "rss"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        try:
            root = DefusedET.fromstring(response.content)
        except Exception as exc:
            raise FetchError(f"{cfg.url}: feed parse failed ({exc})") from exc

        items = _parse_atom(root) if root.tag.startswith(_ATOM) else _parse_rss(root)
        if not items:
            raise FetchError(f"{cfg.url}: parsed but contained no items")

        title = gather(root, f"{_ATOM}title") or gather(root, ".//channel/title")
        return {
            "feed_title": to_text(title, limit=120) or cfg.id,
            "items": items,
            "item_count": len(items),
        }


def parse_feed_date(raw: str | None) -> datetime | None:
    """Best-effort feed timestamp. Feeds are inconsistent; callers tolerate None."""
    if not raw:
        return None
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

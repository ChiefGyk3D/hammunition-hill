# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Who made this, and where to find or support him.

Published as a snapshot like everything else the browser shows, because the
frontend bans hardcoded external URLs (tests/test_frontend.py) and an About
card is exactly the kind of thing that would erode that rule one exception at
a time. The links live here, on the Python side, and the panel renders plain
anchors -- which cost nothing under the CSP and navigate away deliberately,
the same line the pocket reference's link directory already draws.

The support entry names what the support page offers but carries no
cryptocurrency addresses. That is deliberate and load-bearing: an address
copied into a repository goes stale the day it rotates and misdirects money
until someone notices, and a page the author controls is the only copy that
can be trusted. Link to the source of truth; never cache other people's
payment details.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import __version__
from .config import Config
from .snapshot import Snapshot, write_snapshot

# fmt: off
# Data, not code: one row per destination, laid out to be proofread against
# https://support.chiefgyk3d.com/ -- which is where this list was taken from,
# fetched 2026-08-29, not typed from memory. The personal website is absent
# on purpose: the author says the blog is stale, and a link that lands on
# something abandoned costs more trust than no link. Restore it when the
# site is worth sending people to.
SOCIALS: tuple[dict[str, str], ...] = (
    {"name": "GitHub",    "url": "https://github.com/ChiefGyk3D"},
    {"name": "Mastodon",  "url": "https://social.chiefgyk3d.com/@chiefgyk3d"},
    {"name": "Bluesky",   "url": "https://bsky.app/profile/chiefgyk3d.com"},
    {"name": "YouTube",   "url": "https://www.youtube.com/channel/UCvFY4KyqVBuYd7JAl3NRyiQ"},
    {"name": "Twitch",    "url": "https://twitch.tv/chiefgyk3d"},
    {"name": "Kick",      "url": "https://kick.com/chiefgyk3d"},
    {"name": "TikTok",    "url": "https://www.tiktok.com/@chiefgyk3d"},
    {"name": "Instagram", "url": "https://www.instagram.com/chiefgyk3d/"},
    {"name": "Pixelfed",  "url": "https://pics.chiefgyk3d.com/ChiefGyk3D"},
    {"name": "Discord",   "url": "https://discord.chiefgyk3d.com"},
    {"name": "Matrix",    "url": "https://matrix-invite.chiefgyk3d.com"},
)
# fmt: on


def about_payload() -> dict[str, Any]:
    """Everything the about card shows."""
    return {
        "project": {
            "name": "Hammunition Hill",
            "version": __version__,
            "license": "MPL-2.0",
            "repo": "https://github.com/ChiefGyk3D/hammunition-hill",
            "companion": "https://github.com/ChiefGyk3D/Hammunition",
            "tagline": (
                "A ham radio dashboard that runs on your own machine, on your "
                "own network, and talks to nobody you did not name."
            ),
        },
        "author": {
            "name": "ChiefGyk3D",
            "support": {
                "url": "https://support.chiefgyk3d.com",
                # What the page offers, so the card can say more than "donate".
                # The addresses themselves stay on that page on purpose.
                "offers": (
                    "Patreon, Ko-fi, tips, merch, and cryptocurrency "
                    "(BTC, XMR, ETH, SOL) — addresses live on the page itself"
                ),
            },
            "socials": list(SOCIALS),
        },
    }


def publish_about(config: Config) -> None:
    """Written once at startup, tier 0: nothing here was fetched from anywhere."""
    write_snapshot(
        config.data_dir,
        Snapshot(
            source_id="about",
            kind="about",
            fetched_at=datetime.now(UTC),
            stale_after_seconds=0,
            data=about_payload(),
        ),
    )

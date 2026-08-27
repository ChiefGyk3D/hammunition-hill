# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Contrast floors for the palette, measured rather than eyeballed.

A dashboard is read at a distance, often across a room, frequently by someone
whose eyes are on a radio rather than the screen. Contrast is the one property
of a colour scheme that is not a matter of taste, so it is the one worth
asserting.

This exists because repainting the accent in the logo's colours was proposed.
The logo purple is #912795, which is 2.62:1 against the dashboard ground --
below the 3:1 floor for user interface components and well below the 4.5:1 for
text. It would have been a straight readability regression made for brand
reasons, and nothing in the repository would have objected.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "web" / "style.css").read_text(encoding="utf-8")


def tokens() -> dict[str, str]:
    """The `--name: #hex;` declarations on :root."""
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", CSS))


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """Relative luminance, WCAG 2.x definition."""
    h = colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    high, low = max(la, lb), min(la, lb)
    return (high + 0.05) / (low + 0.05)


def test_the_contrast_helper_is_right():
    """Check the maths against the two ends of the scale before trusting it."""
    assert contrast("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)
    assert contrast("#777777", "#777777") == pytest.approx(1.0, abs=0.01)
    # A published reference pair: #767676 on white is the canonical 4.5:1 case.
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.05)


SURFACES = ("ground", "panel", "panel-2")

# Tokens used as foreground text somewhere in the stylesheet, and the floor
# each has to clear on every surface it can land on.
FOREGROUND_FLOORS = {
    "ink": 7.0,  # body text, so AAA
    "muted": 4.5,  # secondary text, AA
    "accent": 4.5,  # links, active tabs, callsigns: text, not decoration
    "good": 3.0,  # status, always paired with a label and a number
    "fair": 3.0,
    "poor": 3.0,
}


@pytest.mark.parametrize("token", sorted(FOREGROUND_FLOORS))
@pytest.mark.parametrize("surface", SURFACES)
def test_foreground_tokens_clear_their_contrast_floor(token, surface):
    palette = tokens()
    assert token in palette, f"--{token} is not defined"
    assert surface in palette, f"--{surface} is not defined"
    measured = contrast(palette[token], palette[surface])
    floor = FOREGROUND_FLOORS[token]
    assert measured >= floor, (
        f"--{token} on --{surface} is {measured:.2f}:1, below the {floor}:1 floor"
    )


def test_the_accent_is_readable_as_a_fill_as_well_as_as_text():
    """`.chip.on` and `.need-badge` put --ground *on* --accent.

    Contrast is symmetric, so one measurement covers both directions -- but
    only because both roles use the same pair. If a third role ever paints
    accent text on a panel, that is the pair above.
    """
    palette = tokens()
    assert contrast(palette["accent"], palette["ground"]) >= 4.5


def test_the_brand_purple_is_not_used_as_a_foreground():
    """--brand is the mark's plate colour, and it is not readable as text.

    At 2.62:1 on the ground it fails every floor there is. It is fine as a
    large solid shape carrying no text, which is what the mark is, and it must
    not quietly become a text colour because it is "the brand colour".
    """
    palette = tokens()
    assert contrast(palette["brand"], palette["ground"]) < 3.0, (
        "--brand now clears 3:1; if it was deliberately lightened, move it into "
        "FOREGROUND_FLOORS instead of deleting this test"
    )
    for line in CSS.splitlines():
        if "var(--brand)" in line and "color:" in line and "background" not in line:
            raise AssertionError(f"--brand used as a text colour: {line.strip()}")

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The brand package: the mark, the palette, and the traps found the hard way.

Every check here corresponds to something that actually shipped broken while
this package was being built, which is the only reason to have a test at all:

* A double hyphen inside an XML comment made the first mark unparseable, so the
  header rendered a broken image icon. It is easy to misread that glyph as a
  design problem rather than as a file that will not load.
* A cutout drawn with overlapping subpaths and ``fill-rule="evenodd"`` filled
  the overlaps back in, shattering the glyph into loose blocks.
* ``optimize=True`` renumbers a PNG palette to drop unused entries, leaving the
  transparency index pointing at whatever colour lands in that slot. The logo
  shipped with a black box behind it.
* ``getpalette()`` returns only the entries in use, so appending a clear colour
  at index 255 to a 128 colour palette produces a 129 entry palette in which
  index 255 does not exist. The file is then silently opaque.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
PALETTE = json.loads((BRAND / "palette.json").read_text(encoding="utf-8"))
CSS = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "BRANDING.md").read_text(encoding="utf-8")

# The citation for why the mark is not the HH monogram. Kept as a whole URL
# so the check below can compare parsed links rather than search for a
# hostname anywhere in the page.
CITATION = "https://www.adl.org/resources/hate-symbol/hh"

MARKS = sorted(BRAND.glob("mark*.svg"))
RASTERS = sorted(BRAND.glob("*.png"))


def test_there_are_marks_to_check():
    """Guard the globs above: an empty glob makes every parametrised test vanish."""
    assert len(MARKS) == 3, [p.name for p in MARKS]
    assert RASTERS, "no rasterised brand assets found"


@pytest.mark.parametrize("svg", MARKS + [ROOT / "web" / "mark.svg"], ids=lambda p: p.name)
def test_every_mark_is_well_formed_xml(svg):
    """A mark that will not parse renders as a broken image icon, not as nothing."""
    # defusedxml rather than the standard library: ruff's S314 and CodeQL's
    # py/xxe both flag xml.etree here, and CodeQL fails the build over it.
    # The input is a file in this repository, so the finding is theoretical,
    # but "the input is trusted" is an argument that stops being true the
    # moment somebody reuses the helper -- and defusedxml is a pure-python
    # test-only dependency with nothing behind it. Cheaper than an exemption
    # that has to be re-justified every time the rule fires.
    from defusedxml.ElementTree import parse

    parse(svg)


@pytest.mark.parametrize("svg", MARKS + [ROOT / "web" / "mark.svg"], ids=lambda p: p.name)
def test_no_double_hyphen_inside_a_comment(svg):
    """The specific way the first mark became unparseable.

    ``ET.parse`` already rejects it, but only as "not well-formed", which sends
    you looking at the wrong thing. Name the actual mistake.
    """
    for comment in re.findall(r"<!--(.*?)-->", svg.read_text(encoding="utf-8"), re.S):
        assert "--" not in comment, f"{svg.name}: a double hyphen ends an XML comment early"


@pytest.mark.parametrize("svg", MARKS, ids=lambda p: p.name)
def test_every_mark_carries_its_licence_and_a_label(svg):
    text = svg.read_text(encoding="utf-8")
    assert "Mozilla Public" in text, f"{svg.name}: no licence header"
    assert "<title>Hammunition Hill</title>" in text, f"{svg.name}: no accessible name"
    assert 'viewBox="0 0 64 64"' in text, f"{svg.name}: marks share one viewBox"


def test_the_marks_agree_on_geometry():
    """The variants are recolourings, not redrawings.

    mark-mono.svg reuses the colour mark's paths inside a mask so the two
    cannot drift; this asserts that reuse rather than trusting it. If a variant
    is ever redrawn by hand, this fails and says so.
    """

    def paths(svg: Path) -> set[str]:
        text = svg.read_text(encoding="utf-8")
        return {re.sub(r"\s+", " ", d).strip() for d in re.findall(r'\sd="([^"]+)"', text)}

    colour = paths(BRAND / "mark.svg")
    for variant in ("mark-light.svg", "mark-mono.svg"):
        shared = colour & paths(BRAND / variant)
        assert len(shared) >= 3, (
            f"{variant} shares only {len(shared)} paths with mark.svg; "
            "the variants are meant to reuse its geometry, not restate it"
        )


def test_the_shipped_mark_is_the_brand_mark():
    """web/ serves its own copy, because the server serves one directory."""
    assert (ROOT / "web" / "mark.svg").read_bytes() == (BRAND / "mark.svg").read_bytes()


def test_the_mark_is_not_the_letters():
    """The reason the mark was redrawn at all.

    HH standing alone in heavy letterforms is a recognised hate symbol, and a
    favicon is exactly the context that strips a monogram of everything that
    would otherwise disambiguate it. Nothing stops someone reinstating it in
    good faith years from now, so the reason lives next to the check.
    """
    for svg in MARKS + [ROOT / "web" / "mark.svg"]:
        text = svg.read_text(encoding="utf-8")
        drawing = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        assert "HH" not in drawing, f"{svg.name}: the mark must not be the HH monogram"
    # Compare parsed link targets, not a substring of the page. CodeQL flags
    # `"adl.org" in text` as incomplete URL sanitization, and while nothing
    # here is sanitizing anything, the rule has a point: a bare hostname
    # matches at any position, so this assertion would also have passed on
    # "notadl.org.example" or on the domain appearing in prose.
    links = set(re.findall(r"\]\((https?://[^)\s]+)\)", DOC))
    assert CITATION in links, (
        f"BRANDING.md must keep the reference for why; its links are {sorted(links)}"
    )


@pytest.mark.parametrize("name", ["brand", "brand-ink", "brand-deep"])
def test_the_palette_matches_the_stylesheet(name):
    """palette.json and style.css publish the same colours or one of them lies."""
    value = PALETTE["brand"][name]
    if name == "brand-deep":
        pytest.skip("brand-deep is artwork shadow, not a dashboard token")
    assert f"--{name}: {value};" in CSS, f"style.css disagrees with palette.json on {name}"


def test_the_palette_reproduces_the_dashboard_surface():
    for token, value in {**PALETTE["surface"], **PALETTE["status"]}.items():
        assert f"--{token}: {value};" in CSS, (
            f"palette.json publishes --{token} as {value}; style.css does not"
        )


@pytest.mark.parametrize("png", RASTERS, ids=lambda p: p.name)
def test_rasterised_assets_are_sane(png):
    size = png.stat().st_size
    assert size > 300, f"{png.name} is {size} bytes -- did the render fail?"
    assert size < 500_000, f"{png.name} is {size // 1024} kB -- quantise it"


@pytest.mark.parametrize(
    "png",
    [
        ROOT / "docs/images/logo.png",
        ROOT / "docs/images/logo-256.png",
        BRAND / "logo-original-monogram.png",
    ],
    ids=lambda p: p.name,
)
def test_the_logo_is_actually_transparent(png):
    """Two separate encoding bugs shipped an opaque logo before this existed.

    Both were invisible in isolation: the file opens, the artwork is right, and
    the only symptom is a black box that appears when it is placed on anything
    that is not black.
    """
    from PIL import Image

    with Image.open(png) as im:
        # histogram()[0] is the count of fully clear pixels, and unlike
        # getdata() it is not deprecated out from under us.
        clear = im.convert("RGBA").getchannel("A").histogram()[0]
        total = im.width * im.height
    assert clear > total // 10, (
        f"{png.name}: only {clear} of {total} pixels are transparent. "
        "A palette PNG loses its clear index to optimize=True, and to a "
        "palette shorter than the index it names."
    )


def test_branding_doc_is_linked_from_the_readme():
    assert "BRANDING.md" in (ROOT / "README.md").read_text(encoding="utf-8")

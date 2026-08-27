# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""47 CFR Part 97, and the parsing that gets it out of a printed volume.

The value of this feature is entirely that the text is the FCC's, verbatim. A
parser that quietly drops a clause, joins two words wrongly, or attributes one
section's text to another turns an authoritative quote into a plausible
fabrication, which is worse than showing nothing -- the reader has no way to
tell, and the whole reason to show a rule is that it can be trusted.

So these check the shipped file against what the regulation actually says.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hammunition_hill.part97 import (
    Part97Error,
    dehyphenate,
    parse,
    section_for,
    shipped,
)

ROOT = Path(__file__).resolve().parents[1]
POOLS = ROOT / "src" / "hammunition_hill" / "data" / "exam"


@pytest.fixture(scope="module")
def part97() -> dict:
    payload = shipped()
    assert payload, "Part 97 is not shipped with the package"
    return payload


def sections(payload: dict) -> dict[str, dict]:
    return {s["number"]: s for s in payload["sections"]}


def test_part_97_has_the_sections_it_should(part97):
    """Sixty-three in the 2025 edition.

    The count is asserted because the two failure modes are silent. A regex
    that is too strict drops sections, which shows up as a question citing a
    rule that "is not in the bundled edition"; one that is too loose promotes
    cross references into sections, which shows up as a rule with somebody
    else's text under it.
    """
    found = sections(part97)
    assert len(found) >= 60, f"only {len(found)} sections parsed"
    for expected in ("97.1", "97.3", "97.13", "97.19", "97.21", "97.103", "97.113", "97.213"):
        assert expected in found, f"§{expected} is missing"


def test_the_basis_and_purpose_says_what_it_says(part97):
    """A known section, checked word for word against the regulation.

    §97.1 is the one every ham has read, which makes it the right canary: if
    de-hyphenation or line joining mangles anything, it shows here first.
    """
    section = sections(part97)["97.1"]
    assert section["title"] == "Basis and purpose."
    body = " ".join(section["text"].split())
    assert "Recognition and enhancement of the value of the amateur service" in body
    assert "voluntary noncommercial communication service" in body
    assert "providing emergency communications" in body


def test_no_section_swallowed_the_next_one(part97):
    """Each section's text must not contain the following section's heading."""
    ordered = part97["sections"]
    for current, following in zip(ordered, ordered[1:], strict=False):
        assert f"§ {following['number']} {following['title']}" not in current["text"], (
            f"§{current['number']} has run into §{following['number']}"
        )


def test_every_section_has_text(part97):
    for section in part97["sections"]:
        assert section["title"].endswith("."), f"§{section['number']} title looks truncated"
        assert len(section["text"]) > 40, f"§{section['number']} has almost no text"


def test_only_genuine_compounds_keep_a_line_broken_hyphen(part97):
    """A word split by the column and left split is the quietest defect here.

    The sentence still reads as a sentence, so nothing looks wrong; the reader
    just sees `ap-proval`. But some hyphens across a line break are real --
    `re-licensing` is hyphenated in the regulation itself -- so the test cannot
    simply forbid them.

    The property that actually holds: a surviving break must be a compound the
    document uses hyphenated somewhere else. Anything else is a join that was
    missed. The first version of the joiner left 197 of 957 unresolved, because
    joining two adjacent broken lines consumed the second before its own hyphen
    was looked at.
    """
    corpus = " ".join(s["text"] for s in part97["sections"])
    hyphenated = {w.lower() for w in re.findall(r"[A-Za-z]+-[A-Za-z]+", corpus.replace("\n", " "))}

    survivors = []
    for section in part97["sections"]:
        for match in re.finditer(r"([A-Za-z]+)-\s*\n\s*([A-Za-z]+)", section["text"]):
            compound = f"{match.group(1)}-{match.group(2)}".lower()
            if compound not in hyphenated:
                survivors.append(f"§{section['number']}: {compound}")
    assert not survivors, "line breaks that should have been joined:\n  " + "\n  ".join(survivors)


def test_no_page_furniture_survived(part97):
    """Running heads land mid sentence, which is how one was found.

    `Federal Communications Commission § 97.115` sat inside §97.113's list of
    prohibited transmissions, between paragraphs (2) and (3), reading as though
    it were part of the rule. The head for the *next* part, `Pt. 101`, made it
    into §97.527 the same way after the first fix only covered Part 97.
    """
    # Whole lines, not substrings. §97.3(a)(21) defines "FCC. Federal
    # Communications Commission", so forbidding that phrase outright fails on
    # the regulation itself -- which is exactly what the first version of this
    # test did, once paragraph reflow joined the definition onto one line.
    furniture = re.compile(
        r"^\s*(?:"
        r"Federal Communications Commission(?:\s+(?:§\s*\d+\.\d+|Pt\.\s*\d+))?"
        r"|\d+ CFR Ch\. I.*"
        r"|VerDate.*|Jkt\s.*"
        r")\s*$"
    )
    found = []
    for section in part97["sections"]:
        for line in section["text"].splitlines():
            if furniture.match(line):
                found.append(f"§{section['number']}: {line.strip()!r}")
    assert not found, "page furniture in the regulation text:\n  " + "\n  ".join(found)


def test_dehyphenation_keeps_real_compounds():
    """The rule that decides has to work in both directions.

    `re-licensing` appears hyphenated elsewhere in the document, so it keeps
    its hyphen. `approval` appears whole, so `ap-` + `proval` joins. Both
    decisions come from the document itself rather than from a word list.
    """
    text = (
        "the approval was fine\nand re-licensing too\nseeking ap-\nproval now\nafter re-\nlicensing"
    )
    out = dehyphenate(text)
    assert "approval now" in out.replace("\n", " ")
    assert "re-licensing" in out


def test_a_paragraph_citation_resolves_to_its_section():
    assert section_for("97.113(a)(4)") == "97.113"
    assert section_for("97.3") == "97.3"
    # T1C10 writes 97.5a where it means 97.5(a); Part 97 has no lettered sections.
    assert section_for("97.5a") == "97.5"
    assert section_for("1.931") == ""
    assert section_for("") == ""


def test_every_part_97_citation_in_every_pool_resolves(part97):
    """The feature is only worth having if the citations land.

    194 questions across the three elements carry a reference. Two of them cite
    Part 1 rather than Part 97 -- §1.931 and §1.1307 -- and are expected not to
    resolve, because Part 1 is a different document that is not bundled. Every
    other one must find its section.
    """
    found = sections(part97)
    outside = {"1.931", "1.1307(1)(b)(3)(i)(A)"}
    unresolved = []
    total = 0
    for path in sorted(POOLS.glob("*.json")):
        for question in json.loads(path.read_text(encoding="utf-8"))["questions"]:
            reference = question.get("reference")
            if not reference or reference in outside:
                continue
            total += 1
            if section_for(reference) not in found:
                unresolved.append(f"{question['id']} cites {reference}")
    assert total > 150, f"only {total} citations found; did the pools change shape?"
    assert not unresolved, "citations that do not resolve:\n  " + "\n  ".join(unresolved)


def test_a_document_that_is_not_part_97_is_refused():
    with pytest.raises(Part97Error):
        parse("This is not the Code of Federal Regulations.\nIt is a shopping list.\n")


def test_the_shipped_file_is_readable_json():
    """Same reasoning as the question pools: this is review material."""
    path = ROOT / "src" / "hammunition_hill" / "data" / "part97.json"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 100, "part97.json has been minified"
    assert lines[0] == "{"

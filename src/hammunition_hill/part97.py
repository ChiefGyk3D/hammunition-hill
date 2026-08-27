# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""47 CFR Part 97, so a rules answer can cite the rule.

Every question in the NCVEC pools that tests a regulation carries the section
it comes from -- `97.3`, `97.113(a)(4)`, and so on. 191 of the 1431 questions
across the three US elements do. Shipping the regulation next to the pool turns
"the answer is C" into "the answer is C, and here is the sentence that makes it
so", for the subset where the reason genuinely *is* the rule.

The other 1240 questions are technical, and their reason is physics. This
module does not pretend otherwise, and nothing here writes an explanation:
every word shown to a reader is the FCC's, extracted from the CFR as published.
That was the whole point. A wrong explanation is worse than none, because it
teaches a mental model that fails on every *related* question too, and the
reader has no way to know.

Parsing the CFR is the awkward part. It is published as a two column PDF, so
the extracted text arrives hard wrapped, with the running headers of a printed
volume, and with roughly a thousand words split across lines by a typesetter's
hyphen. See `dehyphenate` for how those are put back together without a
dictionary, and without guessing.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

DATA_FILE = "data/part97.json"


class Part97Error(ValueError):
    """The document is not Part 97, or not in the shape this can read."""


# Running heads, footers and artefacts of the printed volume. None of these are
# regulation text; all of them land mid-sentence if left in.
# The left-hand running head carries a section number on the same line, so it
# has to be matched whole rather than by its opening words: dropping any line
# starting "Federal Communications Commission" would also drop regulation text
# that happens to begin that way. Leaving it in put a page header into the
# middle of §97.113's prohibited-transmissions list, mid sentence.
_NOISE = re.compile(
    r"^\s*(?:"
    r"\d{1,4}"  # a bare page number
    r"|Federal Communications Commission(?:\s+(?:§\s*\d+\.\d+[a-z]?|Pt\. \d+))?"
    r"|47 CFR Ch\. I.*"  # the running head
    r"|VerDate.*|Jkt \d+.*|PO \d+.*|Frm \d+.*"  # GPO typesetting marks
    r"|Pt\. \d+\s*|§+ ?\d+\.\d+[a-z]?\s*"  # running section heads
    r")\s*$"
)

# A heading sits at the start of a line, begins its title on that same line,
# and ends that title in a full stop -- which may be one line further down,
# because the column is narrow and long titles wrap:
#
#     § 97.315 Certification of external RF
#     power amplifiers.
#
# Requiring text after the number *on the number's own line* is what separates
# a heading from the two things that look like one. A running head leaves
# `§ 97.21` alone on a line with body text beneath it, and a cross reference
# reads `§ 97.309(a) may be transmitted` with no space before the parenthesis.
# Both are rejected by that rule rather than by a list of exceptions.
_HEADING = re.compile(
    r"(?m)^§[ \t]*(?P<number>97\.\d+[a-z]?)[ \t]+"
    r"(?P<title>[^\n]{2,90}?(?:\n[^\n(]{1,70}?)?\.)[ \t]*$"
)

_SUBPART = re.compile(r"(?m)^\s*Subpart\s+(?P<letter>[A-Z])\s*[—–-]\s*(?P<title>\S.{2,90}?)\s*$")

# `97.113(a)(4)` and `97.3(a)(4)(ii)` both resolve to the section they open with.
_REFERENCE = re.compile(r"(?P<section>9?7?\.?97\.\d+[a-z]?|97\.\d+[a-z]?)")


def dehyphenate(text: str) -> str:
    """Rejoin words a typesetter split across a line, without a dictionary.

    The document is its own dictionary. A word broken at a line end almost
    always appears intact somewhere else in thirty-eight pages, so the
    vocabulary is built from tokens that were *not* at a break and each split is
    resolved against it:

    * `approval` is in the vocabulary, so `ap-` + `proval` joins.
    * `re-licensing` is in the vocabulary *with* its hyphen, so it keeps it.
    * Neither form appears: join anyway.

    That last rule is a default, so it was checked rather than assumed. All 103
    cases in the 2025 edition are typographic wraps -- `res-ervoir`,
    `al-phabetized`, `Recommenda-tion`, `Mis-souri` -- and not one is a genuine
    compound. The two that are genuine, `re-licensing` and `re-administered`,
    are caught by the second rule and keep their hyphens.
    """
    vocabulary: Counter[str] = Counter()
    for line in text.splitlines():
        body = line[:-1] if line.endswith("-") else line
        for token in re.findall(r"[A-Za-z][A-Za-z-]*[A-Za-z]", body):
            vocabulary[token.lower()] += 1

    def join(match: re.Match[str]) -> str:
        left, right = match.group("left"), match.group("right")
        compound = f"{left}-{right}".lower()
        if compound in vocabulary and (left + right).lower() not in vocabulary:
            return match.group(0)
        return f"{left}{right}"

    # Repeatedly, not once. A single pass leaves a cascade unresolved: where
    # two broken lines are adjacent, joining the first consumes the second and
    # the second's own hyphen never gets looked at. Substitution runs until the
    # text stops changing, which is the only way the last one in a run is
    # reached. That bug shipped 197 surviving hyphens out of 957 and read as
    # "de-hyphenation does not work" rather than as an off-by-one.
    split = re.compile(r"(?P<left>[A-Za-z]+)-[ \t]*\n[ \t]*(?P<right>[A-Za-z]+)")
    for _ in range(20):
        joined = split.sub(join, text)
        if joined == text:
            break
        text = joined
    return text


# A paragraph opens with its designator -- (a), (1), (i), (A) -- or is the
# bracketed amendment history at the end of a section. Everything else is the
# continuation of the paragraph above it, broken there only because the printed
# column ran out of room.
_PARAGRAPH_START = re.compile(r"^\s*(?:\([a-zA-Z0-9]{1,4}\)|\[)")


def reflow(text: str) -> str:
    """Undo the column, keep the structure.

    The CFR is set in a narrow column, so every paragraph arrives as a stack of
    short lines. Rendered as-is it reads like verse, which is a poor way to
    present a regulation somebody is trying to understand.

    Paragraph lettering is not decoration here -- a citation like 97.103(c)
    only means something if (c) is findable -- so the designators keep their
    own lines and only the wraps inside a paragraph are joined.
    """
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out.append("")
            continue
        if out and out[-1] and not _PARAGRAPH_START.match(line):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return "\n".join(out)


def clean(text: str) -> str:
    """Strip the printed volume's furniture, then rejoin split words."""
    kept = [line.rstrip() for line in text.splitlines() if not _NOISE.match(line)]
    return dehyphenate("\n".join(kept))


@dataclass(frozen=True)
class Section:
    number: str
    title: str
    text: str
    subpart: str = ""
    subpart_title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "text": self.text,
            "subpart": self.subpart,
            "subpart_title": self.subpart_title,
        }


@dataclass(frozen=True)
class Part97:
    edition: str
    sections: dict[str, Section] = field(default_factory=dict)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "edition": self.edition,
            "source": self.source,
            "sections": [s.to_dict() for s in self.sections.values()],
        }


def section_for(reference: str) -> str:
    """`97.113(a)(4)` -> `97.113`. The section is what we can show.

    Pools cite down to the paragraph, and quoting one paragraph out of its
    section is how a rule gets misread: the exceptions usually live two
    paragraphs down. So the whole section is shown, and the citation says which
    part of it the question came from.

    Digits only, deliberately. Part 97 has no letter suffixed sections -- the
    2025 edition has sixty-three and not one of them carries a letter -- so a
    trailing letter in a citation is the pool writing `97.5a` where it means
    `97.5(a)`, which T1C10 does. Matching the letter would leave that question
    pointing at a section that does not exist.
    """
    match = re.search(r"97\.\d+", reference or "")
    return match.group(0) if match else ""


def parse(text: str, *, source: str = "", edition: str = "") -> Part97:
    """Split cleaned CFR text into sections."""
    body = clean(text)

    subparts: list[tuple[int, str, str]] = [
        (m.start(), m.group("letter"), m.group("title").strip()) for m in _SUBPART.finditer(body)
    ]

    heads = list(_HEADING.finditer(body))
    if len(heads) < 20:
        raise Part97Error(
            f"found only {len(heads)} section headings; this does not look like Part 97"
        )

    sections: dict[str, Section] = {}
    for position, head in enumerate(heads):
        start = head.end()
        end = heads[position + 1].start() if position + 1 < len(heads) else len(body)
        number = head.group("number")
        letter = title = ""
        for offset, sub_letter, sub_title in subparts:
            if offset < head.start():
                letter, title = sub_letter, sub_title
        # Later duplicates are running heads that survived; keep the longest.
        candidate = Section(
            number=number,
            title=head.group("title").strip(),
            text=reflow(re.sub(r"\n{3,}", "\n\n", body[start:end]).strip()),
            subpart=letter,
            subpart_title=title,
        )
        if number not in sections or len(candidate.text) > len(sections[number].text):
            sections[number] = candidate

    return Part97(
        edition=edition,
        sections=dict(sorted(sections.items(), key=lambda kv: _sort_key(kv[0]))),
        source=source,
    )


def _sort_key(number: str) -> tuple[int, str]:
    match = re.match(r"97\.(\d+)([a-z]?)", number)
    return (int(match.group(1)), match.group(2)) if match else (0, "")


def read_source(path: Any) -> str:
    """The regulation as text, from a `.txt` or the CFR `.pdf`."""
    from pathlib import Path

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        import pypdf
    except ImportError as exc:
        raise Part97Error(
            "reading the CFR PDF needs the exam extra: "
            "pip install 'hammunition-hill[exam]' — or convert it to text first"
        ) from exc
    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def shipped() -> dict[str, Any]:
    """Part 97 as checked in with this package, or an empty mapping."""
    import json
    from importlib import resources

    try:
        handle = resources.files("hammunition_hill").joinpath(DATA_FILE)
        payload = json.loads(handle.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError, OSError, ValueError):
        return {}
    return payload if payload.get("sections") else {}

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Licence exam practice, from the official question pools.

The US amateur exams are drawn from published pools: NCVEC releases a plain-text
file per element, valid for four years, and every exam is built from it by a
rule that matters more than it looks.

## The rule that makes practice worth anything

**One question from each group.** A Technician exam is 35 questions drawn from
35 groups, one apiece; General is the same shape; Extra is 50 from 50. It is not
a random sample of the pool, and a practice test that took one would be a
different exam -- easier or harder by luck, and never covering the syllabus the
way the real one does.

That is the single most important thing in this module, and the thing a
plausible-looking implementation gets wrong.

## Where the questions come from

Not from here. This parses the official NCVEC release and nothing else, because
a question somebody invented is worse than no practice at all: an operator
studies it, believes it, and is wrong in the exam room about something they were
confident of.

`hamhill exam-import <file>` turns a downloaded pool into the JSON this serves,
the same shape as the FCC ULS importer already in this project: big third-party
data is fetched deliberately by the operator, not vendored or fetched on a
schedule.

## Pools expire

Every pool states the years it is valid for, and studying an expired one is
studying the wrong questions. The window is carried through parsing, published
with the pool, and shown by the panel -- and a pool past its end date is
reported as expired rather than quietly served.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# The three elements, their exam length, and the number of groups each draws
# from. Length and group count are equal by construction: one question per
# group is the rule.
#
# fmt: off
ELEMENTS: tuple[dict[str, Any], ...] = (
    {"id": "technician", "element": 2, "name": "Technician",   "prefix": "T", "questions": 35},
    {"id": "general",    "element": 3, "name": "General",      "prefix": "G", "questions": 35},
    {"id": "extra",      "element": 4, "name": "Amateur Extra","prefix": "E", "questions": 50},
)
# fmt: on

ELEMENT_BY_ID = {entry["id"]: entry for entry in ELEMENTS}
ELEMENT_BY_PREFIX = {entry["prefix"]: entry for entry in ELEMENTS}

# 74% to pass, which is 26 of 35 and 37 of 50. Rounding up, because 25.9 is a
# fail and a practice test that said otherwise would be lying at the only
# moment anybody cares.
PASS_FRACTION = 0.74

ANSWER_LETTERS = ("A", "B", "C", "D")

# T1A01 (C) [97.1]  -- the id, the key, and an optional rule reference.
_QUESTION = re.compile(
    r"^(?P<id>[TGE]\d[A-Z]\d{2})\s*\((?P<answer>[A-D])\)\s*(?:\[(?P<reference>[^\]]*)\])?\s*$"
)
# A line that is trying to be a question header. Narrower than "starts with an
# id", because the releases open with an errata block whose entries also start
# with one -- "G1C09 – question deleted", "T1C01 – change the question to read:".
# Those are prose about a question, not a header, and treating them as malformed
# headers would refuse every real pool file.
#
# So: an id followed by a parenthesis (about to give an answer key), a bracket
# (a reference with the key missing), or nothing at all. An id followed by bare
# prose is left alone, which is the errata case.
_QUESTION_ISH = re.compile(r"^[TGE]\d[A-Z]\d{2}\s*(?:\(|\[|$)")

# The authoritative statement of when a pool is valid, and the reason the panel
# can say "expired" rather than guessing from a pair of years in a title.
#
# Two spellings, because the releases are not consistent: the Technician and
# General pools write "Effective 7/01/2026 – 6/30/2030", the Extra pool writes
# "Effective July 1, 2024". The second gives only a start, so the end comes from
# the year range in the title.
_EFFECTIVE = re.compile(
    r"Effective\s+(?P<from>\d{1,2}/\d{1,2}/\d{4})\s*[-–—]\s*(?P<until>\d{1,2}/\d{1,2}/\d{4})",
    re.I,
)
_EFFECTIVE_FROM = re.compile(
    r"Effective\s+(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})", re.I
)
_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "january february march april may june july august september october november december"
        ).split(),
        start=1,
    )
}

# NCVEC separates questions with a tilde; the PDFs use two. Any run will do.
_SEPARATOR = re.compile(r"^~+$")

# "G1C09 – question deleted" in the errata block at the front of a release.
# Worth reading, because a deleted question that survived into the body is one
# somebody would study and can never be asked -- and it was usually deleted for
# being wrong.
_ERRATUM_DELETED = re.compile(
    r"^(?P<id>[TGE]\d[A-Z]\d{2})\s*[-–—]\s*(?:question\s+)?"
    r"(?:deleted|removed from use|withdrawn)",
    re.I | re.M,
)

# The pool body begins at the last first-subelement heading in the file.
#
# Releases open with an errata block, then a syllabus, then the pool -- and the
# syllabus repeats the subelement headings, so the *last* SUBELEMENT T1 (or G1,
# or E1) is where the questions start. Parsing from there matters more than it
# sounds: the Extra errata restates corrected questions as bare header lines,
# "E1E10 (C) [97.509(m)]" with no text and no answers, which a parser reading
# from the top consumes as questions and then trips over as duplicates of the
# real ones.
_BODY_START = re.compile(r"^SUBELEMENT\s+[TGE]1\b", re.I)

# Any header-shaped line anywhere in the file, used only to notice that two
# elements have been merged into one document. Checked against the whole text
# rather than the parsed body: with the body starting at the last subelement
# heading, a concatenated file would otherwise parse as whichever pool came
# last and say nothing about the one it discarded.
_ANY_HEADER = re.compile(r"^(?P<id>[TGE])\d[A-Z]\d{2}\s*\([A-D]\)", re.M)
# T1A -- group heading. The dash is optional and is not always an em dash: the
# released PDFs write "T1A Purpose and permissible use..." with no dash at all,
# while the plain-text releases use one.
_GROUP = re.compile(r"^(?P<group>[TGE]\d[A-Z])\s*[-–—]?\s+(?P<title>\S.*)$")
_SUBELEMENT = re.compile(r"^SUBELEMENT\s+(?P<subelement>[TGE]\d)\s*[-–—]?\s*(?P<title>.*)$", re.I)
# "[6 Exam Questions - 6 Groups]" on a subelement heading. This is how many of
# the exam's questions come from that subelement, and it is what makes a section
# test a faithful slice of the real thing rather than an arbitrary quiz.
#
# `Questions?` because the Extra release writes E0 as "[1 exam question - 1
# group]" -- singular, and lower case. Requiring the plural silently lost that
# one, and the weights then summed to 49 against a 50-question exam.
_SUBELEMENT_WEIGHT = re.compile(r"\[\s*(?P<questions>\d+)\s*Exam\s+Questions?", re.I)
_ANSWER = re.compile(r"^(?P<letter>[A-D])[.)]\s*(?P<text>.*)$")
# "2022-2026" anywhere in the header, which is how every release states itself.
_VALIDITY = re.compile(r"\b(?P<start>20\d{2})\s*[-–—/]\s*(?P<end>20\d{2})\b")


class ExamError(ValueError):
    """A pool that cannot be trusted to study from."""


def read_source(path: Any) -> str:
    """The pool as text, from a .txt or a .pdf.

    PDF because that is how the releases are actually published now -- both
    ARRL and NCVEC put the pool behind a PDF, and telling an operator to find a
    converter is telling them not to bother. pypdf is an optional extra so the
    core install does not carry a PDF parser it uses once every four years.
    """
    from pathlib import Path

    path = Path(path)
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")

    try:
        import pypdf
    except ImportError as exc:
        raise ExamError(
            "reading a PDF pool needs the exam extra: "
            "pip install 'hammunition-hill[exam]' — or convert it to text first"
        ) from exc

    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@dataclass(frozen=True)
class Question:
    id: str
    group: str
    subelement: str
    text: str
    answers: tuple[str, str, str, str]
    correct: int  # index into answers, 0-3
    reference: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "subelement": self.subelement,
            "text": self.text,
            "answers": list(self.answers),
            "correct": self.correct,
            "reference": self.reference,
        }


@dataclass
class Pool:
    element_id: str
    name: str
    valid_from: int | None
    valid_until: int | None
    # Exact dates when the file states them, which the released PDFs do:
    # "Effective 7/01/2026 - 6/30/2030". Years alone cannot tell you that a
    # pool ended on 30 June and you are studying it in September.
    effective_from: date | None = None
    effective_until: date | None = None
    questions: list[Question] = field(default_factory=list)
    group_titles: dict[str, str] = field(default_factory=dict)
    subelement_titles: dict[str, str] = field(default_factory=dict)
    # How many of the exam's questions each subelement contributes, as the
    # release states it. A section test uses this so practising one subelement
    # is the same shape as that part of the real exam.
    subelement_weights: dict[str, int] = field(default_factory=dict)
    source: str = ""
    # Question ids the release's own errata says were removed. Kept so the
    # importer can prove they really are gone rather than assuming it.
    errata_deleted: tuple[str, ...] = ()

    @property
    def groups(self) -> list[str]:
        """Every group with at least one question, in pool order."""
        seen: dict[str, None] = {}
        for question in self.questions:
            seen.setdefault(question.group, None)
        return list(seen)

    @property
    def subelements(self) -> list[str]:
        """Every subelement with at least one question, in pool order."""
        seen: dict[str, None] = {}
        for question in self.questions:
            seen.setdefault(question.subelement, None)
        return list(seen)

    @property
    def exam_length(self) -> int:
        return int(ELEMENT_BY_ID[self.element_id]["questions"])

    @property
    def pass_mark(self) -> int:
        # Ceiling: 74% of 35 is 25.9, and 26 is the pass.
        return -int(-self.exam_length * PASS_FRACTION // 1)

    def status(self, today: date | None = None) -> str:
        """ "current", "expired", "future", or "unknown" when no dates were stated."""
        if self.valid_from is None or self.valid_until is None:
            return "unknown"
        year = (today or date.today()).year
        if year < self.valid_from:
            return "future"
        # Pools run to 30 June of the final year, but the exact day varies by
        # release and is not stated in the file. Treating the whole final year
        # as valid errs toward not telling somebody their current pool expired.
        if year > self.valid_until:
            return "expired"
        return "current"

    def to_dict(self, today: date | None = None) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element": ELEMENT_BY_ID[self.element_id]["element"],
            "name": self.name,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_until": self.effective_until.isoformat() if self.effective_until else None,
            "status": self.status(today),
            "questions": [question.to_dict() for question in self.questions],
            "groups": self.groups,
            "group_titles": self.group_titles,
            "subelement_titles": self.subelement_titles,
            "subelement_weights": self.subelement_weights,
            "subelements": self.subelements,
            "exam_length": self.exam_length,
            "pass_mark": self.pass_mark,
            "source": self.source,
            "errata_deleted": list(self.errata_deleted),
        }


def _clean(text: str) -> str:
    return " ".join(text.split())


def _us_date(text: str) -> date | None:
    """M/D/YYYY, the way the releases write it."""
    try:
        month, day, year = (int(part) for part in text.split("/"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def parse_pool(text: str, *, source: str = "") -> Pool:
    """Parse an NCVEC release into a Pool.

    Strict about the things that would silently produce a broken exam -- a
    question with the wrong number of answers, an answer key naming a letter
    that is not there, a duplicate id -- and forgiving about layout, because
    the releases differ in whitespace, dash characters and how the tilde
    separator is placed.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    body_start = 0
    for index, line in enumerate(lines):
        if _BODY_START.match(line.strip()):
            body_start = index
    preamble = lines[:body_start]
    # The validity statement lives in the preamble, so it is read from the whole
    # file rather than from the body alone.
    header = "\n".join(lines[: body_start + 40] if body_start else lines[:400])
    validity = _VALIDITY.search(header)
    valid_from = int(validity.group("start")) if validity else None
    valid_until = int(validity.group("end")) if validity else None

    effective_from = effective_until = None
    stated = _EFFECTIVE.search(header)
    if stated:
        effective_from = _us_date(stated.group("from"))
        effective_until = _us_date(stated.group("until"))
        if effective_from and effective_until:
            valid_from, valid_until = effective_from.year, effective_until.year
    else:
        # Only a start date is stated. Pools run to 30 June of the last year in
        # the title, which every release has followed; taking the end from the
        # title is a smaller assumption than having no end date at all, and the
        # panel would otherwise say "unknown" forever.
        named = _EFFECTIVE_FROM.search(header)
        month = _MONTHS.get(named.group("month").lower()) if named else None
        if named and month:
            try:
                effective_from = date(int(named.group("year")), month, int(named.group("day")))
            except ValueError:
                effective_from = None
            if effective_from and valid_until and valid_until > effective_from.year:
                effective_until = date(valid_until, 6, 30)

    questions: list[Question] = []
    group_titles: dict[str, str] = {}
    subelement_titles: dict[str, str] = {}
    subelement_weights: dict[str, int] = {}
    prefixes: set[str] = set()

    index = body_start
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue

        sub = _SUBELEMENT.match(line)
        if sub:
            name_ = sub.group("subelement").upper()
            title = _clean(sub.group("title"))
            weight = _SUBELEMENT_WEIGHT.search(title)
            if weight:
                subelement_weights[name_] = int(weight.group("questions"))
            # The heading carries its own weight in brackets -- "ELECTRICAL
            # PRINCIPLES [4 Exam Questions - 4 Groups] 49 Questions". That is
            # data, not a title, and it is already extracted; leaving it in
            # means the panel prints it back at the reader.
            subelement_titles[name_] = _clean(re.sub(r"\[[^\]]*\].*$", "", title)) or title
            continue

        found = _QUESTION.match(line)
        if not found:
            if _QUESTION_ISH.match(line):
                raise ExamError(
                    f"malformed question header: {line!r}. Expected an id, an "
                    "answer key in parentheses, and an optional [rule] reference."
                )
            # A group heading and a question id both start with the same three
            # characters, so the question pattern is tried first.
            group = _GROUP.match(line)
            if group:
                group_titles[group.group("group").upper()] = _clean(group.group("title"))
            continue

        question_id = found.group("id").upper()
        key = found.group("answer").upper()
        reference = _clean(found.group("reference") or "")

        # The question text is the next non-empty line, then four answers.
        body: list[str] = []
        while index < len(lines) and not body:
            candidate = lines[index].strip()
            index += 1
            if candidate and not _SEPARATOR.match(candidate):
                body.append(candidate)
        if not body:
            raise ExamError(f"{question_id}: no question text")

        answers: dict[str, str] = {}
        while index < len(lines) and len(answers) < 4:
            candidate = lines[index].strip()
            index += 1
            if not candidate or _SEPARATOR.match(candidate):
                if answers:
                    break
                continue
            match = _ANSWER.match(candidate)
            if match:
                answers[match.group("letter").upper()] = _clean(match.group("text"))
            elif answers:
                # A wrapped answer line continues the previous one.
                last = sorted(answers)[-1]
                answers[last] = f"{answers[last]} {_clean(candidate)}"
            else:
                body.append(candidate)

        missing = [letter for letter in ANSWER_LETTERS if letter not in answers]
        if missing:
            raise ExamError(f"{question_id}: missing answer {', '.join(missing)}")
        if key not in answers:
            raise ExamError(f"{question_id}: answer key {key} is not one of the answers")

        questions.append(
            Question(
                id=question_id,
                group=question_id[:3],
                subelement=question_id[:2],
                text=_clean(" ".join(body)),
                answers=tuple(answers[letter] for letter in ANSWER_LETTERS),  # type: ignore[arg-type]
                correct=ANSWER_LETTERS.index(key),
                reference=reference,
            )
        )
        prefixes.add(question_id[0])

    if not questions:
        raise ExamError("no questions found -- is this an NCVEC pool file?")

    seen: set[str] = set()
    for question in questions:
        if question.id in seen:
            raise ExamError(f"duplicate question id {question.id}")
        seen.add(question.id)

    everywhere = {match.group("id").upper() for match in _ANY_HEADER.finditer(text)}
    if len(prefixes | everywhere) != 1:
        raise ExamError(
            f"this file mixes elements ({', '.join(sorted(prefixes | everywhere))}); "
            "each pool is a separate file"
        )
    prefix = prefixes.pop()
    entry = ELEMENT_BY_PREFIX.get(prefix)
    if entry is None:
        raise ExamError(f"unknown element prefix {prefix!r}")

    name = str(entry["name"])
    if valid_from and valid_until:
        name = f"{name} {valid_from}–{valid_until}"

    return Pool(
        element_id=str(entry["id"]),
        name=name,
        valid_from=valid_from,
        valid_until=valid_until,
        effective_from=effective_from,
        effective_until=effective_until,
        errata_deleted=tuple(
            sorted({m.group("id").upper() for m in _ERRATUM_DELETED.finditer("\n".join(preamble))})
        ),
        questions=questions,
        group_titles=group_titles,
        subelement_titles=subelement_titles,
        subelement_weights=subelement_weights,
        source=source,
    )


def check_pool(pool: Pool) -> list[str]:
    """Everything wrong with a pool that does not stop it loading.

    Returned rather than raised: a pool with one group short is still worth
    studying, and the operator should be told rather than handed nothing. The
    importer prints these; the panel shows them.
    """
    problems: list[str] = []
    groups = pool.groups
    if len(groups) < pool.exam_length:
        problems.append(
            f"{len(groups)} question groups but an exam draws {pool.exam_length} — "
            "some questions would have to be drawn twice"
        )
    if pool.valid_from is None or pool.valid_until is None:
        problems.append("no validity years found in the file header")
    thin = [group for group in groups if sum(1 for q in pool.questions if q.group == group) < 2]
    if thin:
        problems.append(f"{len(thin)} groups have only one question: {', '.join(thin[:5])}")

    weights = pool.subelement_weights
    if weights and sum(weights.values()) != pool.exam_length:
        problems.append(
            f"the subelement weights add up to {sum(weights.values())} but the exam is "
            f"{pool.exam_length} questions — a section test would be the wrong size"
        )

    problems.extend(reconcile_errata(pool))
    return problems


def reconcile_errata(pool: Pool) -> list[str]:
    """Check the release's own errata against the questions that survived it.

    Releases arrive with errata applied to the body, and the ones seen so far
    genuinely are -- but "so far" is not a guarantee, and a deleted question
    that stayed in would be studied by somebody and can never be asked. It was
    usually deleted for being wrong, which is worse.

    The other direction is checked too. Every interior gap in a group's
    numbering should be a question the errata removed; a gap that is not one is
    a question this parser lost, which is exactly the failure a count of "it
    parsed" cannot see. A deletion that leaves no gap is normal and not
    reported: removing the last question of a group just shortens it.
    """
    problems: list[str] = []
    present = {question.id for question in pool.questions}

    survived = sorted(set(pool.errata_deleted) & present)
    if survived:
        problems.append(
            f"the errata deletes {', '.join(survived)} but they are still in the pool — "
            "this file is not the corrected release"
        )

    numbers: dict[str, list[int]] = {}
    for question in pool.questions:
        numbers.setdefault(question.group, []).append(int(question.id[3:]))
    gaps = {
        f"{group}{n:02d}"
        for group, seen in numbers.items()
        for n in range(1, max(seen) + 1)
        if n not in seen
    }
    unexplained = sorted(gaps - set(pool.errata_deleted))
    if unexplained:
        problems.append(
            f"{len(unexplained)} questions are missing and the errata does not "
            f"account for them: {', '.join(unexplained[:8])}"
        )
    return problems


def build_exam(pool: Pool, rng: Any) -> list[Question]:
    """One question from each group, in a shuffled order.

    This is the rule the real exam is built by, and the reason this function
    exists rather than a call to random.sample: a uniform sample over the pool
    would over-weight the groups that happen to have more questions and skip
    others entirely, which is a different exam.

    Where there are more groups than the exam has questions, the groups are
    sampled -- and where there are fewer, some group contributes twice, which
    check_pool warns about rather than hiding.
    """
    groups = pool.groups
    by_group: dict[str, list[Question]] = {group: [] for group in groups}
    for question in pool.questions:
        by_group[question.group].append(question)

    chosen_groups = list(groups)
    _shuffle(chosen_groups, rng)
    wanted = pool.exam_length
    while len(chosen_groups) < wanted:
        chosen_groups.extend(groups[: wanted - len(chosen_groups)])
    chosen_groups = chosen_groups[:wanted]

    picked = [by_group[group][rng.below(len(by_group[group]))] for group in chosen_groups]
    _shuffle(picked, rng)
    return picked


def _shuffle(items: list[Any], rng: Any) -> None:
    """Fisher-Yates, matching the browser's, so a seed means the same exam."""
    for i in range(len(items) - 1, 0, -1):
        j = rng.below(i + 1)
        items[i], items[j] = items[j], items[i]


def section_exam(pool: Pool, subelement: str, rng: Any) -> list[Question]:
    """A test over one subelement, the size that subelement contributes.

    The release states it: "SUBELEMENT T1 - COMMISSION'S RULES [6 Exam Questions
    - 6 Groups]". Six questions from six groups is exactly the T1 part of a real
    Technician exam, so practising a section is practising the thing rather than
    a quiz that happens to be about the same topic.

    Falls back to one per group where the release did not state a weight, which
    is the same rule at the section's natural size.
    """
    subelement = subelement.upper()
    groups = [group for group in pool.groups if group.startswith(subelement)]
    if not groups:
        raise ExamError(f"no questions in subelement {subelement!r}")

    by_group: dict[str, list[Question]] = {group: [] for group in groups}
    for question in pool.questions:
        if question.group in by_group:
            by_group[question.group].append(question)

    wanted = pool.subelement_weights.get(subelement, len(groups))
    chosen = list(groups)
    _shuffle(chosen, rng)
    while len(chosen) < wanted:
        chosen.extend(groups[: wanted - len(chosen)])
    chosen = chosen[:wanted]

    picked = [by_group[group][rng.below(len(by_group[group]))] for group in chosen]
    _shuffle(picked, rng)
    return picked


def questions_in(pool: Pool, *, subelement: str = "", group: str = "") -> list[Question]:
    """The pool narrowed to a subelement or a single group, in pool order.

    For working through a section rather than being tested on it -- some people
    read the syllabus straight through, and a study panel that only ever served
    random questions would not let them.
    """
    scope = (group or subelement).upper()
    if not scope:
        return list(pool.questions)
    return [question for question in pool.questions if question.id.startswith(scope)]


def grade(pool: Pool, questions: list[Question], answers: list[int | None]) -> dict[str, Any]:
    """Score an attempt the way a VE session would."""
    if len(questions) != len(answers):
        raise ExamError("one answer per question, please")
    right = sum(
        1 for question, given in zip(questions, answers, strict=True) if given == question.correct
    )
    return {
        "right": right,
        "asked": len(questions),
        "pass_mark": pool.pass_mark,
        "passed": right >= pool.pass_mark,
        "percent": round(100.0 * right / len(questions), 1) if questions else 0.0,
    }


# --- the pools that ship with this package ----------------------------------

DATA_DIR = "data/exam"


def shipped_pools() -> dict[str, dict[str, Any]]:
    """Every pool checked in with this package, keyed by element id.

    Read fresh rather than cached: this runs once at startup, and a module-level
    cache of a megabyte of questions would sit in every process for the life of
    the collector to save a few milliseconds once.
    """
    import json
    from importlib import resources

    pools: dict[str, dict[str, Any]] = {}
    try:
        root = resources.files("hammunition_hill").joinpath(DATA_DIR)
        entries = sorted(root.iterdir(), key=lambda entry: entry.name)
    except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError):
        return pools

    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        element_id = payload.get("element_id")
        if element_id in ELEMENT_BY_ID:
            payload["shipped"] = True
            pools[element_id] = payload
    return pools

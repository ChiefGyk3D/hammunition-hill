# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Licence exam practice.

The questions in this file are **invented**, and say so on every line. Real
pool content is not vendored and not fabricated: an operator studies a practice
question, believes it, and is then confidently wrong in the exam room about the
one thing they were sure of. What is tested here is the machinery -- the parser
against the real NCVEC layout, and the rule that builds an exam.

That rule is the load-bearing part. A real exam draws **one question from each
group**: 35 questions from 35 groups for Technician and General, 50 from 50 for
Extra. A uniform sample over the pool would over-weight whichever groups happen
to have more questions and skip others entirely -- a different exam, easier or
harder by luck, and never covering the syllabus the way the real one does. It is
also exactly what a plausible-looking implementation does instead.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from hammunition_hill.cwpractice import Rng
from hammunition_hill.exam import (
    ELEMENT_BY_ID,
    ExamError,
    build_exam,
    check_pool,
    grade,
    parse_pool,
)

# Group letters per subelement, chosen so a synthetic Technician pool has the
# 35 groups a real one has and the exam rule can be tested at full size.
SUBELEMENTS = {
    "T1": "ABCDEF",
    "T2": "ABC",
    "T3": "ABC",
    "T4": "AB",
    "T5": "ABCD",
    "T6": "ABCD",
    "T7": "ABCD",
    "T8": "ABCD",
    "T9": "AB",
    "T0": "ABC",
}


def synthetic_pool(prefix: str = "T", years: str = "2022-2026", per_group: int = 3) -> str:
    """An NCVEC-shaped file with invented content.

    Shaped faithfully -- subelement headings, group headings, the answer key in
    parentheses, an optional bracketed rule reference, four lettered answers, a
    tilde separator -- because the parser is what is under test. The words are
    nonsense and are labelled as such.
    """
    out = [
        f"{years} AMATEUR RADIO QUESTION POOL — SYNTHETIC, FOR TESTS ONLY",
        "These questions are invented. They are not the NCVEC pool.",
        "",
    ]
    subelements = {k.replace("T", prefix): v for k, v in SUBELEMENTS.items()}
    for subelement, letters in subelements.items():
        out.append(
            f"SUBELEMENT {subelement} – Invented subelement {subelement} "
            f"– [{len(letters)} Exam Questions – {len(letters)} Groups]"
        )
        out.append("")
        for letter in letters:
            group = f"{subelement}{letter}"
            out.append(f"{group} – Invented group {group}")
            out.append("")
            for n in range(1, per_group + 1):
                key = "ABCD"[n % 4]
                out.append(f"{group}{n:02d} ({key}) [97.{n}]")
                out.append(f"Invented question {group}{n:02d}, which is not a real question?")
                for answer_letter in "ABCD":
                    out.append(
                        f"{answer_letter}. Invented answer {answer_letter} for {group}{n:02d}"
                    )
                out.append("~")
                out.append("")
    return "\n".join(out)


@pytest.fixture
def pool():
    return parse_pool(synthetic_pool(), source="synthetic")


# --- parsing ----------------------------------------------------------------


def test_a_pool_parses_into_questions(pool):
    assert pool.element_id == "technician"
    assert len(pool.questions) == 35 * 3
    assert len(pool.groups) == 35


def test_every_field_of_a_question_is_extracted(pool):
    question = next(q for q in pool.questions if q.id == "T1A01")
    assert question.group == "T1A"
    assert question.subelement == "T1"
    assert question.text.startswith("Invented question T1A01")
    assert len(question.answers) == 4
    assert question.reference == "97.1"
    # The header said (B) for n=1, and B is index 1.
    assert question.correct == 1
    assert question.answers[question.correct].startswith("Invented answer B")


def test_the_validity_years_are_read_from_the_header(pool):
    assert pool.valid_from == 2022
    assert pool.valid_until == 2026
    assert "2022" in pool.name and "2026" in pool.name


def test_group_and_subelement_titles_are_kept(pool):
    """The panel shows which part of the syllabus a question came from, and a
    group code alone tells a candidate nothing."""
    assert pool.group_titles["T1A"] == "Invented group T1A"
    assert pool.subelement_titles["T1"].startswith("Invented subelement T1")


@pytest.mark.parametrize("dash", ["-", "–", "—"])
def test_every_dash_the_releases_use_is_accepted(dash):
    """NCVEC releases are not consistent about this and a hyphen-only parser
    silently finds no groups at all."""
    text = synthetic_pool().replace("–", dash)
    assert len(parse_pool(text).groups) == 35


def test_an_answer_wrapped_onto_a_second_line_is_joined():
    text = synthetic_pool().replace(
        "A. Invented answer A for T1A01",
        "A. Invented answer A for T1A01\nwhich continues onto another line",
    )
    question = next(q for q in parse_pool(text).questions if q.id == "T1A01")
    assert question.answers[0].endswith("which continues onto another line")


def test_a_missing_rule_reference_is_not_an_error():
    text = synthetic_pool().replace("T1A01 (B) [97.1]", "T1A01 (B)")
    question = next(q for q in parse_pool(text).questions if q.id == "T1A01")
    assert question.reference == ""


@pytest.mark.parametrize("prefix", ["T", "G", "E"])
def test_each_element_is_recognised_from_its_question_ids(prefix):
    assert (
        parse_pool(synthetic_pool(prefix=prefix)).element_id
        == {
            "T": "technician",
            "G": "general",
            "E": "extra",
        }[prefix]
    )


# --- what it refuses --------------------------------------------------------


def test_a_question_missing_an_answer_is_refused():
    """Silently shipping a three-answer question makes one exam item
    unanswerable, and nothing downstream would notice."""
    text = synthetic_pool().replace("C. Invented answer C for T1A01\n", "")
    with pytest.raises(ExamError, match="missing answer C"):
        parse_pool(text)


def test_an_answer_key_naming_a_letter_that_is_not_there_is_refused():
    """(E) is not an answer, so this is a malformed header rather than a bad key.

    Worth distinguishing: the first version of the parser skipped any line it
    could not read as a header, so this pool loaded one question short and said
    nothing. A file that looks like a question and is not is a problem with the
    file, and the operator should hear about it.
    """
    text = synthetic_pool().replace("T1A01 (B)", "T1A01 (E)")
    with pytest.raises(ExamError, match="malformed question header"):
        parse_pool(text)


@pytest.mark.parametrize("broken", ["T1A01 (B", "T1A01", "T1A01 [97.1]", "T1A01 ((B))"])
def test_a_header_that_does_not_parse_is_reported_not_skipped(broken):
    text = synthetic_pool().replace("T1A01 (B) [97.1]", broken)
    with pytest.raises(ExamError, match="malformed question header"):
        parse_pool(text)


def test_a_key_outside_a_to_d_cannot_silently_become_a_valid_answer():
    """The other half: a key that parses but names a letter with no answer."""
    text = synthetic_pool().replace(
        "D. Invented answer D for T1A01", "X. Invented answer D for T1A01"
    )
    with pytest.raises(ExamError, match="missing answer D"):
        parse_pool(text)


def test_a_duplicate_question_id_is_refused():
    """Two questions with one id means one of them can never be reviewed."""
    text = synthetic_pool().replace("T1A02 (C)", "T1A01 (C)")
    with pytest.raises(ExamError, match="duplicate question id T1A01"):
        parse_pool(text)


def test_a_file_mixing_elements_is_refused():
    """Each pool is a separate file, and a merged one would build an exam from
    two syllabuses."""
    text = synthetic_pool("T") + "\n" + synthetic_pool("G")
    with pytest.raises(ExamError, match="mixes elements"):
        parse_pool(text)


@pytest.mark.parametrize("text", ["", "   \n\n", "This is not a question pool at all."])
def test_a_file_that_is_not_a_pool_is_refused(text):
    with pytest.raises(ExamError, match="no questions found"):
        parse_pool(text)


def test_a_question_with_no_text_is_refused():
    text = synthetic_pool().replace("Invented question T1A01, which is not a real question?\n", "")
    with pytest.raises(ExamError):
        parse_pool(text)


# --- the rule that makes an exam an exam ------------------------------------


def test_an_exam_is_the_right_length(pool):
    assert len(build_exam(pool, Rng(1))) == 35
    assert pool.exam_length == 35


def test_an_exam_draws_one_question_from_each_group(pool):
    """The load-bearing property.

    A uniform sample over the pool would over-weight the groups with more
    questions and skip others entirely. That is a different exam, and it is
    what a plausible-looking implementation does instead.
    """
    for seed in range(40):
        exam = build_exam(pool, Rng(seed))
        groups = [question.group for question in exam]
        assert len(set(groups)) == len(groups), f"seed {seed} drew two from one group"
        assert set(groups) == set(pool.groups), f"seed {seed} missed a group"


def test_an_exam_is_not_in_pool_order(pool):
    """Otherwise every attempt walks the syllabus in the same order and the
    candidate learns positions rather than material."""
    exam = build_exam(pool, Rng(7))
    assert [q.group for q in exam] != pool.groups


def test_the_same_seed_gives_the_same_exam(pool):
    first = [q.id for q in build_exam(pool, Rng(99))]
    second = [q.id for q in build_exam(pool, Rng(99))]
    assert first == second


def test_different_seeds_give_different_exams(pool):
    first = [q.id for q in build_exam(pool, Rng(1))]
    second = [q.id for q in build_exam(pool, Rng(2))]
    assert first != second


def test_over_many_exams_every_question_can_appear(pool):
    """A picker that always took the first question of a group would pass every
    test above and drill a third of the pool."""
    seen: set[str] = set()
    for seed in range(200):
        seen.update(q.id for q in build_exam(pool, Rng(seed)))
    assert len(seen) == len(pool.questions), f"{len(seen)} of {len(pool.questions)} reachable"


def test_an_extra_pool_draws_fifty(pool):
    extra = parse_pool(synthetic_pool(prefix="E"))
    assert extra.exam_length == 50
    # The synthetic Extra pool has 35 groups and an Extra exam wants 50, which
    # check_pool warns about; the exam is still the right length.
    assert len(build_exam(extra, Rng(3))) == 50


# --- passing ----------------------------------------------------------------


def test_the_pass_mark_is_the_published_one(pool):
    """74%: 26 of 35 and 37 of 50. Rounding down would pass a candidate on 25."""
    assert pool.pass_mark == 26
    assert parse_pool(synthetic_pool(prefix="E")).pass_mark == 37


def test_grading_counts_only_the_right_answers(pool):
    exam = build_exam(pool, Rng(5))
    answers = [q.correct for q in exam]
    result = grade(pool, exam, answers)
    assert result["right"] == 35
    assert result["percent"] == 100.0
    assert result["passed"] is True


def test_the_pass_boundary_is_exact(pool):
    exam = build_exam(pool, Rng(5))
    for right, expected in ((26, True), (25, False)):
        answers = [
            question.correct if index < right else (question.correct + 1) % 4
            for index, question in enumerate(exam)
        ]
        assert grade(pool, exam, answers)["passed"] is expected, right


def test_an_unanswered_question_is_wrong_not_skipped(pool):
    """A VE session marks a blank wrong, and a practice test that ignored them
    would tell somebody they passed on twenty answers."""
    exam = build_exam(pool, Rng(5))
    answers: list[int | None] = [None] * len(exam)
    assert grade(pool, exam, answers)["right"] == 0
    assert grade(pool, exam, answers)["passed"] is False


def test_grading_a_mismatched_answer_list_is_an_error(pool):
    exam = build_exam(pool, Rng(5))
    with pytest.raises(ExamError, match="one answer per question"):
        grade(pool, exam, [0, 1])


# --- pools expire -----------------------------------------------------------


@pytest.mark.parametrize(
    ("today", "status"),
    [
        (date(2021, 6, 1), "future"),
        (date(2022, 7, 1), "current"),
        (date(2026, 6, 1), "current"),
        (date(2027, 1, 1), "expired"),
    ],
)
def test_a_pool_knows_whether_it_is_current(pool, today, status):
    """Studying an expired pool is studying the wrong questions, and nothing
    about the file says so on its face."""
    assert pool.status(today) == status


def test_a_pool_with_no_stated_years_says_unknown_rather_than_current():
    text = synthetic_pool().replace("2022-2026 AMATEUR", "AMATEUR")
    unknown = parse_pool(text)
    assert unknown.valid_from is None
    assert unknown.status(date(2026, 1, 1)) == "unknown"
    assert "no validity years found" in " ".join(check_pool(unknown))


def test_the_published_payload_carries_the_status(pool):
    payload = pool.to_dict(date(2027, 1, 1))
    assert payload["status"] == "expired"
    assert payload["pass_mark"] == 26
    assert payload["exam_length"] == 35
    assert len(payload["questions"]) == len(pool.questions)


# --- warnings that are not errors -------------------------------------------


def test_a_healthy_pool_has_nothing_to_warn_about(pool):
    assert check_pool(pool) == []


def test_too_few_groups_for_the_exam_is_a_warning_not_a_refusal():
    """A short pool is still worth studying; the operator should be told rather
    than handed nothing."""
    extra = parse_pool(synthetic_pool(prefix="E"))
    problems = " ".join(check_pool(extra))
    assert "35 question groups but an exam draws 50" in problems


def test_a_group_with_a_single_question_is_flagged():
    thin = parse_pool(synthetic_pool(per_group=1))
    assert "only one question" in " ".join(check_pool(thin))


def test_the_element_table_agrees_with_itself():
    """Exam length and group count are equal by construction -- one question per
    group is the rule, so a table where they differed would be incoherent."""
    for entry in ELEMENT_BY_ID.values():
        assert entry["questions"] in (35, 50)
        assert entry["prefix"] in ("T", "G", "E")


# --- and the browser agrees -------------------------------------------------


def test_the_browser_builds_the_same_exam():
    """web/lib/exam.js is a second implementation of the rule that matters.

    The panel draws exams itself so a candidate can practise on a train, which
    means the group-sampling rule exists twice. Same seed, same exam, or the
    browser is quietly running a different test from the one this file proves
    correct.
    """
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    parsed = parse_pool(synthetic_pool())
    payload = parsed.to_dict(date(2024, 1, 1))
    seeds = [0, 1, 7, 4242, 999983]

    with tempfile.TemporaryDirectory() as tmp:
        pool_path = Path(tmp) / "pool.json"
        pool_path.write_text(json.dumps(payload), encoding="utf-8")

        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{ readFileSync }} from "fs";
import {{ buildExam, grade }} from "{root / "web/lib/exam.js"}";

const pool = JSON.parse(readFileSync({str(pool_path)!r}, "utf8"));
const out = {{ exams: {{}}, grades: {{}} }};
for (const seed of {json.dumps(seeds)}) {{
  const exam = buildExam(pool, seed);
  out.exams[seed] = exam.map((q) => q.id);
  out.grades[seed] = grade(pool, exam, exam.map((q, i) => (i % 3 ? q.correct : null)));
}}
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )

        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        js = json.loads(result.stdout)

    for seed in seeds:
        want = [question.id for question in build_exam(parsed, Rng(seed))]
        assert js["exams"][str(seed)] == want, f"buildExam({seed})"

        exam = build_exam(parsed, Rng(seed))
        answers: list[int | None] = [
            None if index % 3 == 0 else question.correct for index, question in enumerate(exam)
        ]
        assert js["grades"][str(seed)] == grade(parsed, exam, answers), f"grade({seed})"


def test_the_browser_also_draws_one_question_per_group():
    """The property, checked on the JavaScript rather than inferred from the
    Python agreeing with it."""
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    payload = parse_pool(synthetic_pool()).to_dict(date(2024, 1, 1))

    with tempfile.TemporaryDirectory() as tmp:
        pool_path = Path(tmp) / "pool.json"
        pool_path.write_text(json.dumps(payload), encoding="utf-8")
        driver = Path(tmp) / "groups.mjs"
        driver.write_text(
            f"""
import {{ readFileSync }} from "fs";
import {{ buildExam }} from "{root / "web/lib/exam.js"}";
const pool = JSON.parse(readFileSync({str(pool_path)!r}, "utf8"));
const bad = [];
for (let seed = 0; seed < 40; seed += 1) {{
  const groups = buildExam(pool, seed).map((q) => q.group);
  if (new Set(groups).size !== groups.length) bad.push(seed);
}}
console.log(JSON.stringify(bad));
""",
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == [], "the browser drew two questions from one group"


# --- the pools that actually ship -------------------------------------------


def test_all_three_elements_ship():
    """Technician, General and Extra. A missing one is a candidate who cannot
    practise for the licence they are actually sitting."""
    from hammunition_hill.exam import shipped_pools

    assert set(shipped_pools()) == {"technician", "general", "extra"}


def test_the_extra_pool_is_the_fifty_question_one():
    """It arrives as five separate documents and is joined before parsing, so
    a part dropped on the floor is a real possibility. Fifty groups is what
    proves all of it is there."""
    from hammunition_hill.exam import shipped_pools

    payload = shipped_pools()["extra"]
    assert payload["exam_length"] == 50
    assert payload["pass_mark"] == 37
    assert len(payload["groups"]) == 50
    assert len(payload["questions"]) > 550


def test_the_shipped_pools_are_present_and_whole():
    """These are real questions somebody will study from, so they are checked
    rather than assumed. Every failure here is a person learning the wrong
    thing."""
    from hammunition_hill.exam import shipped_pools

    pools = shipped_pools()
    assert pools, "no question pools shipped with the package"
    for element_id, payload in pools.items():
        assert element_id in ELEMENT_BY_ID
        assert payload["shipped"] is True
        assert len(payload["questions"]) > 200, f"{element_id} is suspiciously small"
        assert payload["source"], f"{element_id} has no provenance recorded"


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_a_shipped_pool_can_build_an_exam(element_id):
    from hammunition_hill.exam import Pool, Question, shipped_pools

    payload = shipped_pools()[element_id]
    pool = Pool(
        element_id=payload["element_id"],
        name=payload["name"],
        valid_from=payload["valid_from"],
        valid_until=payload["valid_until"],
        questions=[
            Question(
                id=q["id"],
                group=q["group"],
                subelement=q["subelement"],
                text=q["text"],
                answers=tuple(q["answers"]),
                correct=q["correct"],
                reference=q["reference"],
            )
            for q in payload["questions"]
        ],
    )
    exam = build_exam(pool, Rng(11))
    assert len(exam) == payload["exam_length"]
    assert len({question.group for question in exam}) == len(exam)


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_every_shipped_question_is_answerable(element_id):
    """Four distinct answers, a key that points at one of them, and text.

    The failure this catches is a PDF extraction that dropped or merged a line:
    it parses, it looks fine in a list, and one question in four hundred is
    unanswerable.
    """
    from hammunition_hill.exam import shipped_pools

    for question in shipped_pools()[element_id]["questions"]:
        assert question["text"].strip(), question["id"]
        assert len(question["answers"]) == 4, question["id"]
        assert len(set(question["answers"])) == 4, f"{question['id']} repeats an answer"
        assert all(answer.strip() for answer in question["answers"]), question["id"]
        assert 0 <= question["correct"] <= 3, question["id"]


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_no_shipped_question_carries_page_furniture(element_id):
    """A page header swept into a question is what a bad extraction looks like,
    and it reads as a plausible sentence in the middle of an answer."""
    from hammunition_hill.exam import shipped_pools

    furniture = re.compile(r"Question Pool|Effective \d|Public Release|Page \d|Errata", re.I)
    for question in shipped_pools()[element_id]["questions"]:
        blob = question["text"] + " " + " ".join(question["answers"])
        assert not furniture.search(blob), f"{question['id']}: {blob[:120]}"


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_a_shipped_pool_has_the_groups_its_exam_needs(element_id):
    from hammunition_hill.exam import shipped_pools

    payload = shipped_pools()[element_id]
    assert len(payload["groups"]) >= payload["exam_length"]


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_a_shipped_pool_states_its_effective_dates(element_id):
    """The whole reason a stale pool is detectable rather than silent."""
    from hammunition_hill.exam import shipped_pools

    payload = shipped_pools()[element_id]
    assert payload["effective_from"], f"{element_id} has no effective_from"
    assert payload["effective_until"], f"{element_id} has no effective_until"
    assert payload["effective_from"] < payload["effective_until"]


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_the_shipped_pools_have_not_expired(element_id):
    """A deliberate tripwire.

    It fails when a shipped pool runs out, which is exactly when somebody needs
    to import the replacement. A test that goes red on a calendar date is
    usually a mistake; here it is the feature -- the alternative is shipping
    superseded questions and finding out from a candidate who failed.
    """
    from hammunition_hill.exam import shipped_pools

    payload = shipped_pools()[element_id]
    assert payload["status"] != "expired", (
        f"the shipped {element_id} pool expired on {payload['effective_until']} — "
        "download the current one and re-run hamhill exam-import"
    )


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_no_question_the_errata_deleted_survived(element_id):
    """The 2023-2027 General release deletes nine questions. A deleted question
    that stayed in would be studied and can never be asked -- and it was usually
    deleted for being wrong."""
    from hammunition_hill.exam import shipped_pools

    payload = shipped_pools()[element_id]
    present = {question["id"] for question in payload["questions"]}
    survived = sorted(set(payload["errata_deleted"]) & present)
    assert not survived, f"errata-deleted questions still present: {survived}"


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_every_gap_in_the_numbering_is_an_errata_deletion(element_id):
    """The other direction, and the one that catches a lost question.

    A question this parser dropped leaves a hole that looks exactly like a
    deletion. Reconciling the holes against the release's own errata is what
    tells the two apart -- and it is why the General pool's syllabus total of
    425 against 423 extracted is a stale heading rather than a bug.
    """
    from hammunition_hill.exam import shipped_pools

    payload = shipped_pools()[element_id]
    numbers: dict[str, list[int]] = {}
    for question in payload["questions"]:
        numbers.setdefault(question["group"], []).append(int(question["id"][3:]))
    gaps = {
        f"{group}{n:02d}"
        for group, seen in numbers.items()
        for n in range(1, max(seen) + 1)
        if n not in seen
    }
    unexplained = sorted(gaps - set(payload["errata_deleted"]))
    assert not unexplained, f"questions missing with no erratum to explain them: {unexplained}"


def test_the_pools_are_actually_committed():
    """They live under a path .gitignore excludes for a different reason.

    `data/` in .gitignore means the collector's snapshot directory. It also
    matched `src/hammunition_hill/data/`, so the pools were built, tested
    against, and left out of the commit -- every test above passing on files
    that existed only on the machine that made them.
    """
    import subprocess

    root = Path(__file__).resolve().parents[1]
    listed = subprocess.run(  # noqa: S603
        ["git", "ls-files", "src/hammunition_hill/data/exam/"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if listed.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = {line.rsplit("/", 1)[-1] for line in listed.stdout.split()}
    assert tracked >= {"technician.json", "general.json", "extra.json"}, (
        f"question pools are not tracked by git: {sorted(tracked)}"
    )


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_a_shipped_pool_has_every_field_the_code_publishes(element_id):
    """Vendored data drifts from the code that reads it, silently.

    The pools are generated by to_dict() and checked in. Add a field to
    to_dict(), forget to re-run the import, and every test that reads the pool
    still passes while the panel throws on the missing key at render time --
    which is exactly what happened when `subelements` was added.
    """
    from hammunition_hill.exam import shipped_pools

    reference_keys = set(parse_pool(synthetic_pool()).to_dict()) | {"shipped"}
    shipped = set(shipped_pools()[element_id])
    missing = sorted(reference_keys - shipped)
    assert not missing, (
        f"the shipped {element_id} pool is missing {missing} — it was built by an "
        "older version of to_dict(); re-run hamhill exam-import"
    )


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_the_subelement_weights_add_up_to_the_exam(element_id):
    """ "[6 Exam Questions - 6 Groups]" per subelement, summing to 35 or 50.

    This is what makes a section test the right size, so if the sum is wrong
    either the parse dropped a heading or the release contradicts itself.
    """
    from hammunition_hill.exam import shipped_pools

    payload = shipped_pools()[element_id]
    weights = payload["subelement_weights"]
    assert weights, f"{element_id} states no subelement weights"
    assert sum(weights.values()) == payload["exam_length"]


@pytest.mark.parametrize("element_id", ["technician", "general", "extra"])
def test_a_section_test_is_the_size_the_release_says(element_id):
    from hammunition_hill.exam import Pool, Question, section_exam, shipped_pools

    payload = shipped_pools()[element_id]
    pool = Pool(
        element_id=payload["element_id"],
        name=payload["name"],
        valid_from=payload["valid_from"],
        valid_until=payload["valid_until"],
        questions=[
            Question(
                id=q["id"],
                group=q["group"],
                subelement=q["subelement"],
                text=q["text"],
                answers=tuple(q["answers"]),
                correct=q["correct"],
                reference=q["reference"],
            )
            for q in payload["questions"]
        ],
        subelement_weights=payload["subelement_weights"],
    )
    total = 0
    for subelement in payload["subelements"]:
        section = section_exam(pool, subelement, Rng(4))
        assert len(section) == payload["subelement_weights"][subelement], subelement
        assert len({q.group for q in section}) == len(section), f"{subelement} repeated a group"
        assert all(q.subelement == subelement for q in section)
        total += len(section)
    # Every section back to back is one exam's worth, which is what "section"
    # means here rather than "a quiz about that topic".
    assert total == payload["exam_length"]


def test_the_shipped_pools_are_readable_json():
    """The vendored pools are review material, so they are formatted for review.

    They shipped minified: three files of one line each, 130 kB wide. Nothing
    about that is wrong at runtime -- the panel is served the collector's
    snapshot, not these files, so the extra bytes never cross a wire -- but a
    pool is a claim about what the official release says, and a claim nobody can
    read is a claim nobody can check. It also makes the diff for a pool update
    a single changed line, which is the one moment the diff matters most.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src/hammunition_hill/data/exam"
    files = sorted(root.glob("*.json"))
    assert files, "no shipped pools found"
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert len(lines) > 100, f"{path.name} is {len(lines)} lines; it has been minified"
        assert lines[0] == "{", f"{path.name} does not start on its own line"
        assert any(line.startswith('      "id":') for line in lines), (
            f"{path.name} is not indented per question"
        )
        # Real characters, not escapes: an en dash written – defeats the
        # point of formatting these for a human to check against the release.
        assert "\\u" not in text, f"{path.name} contains escaped non-ASCII"
        json.loads(text)

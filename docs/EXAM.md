# Licence exam practice

Study mode and full practice exams from the **official question pools**, which
ship with this project.

| Element | Pool | Questions | Exam | Pass |
|---|---|---|---|---|
| 2 — Technician | 2026–2030 | 409 | 35 | 26 |
| 3 — General | 2023–2027 | 423 | 35 | 26 |
| 4 — Amateur Extra | 2024–2028 | 599 | 50 | 37 |

Tier 0. The pool is on disk; everything after that is arithmetic in the browser,
so it works on a train with the phone in aeroplane mode.

## The rule that makes a practice exam real

**One question from each group.** A Technician exam is 35 questions drawn from
35 groups, one apiece; General is the same shape; Extra is 50 from 50.

It is *not* a random sample of the pool, and this is the thing a
plausible-looking implementation gets wrong. A uniform sample over 409 questions
would over-weight whichever groups happen to carry more of them and skip others
entirely — easier or harder by luck, and never covering the syllabus the way the
real exam does.

Both the Python and the JavaScript build exams this way, and a test runs the
browser copy under node and demands the identical exam for the same seed.

## Where the questions come from

The releases published by NCVEC, available from
[arrl.org/question-pools](https://www.arrl.org/question-pools). They are parsed
once by `hamhill exam-import` and checked in, each recording its own provenance
— which release, which errata, and the date.

Nothing is invented. That is worth stating plainly: a fabricated practice
question is worse than no practice at all, because an operator studies it,
believes it, and is then confidently wrong in the exam room about the one thing
they were sure of.

## Pools expire, and this one says so

Every release states the window it is valid for, and studying an expired pool is
studying the wrong questions — the failure is quiet, because the questions look
completely normal.

So the effective dates are parsed out of the release (`Effective 7/01/2026 –
6/30/2030`), carried through, and shown by the panel. An expired pool gets a red
banner telling you to import the current one, and **a test fails when a shipped
pool runs out.** A test that goes red on a calendar date is usually a mistake;
here it is the point.

## Updating a pool

```
hamhill exam-import --file "2030-2034 Technician Pool.pdf"
```

PDF because that is how the pools are actually published now. Reading one needs
an optional extra:

```
pip install 'hammunition-hill[exam]'
```

If a pool arrives split across several documents, repeat `--file` in order and
they are joined before parsing:

```
hamhill exam-import --file part1.pdf --file part2.pdf --file part3.pdf
```

An imported pool is written to the data directory and takes precedence over the
shipped one. Upgrading the package refreshes what it shipped and never
overwrites what you imported.

### Updating Part 97

The CFR is revised annually. The shipped copy says which edition it is, and the
panel prints that under every quote.

```bash
hamhill part97-import --file CFR-2025-title47-vol5-part97.pdf
```

Volumes are published at [govinfo](https://www.govinfo.gov/app/collection/cfr) —
title 47, volume 5. Like the pools, the result is checked in, so this is a
maintainer's command rather than something an operator has to run.

## What the importer checks

Parsing a pool that "looks fine" is not the same as parsing it correctly, and
the failure mode is a question quietly missing or an answer truncated. So:

- **Every question has four distinct answers and a key naming one of them.** A
  three-answer question would be unanswerable and nothing downstream would
  notice.
- **No duplicate ids**, which is how the Extra release's habit of restating
  corrected questions in the errata block was caught. Those restatements are
  header lines with no text and no answers; a parser reading from the top
  swallows them as questions.
- **The errata is reconciled against the pool.** Every question the release says
  it deleted must be gone, and every gap in a group's numbering must be a
  deletion the errata accounts for. That second direction is the one that
  catches a question *this parser* lost, because a hole looks identical either
  way.

That reconciliation is why the General pool's syllabus heading of 425 against
423 extracted is a stale heading rather than a bug: all nine errata deletions
are accounted for, and every numbering gap is one of them.

## Five ways to work

People study differently, and the pool supports all of it. Every mode except
`exam` and `review` can be narrowed to one subelement.

**read** — the syllabus straight through, in pool order, with the answer showing
and the rule reference under it. Some people learn by reading; a panel that only
ever asked questions at random would not let them.

**study** — one at a time, hidden until you answer. A group you get wrong is
revisited sooner; a group you get right leaves the list. Not *only* mistakes,
though — drilling nothing else means never seeing the rest of the syllabus
again.

**section** — a test over one subelement, **the size that subelement contributes
to the real exam**. The release states it: `SUBELEMENT T1 - COMMISSION'S RULES
[6 Exam Questions - 6 Groups]`. Six questions from six T1 groups is exactly the
T1 part of a Technician exam, so a section test is a slice of the real thing
rather than a quiz that happens to be about the same topic. Sit all ten sections
back to back and you have sat one exam's worth — which is asserted in the tests.

**exam** — the full 35 or 50, built by the rule above, scored with every missed
question listed. A blank counts wrong, because a VE session counts it wrong.

**review** — everything you have got wrong this session, in one go.

## Why an answer is right

For a rules question, "why" is a citation — so the rule is shown.

192 of the 1431 questions carry a Part 97 reference, and 47 CFR Part 97 ships
with the project. Answer one of them and the section it comes from appears
underneath, in full, exactly as the FCC published it:

> **T1D01** — With which countries are FCC-licensed amateur radio stations
> prohibited from exchanging communications?
> **Rule reference: §97.111(a)(1)**
>
> §97.111 *Authorized transmissions.*
> (a) An amateur station may transmit the following types of two-way
> communications:
> (1) Transmissions necessary to exchange messages with other stations in the
> amateur service, **except those in any country whose administration has
> notified the ITU that it objects to such communications.** …

The answer is not paraphrased into an explanation; the regulation simply says
it. **The whole section is shown, not the cited paragraph.** Quoting one
paragraph out of its section is how a rule gets misread — the exceptions
usually live two paragraphs further down — so the citation says which part the
question came from and the section is there to be read around it.

Two questions cite Part 1 rather than Part 97 (§1.931 and §1.1307). They get the
citation and a note saying the text is not bundled, rather than nothing.

### The other 1240 questions

There is no written explanation of why a *technical* answer is right, and there
will not be one this project invented.

Writing 1431 explanations that nobody checked would be generating study material
at scale, and a wrong explanation is worse than no explanation: it teaches a
mental model that then fails on every related question, not just the one. That
is the same reason the questions themselves are the official ones and nothing
else.

Explanations for the technical questions would be a written contribution with
an author's name on it, reviewed like any other, rather than something
generated.

## What it does not do

- **No progress across sessions.** The score is for the session you are in.
  Storing a study history would mean storing data about you, which this project
  does not do.
- **No explanations for the technical questions.** The rules questions cite
  Part 97 and Part 97 is shipped, so those explain themselves. Ohm's law does
  not come with a citation.
- **No Canadian, UK or other syllabuses.** The parser is written for the NCVEC
  format. Another country's pool is a data contribution and probably a second
  parser.
- **It is not a VE session.** Passing here is encouraging and is not a licence.

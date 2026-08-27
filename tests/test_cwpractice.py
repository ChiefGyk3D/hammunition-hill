# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The CW curriculum: that it is a curriculum, and that the browser agrees.

Two things need proving here that a reference table does not need. The first is
that everything the trainer generates is *sendable* -- a drill that emits a
character with no Morse encoding sends silence and calls it practice. The second
is that the browser generates the identical thing, since the generators are
implemented twice and a second implementation drifts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import pytest

from hammunition_hill import morse
from hammunition_hill.cwpractice import (
    ANTENNAS,
    FIRST_LESSON,
    KOCH_ORDER,
    NAMES,
    PHONETICS,
    QTHS,
    RIGS,
    SCRIPTS,
    WEATHER,
    Rng,
    alphabet_for,
    callsign,
    callsigns,
    entity_for,
    groups,
    lessons,
    qso,
    quiz_pairs,
    quiz_question,
    reference,
)

POOL = reference()["prefixes"]
NAMES_ONLY = [entry["prefix"] for entry in POOL]


# --- the generator ----------------------------------------------------------


def test_the_same_seed_gives_the_same_sequence():
    assert [Rng(99).next() for _ in range(1)] == [Rng(99).next() for _ in range(1)]
    a = [Rng(2024).next() for _ in range(5)]
    b = Rng(2024)
    assert a[0] == b.next()


def test_values_stay_in_range():
    rng = Rng(7)
    for _ in range(5000):
        value = rng.next()
        assert 0.0 <= value < 1.0


def test_different_seeds_diverge():
    """Not a strong claim, but a generator that ignored its seed would pass
    every other test in this file."""
    first = [Rng(1).next() for _ in range(10)]
    second = [Rng(2).next() for _ in range(10)]
    assert first != second


def test_below_stays_in_range_and_uses_the_whole_range():
    rng = Rng(31337)
    seen = Counter(rng.below(6) for _ in range(6000))
    assert set(seen) == set(range(6)), f"some values never came up: {sorted(seen)}"
    assert all(0 < count for count in seen.values())


def test_the_state_wraps_rather_than_growing():
    """32-bit, because the JavaScript side has no choice about that."""
    rng = Rng(0xFFFFFFFF)
    for _ in range(1000):
        rng.next()
    assert 0 <= rng._a <= 0xFFFFFFFF


# --- the Koch order and its lesson plan -------------------------------------


def test_the_koch_order_is_a_permutation_of_sendable_characters():
    assert len(set(KOCH_ORDER)) == len(KOCH_ORDER), "a character appears twice"
    for char in KOCH_ORDER:
        assert char in morse.ENCODE, f"{char!r} is in the Koch order but has no Morse code"


def test_the_koch_order_covers_the_whole_alphabet_and_digits():
    assert set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") <= set(KOCH_ORDER)


def test_the_lesson_plan_adds_one_character_at_a_time():
    plan = lessons()
    assert plan[0]["lesson"] == 1
    assert plan[0]["alphabet"] == KOCH_ORDER[:FIRST_LESSON]
    assert len(plan) == len(KOCH_ORDER) - FIRST_LESSON + 1

    for earlier, later in zip(plan, plan[1:], strict=False):
        assert later["lesson"] == earlier["lesson"] + 1
        assert len(later["alphabet"]) == len(earlier["alphabet"]) + 1
        assert later["alphabet"].startswith(earlier["alphabet"]), "a lesson dropped a character"
        assert later["adds"] == later["alphabet"][-1]

    assert plan[-1]["alphabet"] == KOCH_ORDER


def test_alphabet_for_clamps_at_both_ends():
    assert alphabet_for(1) == KOCH_ORDER[:FIRST_LESSON]
    assert alphabet_for(0) == KOCH_ORDER[:FIRST_LESSON]
    assert alphabet_for(-5) == KOCH_ORDER[:FIRST_LESSON]
    assert alphabet_for(10_000) == KOCH_ORDER
    assert alphabet_for(3) == KOCH_ORDER[: FIRST_LESSON + 2]


def test_every_lesson_alphabet_agrees_with_alphabet_for():
    for entry in lessons():
        assert alphabet_for(entry["lesson"]) == entry["alphabet"]


# --- groups -----------------------------------------------------------------


def test_groups_have_the_shape_they_claim():
    text = groups(Rng(5), "KMRS", count=7, size=4)
    parts = text.split(" ")
    assert len(parts) == 7
    assert all(len(part) == 4 for part in parts)


def test_groups_use_only_the_lesson_alphabet():
    alphabet = alphabet_for(6)
    text = groups(Rng(11), alphabet, count=50, size=5)
    assert set(text.replace(" ", "")) <= set(alphabet)


def test_groups_with_no_alphabet_are_empty_rather_than_an_error():
    assert groups(Rng(1), "") == ""


def test_groups_use_the_whole_alphabet_given_enough_of_them():
    """A generator biased to the first character would still pass the tests above."""
    alphabet = alphabet_for(8)
    text = groups(Rng(4), alphabet, count=400, size=5)
    assert set(text.replace(" ", "")) == set(alphabet)


# --- callsigns --------------------------------------------------------------

CALL_SHAPE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z]{1,3}$")


def test_generated_callsigns_look_like_callsigns():
    rng = Rng(2718)
    for _ in range(2000):
        call = callsign(rng, NAMES_ONLY)
        assert CALL_SHAPE.match(call), call


def test_every_generated_callsign_starts_with_a_real_prefix():
    rng = Rng(1618)
    for _ in range(2000):
        call = callsign(rng, NAMES_ONLY)
        assert entity_for(call, POOL), f"{call} resolves to no entity"


def test_suffix_lengths_follow_the_declared_weights():
    """The weights exist to make short contest-style calls the common case.

    Without this, a bug that always returned three letters would still produce
    valid callsigns and nothing would notice the trainer had got easier.
    """
    rng = Rng(90210)
    lengths = Counter()
    for _ in range(20_000):
        call = callsign(rng, ["K"])
        lengths[len(call) - 2] += 1  # "K" plus one call-area digit
    total = sum(lengths.values())
    assert lengths[1] / total == pytest.approx(0.15, abs=0.02)
    assert lengths[2] / total == pytest.approx(0.50, abs=0.02)
    assert lengths[3] / total == pytest.approx(0.35, abs=0.02)


def test_a_prefix_ending_in_a_digit_takes_no_call_area():
    """KH6 calls are KH6XY, not KH6-something-XY."""
    rng = Rng(6)
    for _ in range(300):
        call = callsign(rng, ["KH6"])
        assert call.startswith("KH6")
        assert call[3].isalpha(), call


def test_an_empty_prefix_pool_gives_an_empty_callsign():
    assert callsign(Rng(1), []) == ""


def test_callsigns_returns_the_number_asked_for():
    assert len(callsigns(Rng(3), NAMES_ONLY, count=9)) == 9


def test_entity_lookup_prefers_the_longest_prefix():
    """K and KH6 are both in the table; a Hawaiian call is not the mainland."""
    pool = [{"prefix": "K", "entity": "United States"}, {"prefix": "KH6", "entity": "Hawaii"}]
    assert entity_for("KH6ABC", pool) == "Hawaii"
    assert entity_for("K1ABC", pool) == "United States"
    assert entity_for("ZZ9ZZZ", pool) == ""


def test_the_prefix_pool_is_not_empty_and_has_no_blank_entries():
    assert len(POOL) > 100
    for entry in POOL:
        assert entry["prefix"] and entry["entity"]


# --- the QSO simulator ------------------------------------------------------


@pytest.mark.parametrize("style", sorted(SCRIPTS))
def test_a_qso_fills_in_every_placeholder(style):
    lines = qso(Rng(2020), NAMES_ONLY, style=style, my_call="K7ABC", my_name="ALEX")
    for line in lines:
        assert "{" not in line.text and "}" not in line.text, line.text
        assert line.text.strip()
        assert line.speaker in {"me", "dx"}


@pytest.mark.parametrize("style", sorted(SCRIPTS))
def test_a_qso_uses_the_operators_own_callsign(style):
    lines = qso(Rng(11), NAMES_ONLY, style=style, my_call="K7ABC")
    assert any("K7ABC" in line.text for line in lines)


@pytest.mark.parametrize("style", sorted(SCRIPTS))
def test_both_sides_transmit(style):
    """A one-sided script would not be a QSO, and the panel plays only `dx`."""
    speakers = {line.speaker for line in qso(Rng(8), NAMES_ONLY, style=style)}
    assert speakers == {"me", "dx"}


def test_the_dx_station_keeps_one_callsign_throughout():
    """Generating a fresh callsign per line would be a different station each time."""
    lines = qso(Rng(404), NAMES_ONLY, style="ragchew", my_call="K7ABC")
    calls = {word for line in lines for word in line.text.split() if CALL_SHAPE.match(word)}
    assert calls - {"K7ABC"}, "no DX callsign appeared at all"
    assert len(calls - {"K7ABC"}) == 1, f"more than one DX station in one QSO: {calls}"


def test_a_ragchew_carries_the_details_a_ragchew_carries():
    lines = qso(Rng(77), NAMES_ONLY, style="ragchew", my_name="SAM")
    text = " ".join(line.text for line in lines)
    assert any(f" {name} " in f" {text} " for name in NAMES)
    assert any(qth in text for qth in QTHS)
    assert any(rig in text for rig in RIGS)
    assert any(antenna in text for antenna in ANTENNAS)
    assert any(weather in text for weather in WEATHER)
    assert "SAM" in text


def test_a_contest_exchange_carries_a_serial_and_a_report():
    lines = qso(Rng(78), NAMES_ONLY, style="contest")
    text = " ".join(line.text for line in lines)
    assert "5NN" in text
    assert re.search(r"5NN \d{3}", text), text


def test_an_unknown_style_is_an_error_rather_than_an_empty_qso():
    with pytest.raises(ValueError, match="unknown QSO style"):
        qso(Rng(1), NAMES_ONLY, style="chatting")


# --- the quizzes ------------------------------------------------------------


def test_the_phonetic_alphabet_is_complete_and_unambiguous():
    chars = [row["char"] for row in PHONETICS]
    assert set(chars) == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    assert len(chars) == len(set(chars))
    words = [row["word"] for row in PHONETICS]
    assert len(words) == len(set(words)), "two characters share a word"
    for word, char in zip(words, chars, strict=True):
        if char.isalpha():
            assert word[0].upper() == char, f"{word} does not start with {char}"


@pytest.mark.parametrize("bank", sorted(quiz_pairs()))
def test_every_quiz_bank_is_usable(bank):
    pairs = quiz_pairs()[bank]
    assert len(pairs) >= 4, "a bank smaller than the number of choices"
    for pair in pairs:
        assert pair["prompt"] and pair["answer"]


@pytest.mark.parametrize("bank", sorted(quiz_pairs()))
def test_a_quiz_question_is_answerable(bank):
    pairs = quiz_pairs()[bank]
    rng = Rng(1234)
    for _ in range(300):
        question = quiz_question(rng, pairs)
        assert question["answer"] in question["options"]
        assert len(question["options"]) == 4
        assert len(set(question["options"])) == 4, "the same wrong answer twice"
        assert {"prompt": question["prompt"], "answer": question["answer"]} in pairs


def test_the_right_answer_is_not_always_in_the_same_place():
    """Without the shuffle it would always be first, and the quiz would be free."""
    pairs = quiz_pairs()["phonetics"]
    rng = Rng(55)
    positions = Counter()
    for _ in range(2000):
        question = quiz_question(rng, pairs)
        positions[question["options"].index(question["answer"])] += 1
    assert set(positions) == {0, 1, 2, 3}
    for count in positions.values():
        assert count / 2000 == pytest.approx(0.25, abs=0.03)


def test_a_bank_too_small_for_four_choices_terminates():
    """The loop that fills in wrong answers must be bounded, not hopeful."""
    tiny = [{"prompt": "A", "answer": "Alfa"}, {"prompt": "B", "answer": "Bravo"}]
    question = quiz_question(Rng(1), tiny)
    assert question["answer"] in question["options"]
    assert len(question["options"]) == 2


# --- everything generated must actually be sendable -------------------------


def test_every_character_the_trainer_can_send_has_a_morse_code():
    """The one that matters.

    A drill that emits a character with no encoding sends silence where a
    character should be, and the student copies a gap. This walks everything the
    generators can produce -- groups at the full alphabet, two thousand
    callsigns, both QSO scripts with every field filled -- and checks each
    character against the encode table.
    """
    sendable = set(morse.ENCODE) | {" "}
    rng = Rng(31415)

    text = groups(rng, KOCH_ORDER, count=200, size=5)
    text += " " + " ".join(callsigns(rng, NAMES_ONLY, count=2000))
    for style in SCRIPTS:
        for _ in range(200):
            for line in qso(rng, NAMES_ONLY, style=style, my_call="K7ABC", my_name="ALEX"):
                text += " " + line.text

    unsendable = sorted(set(text) - sendable)
    assert not unsendable, f"the trainer can send characters with no Morse code: {unsendable}"


def test_the_static_word_lists_are_sendable_too():
    """The lists are data and a new entry is one keystroke from an accent."""
    sendable = set(morse.ENCODE) | {" "}
    for label, words in (
        ("names", NAMES),
        ("QTHs", QTHS),
        ("rigs", RIGS),
        ("antennas", ANTENNAS),
        ("weather", WEATHER),
    ):
        for word in words:
            bad = sorted(set(word) - sendable)
            assert not bad, f"{label}: {word!r} contains unsendable {bad}"


def test_encoding_a_whole_qso_round_trips():
    """Not just per-character: the decoder must give the text back."""
    for style in SCRIPTS:
        for line in qso(Rng(9), NAMES_ONLY, style=style, my_call="K7ABC"):
            assert morse.decode(morse.encode(line.text)) == line.text


# --- the published payload --------------------------------------------------


def test_the_reference_payload_is_json_and_has_what_the_panel_reads():
    payload = reference()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped == payload
    for key in (
        "koch_order",
        "first_lesson",
        "lessons",
        "phonetics",
        "names",
        "qths",
        "rigs",
        "antennas",
        "weather",
        "scripts",
        "quizzes",
        "prefixes",
    ):
        assert payload[key], f"reference() published nothing under {key!r}"


def test_the_published_scripts_match_the_module():
    published = reference()["scripts"]
    assert set(published) == set(SCRIPTS)
    for style, script in SCRIPTS.items():
        assert published[style] == [{"speaker": s, "text": t} for s, t in script]


# --- and the browser agrees -------------------------------------------------


def test_the_browser_generators_match_this_module():
    """web/lib/cwpractice.js is a second implementation, and those drift.

    Everything above tests the Python. This runs the JavaScript the panel
    actually loads, over the same seeds and the same published payload, and
    demands identical output -- not merely output of the right shape. Skipped
    rather than failed where node is absent, because a contributor without it
    should still be able to run the suite.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")

    root = Path(__file__).resolve().parents[1]
    payload = reference()
    seeds = [0, 1, 42, 12345, 999983, 4294967295]

    with tempfile.TemporaryDirectory() as tmp:
        ref_path = Path(tmp) / "practice.json"
        ref_path.write_text(json.dumps(payload), encoding="utf-8")

        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{ readFileSync }} from "fs";
import {{
  alphabetFor, callsign, callsigns, entityFor, groups, qso, quizQuestion, rng,
}} from "{root / "web/lib/cwpractice.js"}";

const p = JSON.parse(readFileSync({str(ref_path)!r}, "utf8"));
const prefixes = p.prefixes.map((e) => e.prefix);
const out = {{
  raw: {{}}, groups: {{}}, calls: {{}}, qso: {{}},
  quiz: {{}}, alphabet: {{}}, entity: {{}},
}};

for (const seed of {json.dumps(seeds)}) {{
  const r = rng(seed);
  out.raw[seed] = Array.from({{ length: 8 }}, () => r());
  out.groups[seed] = groups(rng(seed), alphabetFor(6, p.koch_order, p.first_lesson));
  out.calls[seed] = callsigns(rng(seed), prefixes, {{ count: 60 }});
  out.qso[seed] = {{}};
  for (const style of Object.keys(p.scripts)) {{
    out.qso[seed][style] = qso(rng(seed), prefixes, p, {{
      style, myCall: "K7ABC", myName: "ALEX",
    }});
  }}
  out.quiz[seed] = {{}};
  for (const bank of Object.keys(p.quizzes)) {{
    out.quiz[seed][bank] = quizQuestion(rng(seed), p.quizzes[bank]);
  }}
}}
for (const n of [1, 2, 5, 20, 500, 0, -3]) {{
  out.alphabet[n] = alphabetFor(n, p.koch_order, p.first_lesson);
}}
for (const call of ["KH6ABC", "K1AW", "DL1XY", "ZZ9ZZZ", "9A2AA"]) {{
  out.entity[call] = entityFor(call, p.prefixes);
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
        key = str(seed)
        rng_py = Rng(seed)
        assert js["raw"][key] == [rng_py.next() for _ in range(8)], f"rng({seed})"

        assert js["groups"][key] == groups(Rng(seed), alphabet_for(6)), f"groups({seed})"
        assert js["calls"][key] == callsigns(Rng(seed), NAMES_ONLY, count=60), f"callsigns({seed})"

        for style in SCRIPTS:
            want = [
                {"speaker": line.speaker, "text": line.text}
                for line in qso(Rng(seed), NAMES_ONLY, style=style, my_call="K7ABC", my_name="ALEX")
            ]
            assert js["qso"][key][style] == want, f"qso({seed}, {style})"

        banks = quiz_pairs()
        for bank, pairs in banks.items():
            assert js["quiz"][key][bank] == quiz_question(Rng(seed), pairs), f"quiz({seed}, {bank})"

    for lesson in (1, 2, 5, 20, 500, 0, -3):
        assert js["alphabet"][str(lesson)] == alphabet_for(lesson), f"alphabetFor({lesson})"

    for call in ("KH6ABC", "K1AW", "DL1XY", "ZZ9ZZZ", "9A2AA"):
        assert js["entity"][call] == entity_for(call, POOL), f"entityFor({call})"

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Morse tables, timing and translation.

A Morse table is exactly the kind of data where a single wrong character is
invisible on inspection and obvious on the air. So it is checked against
independent properties -- the standard's own structure, the PARIS timing
definition, round trips -- rather than by reading it back.
"""

from __future__ import annotations

import pytest

from hammunition_hill.morse import (
    ABBREVIATIONS,
    CUT_NUMBERS,
    DECODE,
    DIGITS,
    ENCODE,
    EXTENDED,
    LETTERS,
    PROSIGNS,
    PUNCTUATION,
    Q_CODES,
    SYNONYMS,
    decode,
    encode,
    reference,
    timing,
    word_duration_ms,
)


# --- the table itself -----------------------------------------------------
def test_all_twenty_six_letters():
    assert set(LETTERS) == set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def test_all_ten_digits():
    assert set(DIGITS) == set("0123456789")


def test_digits_are_all_five_elements():
    """A structural property of the standard, not an opinion about the table."""
    for digit, code in DIGITS.items():
        assert len(code) == 5, f"{digit} is {code}"


def test_digits_follow_the_standard_progression():
    """1-5 add dahs from the right, 6-0 add dits. Checks the whole run at once.

    1 .----   2 ..---   3 ...--   4 ....-   5 .....
    6 -....   7 --...   8 ---..   9 ----.   0 -----
    """
    for n in range(1, 6):
        assert DIGITS[str(n)] == "." * n + "-" * (5 - n)
    for n in range(6, 10):
        assert DIGITS[str(n)] == "-" * (n - 5) + "." * (10 - n)
    assert DIGITS["0"] == "-----"


@pytest.mark.parametrize(
    "char,code",
    [
        ("E", "."),
        ("T", "-"),  # the two shortest, by design
        ("A", ".-"),
        ("N", "-."),
        ("S", "..."),
        ("O", "---"),  # the ones everyone knows from SOS
        ("H", "...."),
        ("5", "....."),
        ("Q", "--.-"),
        ("Z", "--.."),  # commonly confused pair
        ("F", "..-."),
        ("L", ".-.."),  # the other commonly confused pair
    ],
)
def test_known_characters(char, code):
    assert LETTERS.get(char) or DIGITS.get(char) == code or LETTERS[char] == code


def test_sos_is_the_famous_pattern():
    assert encode("SOS") == "... --- ..."


def test_every_code_uses_only_dits_and_dahs():
    for char, code in ENCODE.items():
        assert set(code) <= {".", "-"}, f"{char} contains something else: {code!r}"
        assert code, f"{char} has an empty code"


def test_no_letter_or_digit_shares_a_code():
    """Ambiguity inside the alphanumerics would make decoding guesswork."""
    alnum = {**LETTERS, **DIGITS}
    seen: dict[str, str] = {}
    for char, code in alnum.items():
        assert code not in seen, f"{char} and {seen[code]} are both {code}"
        seen[code] = char


def test_the_known_prosign_collisions_are_present_and_intentional():
    """AR/+, AS/&, BT/= and KN/( are one sound each. Not a bug to fix.

    Morse has no punctuation namespace. Pinning these means a future "cleanup"
    that renamed one of them would fail here rather than silently changing what
    the decoder prints.
    """
    for sign, punctuation in (("AR", "+"), ("AS", "&"), ("BT", "="), ("KN", "(")):
        prosign = next(p for p in PROSIGNS if p["sign"] == sign)
        assert prosign["code"] == PUNCTUATION[punctuation]
        assert prosign["also"] == punctuation


def test_decode_prefers_the_punctuation_reading_of_a_collision():
    """A decoder should print `+`, not `AR`. The chart carries the other reading."""
    assert decode(".-.-.") == "+"
    assert decode("-...-") == "="


def test_extended_characters_do_not_collide_with_letters():
    """Ö is ---. and O is ---. A collision here would corrupt English text."""
    for char, code in EXTENDED.items():
        clash = [c for c, k in LETTERS.items() if k == code]
        assert not clash, f"{char} ({code}) collides with {clash}"


# --- round trips ----------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["CQ CQ DE W1AW", "HELLO WORLD", "73", "SOS", "TEST 599 TU", "A", "PARIS"],
)
def test_encode_decode_round_trip(text):
    assert decode(encode(text)) == text


def test_every_character_round_trips():
    """One wrong entry in either direction shows up here rather than on the air.

    Documented synonyms are excluded: Á and Å are genuinely the same pattern in
    international Morse, so a decoder cannot recover which was sent and no test
    should pretend otherwise. Pinned separately below rather than waved away.
    """
    ambiguous = {char for group in SYNONYMS for char in group}
    for char in ENCODE:
        if char in ambiguous:
            continue
        assert decode(encode(char)) == char, char


def test_the_one_genuine_synonym_is_the_one_we_know_about():
    """A second collision appearing here would be a table error, not Morse.

    This is the whole value of listing them: the round-trip test above skips
    exactly this set, so an accidental duplicate slipped into the table would
    otherwise be skipped too.
    """
    by_code: dict[str, list[str]] = {}
    for char, code in ENCODE.items():
        by_code.setdefault(code, []).append(char)

    collisions = {code: chars for code, chars in by_code.items() if len(chars) > 1}
    assert collisions == {".--.-": ["Á", "Å"]}, collisions

    for group in SYNONYMS:
        codes = {ENCODE[char] for char in group}
        assert len(codes) == 1, f"{group} are listed as synonyms but differ"


def test_words_are_separated():
    assert encode("A B") == ".- / -..."
    assert decode(".- / -...") == "A B"


def test_lowercase_is_accepted():
    """Morse has no case. Refusing lowercase would just annoy the user."""
    assert encode("cq") == encode("CQ")


def test_unknown_characters_are_dropped_by_default():
    assert encode("A~B") == ".- -..."


def test_unknown_characters_can_be_marked():
    """The panel marks them, so a user sees that something did not translate."""
    assert "?" in encode("A~B", unknown="?")


def test_decode_accepts_typographic_characters():
    """A chart copied from a book or a web page rarely uses ASCII."""
    assert decode("·-·-·-") == "."
    assert decode("... —— ...".replace("——", "---")) == "SOS"
    assert decode("•-") == "A"


def test_decode_accepts_a_double_space_as_a_word_gap():
    assert decode("...  ---") == "S O"


def test_decode_marks_what_it_cannot_read():
    assert decode("........................") == "?"


def test_empty_input_is_empty_output():
    assert encode("") == ""
    assert decode("") == ""
    assert encode("   ") == ""


# --- timing ---------------------------------------------------------------
def test_dit_length_follows_the_standard():
    """1200/WPM milliseconds. 20 WPM is 60 ms, which is the number to know."""
    assert timing(20).dit_ms == pytest.approx(60.0)
    assert timing(5).dit_ms == pytest.approx(240.0)
    assert timing(40).dit_ms == pytest.approx(30.0)


def test_element_ratios():
    plan = timing(20)
    assert plan.dah_ms == pytest.approx(plan.dit_ms * 3)
    assert plan.inter_character_ms == pytest.approx(plan.dit_ms * 3)
    assert plan.inter_word_ms == pytest.approx(plan.dit_ms * 7)


@pytest.mark.parametrize("wpm", [5, 13, 20, 25, 35])
def test_paris_takes_exactly_one_minute_at_n_wpm(wpm):
    """The definition of WPM, used as the test of the timing.

    "PARIS " is 50 dit units. Sending it `wpm` times must take 60 seconds, or
    the speed does not mean what it says. Measured over repetitions so the
    trailing word gap is counted the way the standard counts it.
    """
    plan = timing(wpm)
    text = " ".join(["PARIS"] * wpm)
    # word_duration_ms omits the gap after the final word; add it back.
    total = word_duration_ms(text, plan) + plan.inter_word_ms
    assert total == pytest.approx(60_000, rel=0.001)


def test_farnsworth_keeps_characters_fast_and_stretches_the_gaps():
    """The point of Farnsworth: learn the rhythm of a letter, not a slow version."""
    plan = timing(20, effective_wpm=10)
    straight = timing(20)

    assert plan.dit_ms == straight.dit_ms  # characters unchanged
    assert plan.inter_character_ms > straight.inter_character_ms
    assert plan.inter_word_ms > straight.inter_word_ms
    assert plan.farnsworth is True


def test_farnsworth_gaps_keep_the_three_to_seven_ratio():
    """Stretched gaps must still sound like Morse, not like arbitrary pauses."""
    plan = timing(20, effective_wpm=10)
    assert plan.inter_word_ms / plan.inter_character_ms == pytest.approx(7 / 3)


def test_farnsworth_at_equal_speeds_is_plain_timing():
    assert timing(18, effective_wpm=18).to_dict() == timing(18).to_dict()


def test_effective_faster_than_character_speed_is_clamped():
    """A contradiction, and it must not produce negative gaps."""
    plan = timing(15, effective_wpm=25)
    assert plan.effective_wpm == 15
    assert plan.inter_character_ms > 0


@pytest.mark.parametrize("bad", [0, -5])
def test_nonsense_speeds_are_refused(bad):
    with pytest.raises(ValueError):
        timing(bad)


def test_higher_wpm_is_faster():
    assert word_duration_ms("CQ", timing(30)) < word_duration_ms("CQ", timing(10))


# --- reference data -------------------------------------------------------
def test_reference_carries_every_section():
    ref = reference()
    for key in (
        "letters",
        "digits",
        "punctuation",
        "extended",
        "prosigns",
        "q_codes",
        "abbreviations",
        "cut_numbers",
    ):
        assert ref[key], f"{key} is empty"


def test_q_codes_are_all_three_letters_starting_with_q():
    for entry in Q_CODES:
        assert entry["code"].startswith("Q")
        assert len(entry["code"]) == 3


def test_everything_has_a_meaning():
    """A reference chart with a blank column is not a reference chart."""
    for group in (Q_CODES, ABBREVIATIONS, PROSIGNS):
        for entry in group:
            assert entry.get("meaning"), entry


def test_prosign_codes_are_sendable():
    for entry in PROSIGNS:
        assert set(entry["code"]) <= {".", "-"}, entry


def test_cut_numbers_match_their_letters():
    """A cut number is a letter that sounds like a shorter digit. 5NN is 599."""
    for entry in CUT_NUMBERS:
        assert LETTERS[entry["cut"]] == entry["code"]


def test_decode_table_covers_every_encodable_character():
    for code in ENCODE.values():
        assert code in DECODE


# --- the browser agrees with the tables ------------------------------------
def test_the_browser_translator_matches_this_module():
    """web/lib/morse.js must not drift from the tables tested above.

    The tables live in Python because that is where they can be checked. The
    browser receives them as data, but it implements encode, decode and the
    timing arithmetic itself -- it has to, to translate as you type and to make
    a sound. That is a second implementation, and a second implementation is
    something that drifts.

    So it is run under node against the same reference payload and every answer
    compared. Skipped rather than failed where node is absent, because a
    contributor without it should still be able to run the suite.
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
    cases = ["CQ CQ DE W1AW", "SOS", "HELLO WORLD", "73 ES TU", "PARIS", "TEST 599", "A?B"]
    speeds = [5, 13, 20, 25, 40]

    with tempfile.TemporaryDirectory() as tmp:
        ref_path = Path(tmp) / "ref.json"
        ref_path.write_text(json.dumps(reference()), encoding="utf-8")

        driver = Path(tmp) / "cmp.mjs"
        driver.write_text(
            f"""
import {{ readFileSync }} from "fs";
import {{ tables, encodeText, decodeMorse, timing }} from "{root / "web/lib/morse.js"}";
const ref = JSON.parse(readFileSync({str(ref_path)!r}, "utf8"));
const {{ encode, decode }} = tables(ref);
const cases = {json.dumps(cases)};
const out = {{ encode: {{}}, decode: {{}}, timing: {{}} }};
for (const c of cases) out.encode[c] = encodeText(c, encode, {{ unknown: "" }});
for (const c of cases) {{
  const m = encodeText(c, encode, {{ unknown: "" }});
  out.decode[m] = decodeMorse(m, decode);
}}
for (const w of {json.dumps(speeds)}) out.timing[w] = timing(w);
out.farnsworth = timing(20, 10);
console.log(JSON.stringify(out));
""",
            encoding="utf-8",
        )

        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr
        js = json.loads(result.stdout)

    for text, got in js["encode"].items():
        assert got == encode(text), f"encode({text!r})"
    for morse, got in js["decode"].items():
        assert got == decode(morse), f"decode({morse!r})"

    for wpm, got in js["timing"].items():
        want = timing(float(wpm))
        assert got["dit"] == pytest.approx(want.dit_ms), wpm
        assert got["dah"] == pytest.approx(want.dah_ms), wpm
        assert got["inter"] == pytest.approx(want.inter_character_ms), wpm
        assert got["word"] == pytest.approx(want.inter_word_ms), wpm

    farnsworth = timing(20, 10)
    assert js["farnsworth"]["inter"] == pytest.approx(farnsworth.inter_character_ms)
    assert js["farnsworth"]["word"] == pytest.approx(farnsworth.inter_word_ms)

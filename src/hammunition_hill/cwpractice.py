# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""What to send when you are learning to copy it.

morse.py is the alphabet. This is the curriculum: the Koch order and its
lesson plan, the phonetics and Q-signals worth being quizzed on, callsigns
shaped like real ones, and the two conversations every operator has -- a
contest exchange and a ragchew.

Everything here is generated from a seed, by a generator implemented
identically in Python and in web/lib/morse.js. That is not a detail: a trainer
needs randomness and a *test* of a trainer needs the same randomness twice, and
seeding one algorithm both languages agree on is what lets the drift test
compare exact output rather than shapes. If the browser ever generates a
different callsign from the same seed, the suite says so.

No network, no state, no clock. Tier 0 in the sense the rest of the project
means it: as useful at a POTA site with the phone in aeroplane mode as at home.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import morse
from .prefix import builtin_prefixes

# The order Ludwig Koch found by experiment, and the reason the method works:
# each new character is chosen to be *confusable* with the ones already learned,
# so you are always discriminating rather than merely recognising. Learning
# alphabetically instead gives you A B C -- three characters that sound nothing
# alike, and no practice at the thing that is actually hard.
KOCH_ORDER = "KMRSUAPTLOWI.NJEF0Y,VG5/Q9ZH38B?42C7DX16"

# The number of characters a lesson adds. One is the classic; the ARRL and most
# software add the first two together because a two-character alphabet is the
# smallest that can be a discrimination exercise at all.
FIRST_LESSON = 2

# fmt: off
# Fenced per the rule in CONTRIBUTING: these are data, and they are laid out as
# tables because that is how they are read and checked. The formatter would
# expand them to one field per line and make a reviewer scroll for what
# currently fits in a glance.

# ITU/NATO. The spelling alphabet is the one piece of phone procedure a CW
# operator still needs, because the moment a callsign is misheard the fix is
# always "I say again, phonetically".
PHONETICS: tuple[dict[str, str], ...] = (
    {"char": "A", "word": "Alfa"},     {"char": "B", "word": "Bravo"},
    {"char": "C", "word": "Charlie"},  {"char": "D", "word": "Delta"},
    {"char": "E", "word": "Echo"},     {"char": "F", "word": "Foxtrot"},
    {"char": "G", "word": "Golf"},     {"char": "H", "word": "Hotel"},
    {"char": "I", "word": "India"},    {"char": "J", "word": "Juliett"},
    {"char": "K", "word": "Kilo"},     {"char": "L", "word": "Lima"},
    {"char": "M", "word": "Mike"},     {"char": "N", "word": "November"},
    {"char": "O", "word": "Oscar"},    {"char": "P", "word": "Papa"},
    {"char": "Q", "word": "Quebec"},   {"char": "R", "word": "Romeo"},
    {"char": "S", "word": "Sierra"},   {"char": "T", "word": "Tango"},
    {"char": "U", "word": "Uniform"},  {"char": "V", "word": "Victor"},
    {"char": "W", "word": "Whiskey"},  {"char": "X", "word": "X-ray"},
    {"char": "Y", "word": "Yankee"},   {"char": "Z", "word": "Zulu"},
    {"char": "0", "word": "Zero"},     {"char": "1", "word": "One"},
    {"char": "2", "word": "Two"},      {"char": "3", "word": "Three"},
    {"char": "4", "word": "Four"},     {"char": "5", "word": "Five"},
    {"char": "6", "word": "Six"},      {"char": "7", "word": "Seven"},
    {"char": "8", "word": "Eight"},    {"char": "9", "word": "Nine"},
)

# Short because they are sent by hand at 20 WPM. A ragchew generator that
# produced "BARTHOLOMEW" would be testing your patience, not your copy.
NAMES: tuple[str, ...] = (
    "BOB", "JIM", "TOM", "DAN", "AL", "ED", "KEN", "RAY", "JOE", "MIKE",
    "STEVE", "DAVE", "JACK", "PAUL", "RON", "GARY", "LARRY", "PETE", "SAM",
    "ANN", "SUE", "KATE", "JAN", "LIZ", "MARY", "PAT", "JEN", "CARL", "HANS",
    "YURI", "KENJI", "OLAF", "LUIS", "PIET", "IVAN", "FRANZ", "ANDY", "CHRIS",
)

# ARRL/RAC sections and a handful of DX cities: what actually lands in the QTH
# field of a real exchange.
QTHS: tuple[str, ...] = (
    "CT", "MA", "ME", "NH", "RI", "VT", "NY", "NJ", "DE", "MD", "PA",
    "AL", "FL", "GA", "KY", "NC", "SC", "TN", "VA", "AR", "LA", "MS", "TX",
    "OK", "CA", "AZ", "NM", "CO", "UT", "NV", "ID", "MT", "OR", "WA", "WY",
    "MI", "OH", "WV", "IN", "WI", "IL", "MN", "IA", "KS", "MO", "NE", "ND",
    "SD", "ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB",
    "TOKYO", "LONDON", "BERLIN", "MADRID", "ROMA", "OSLO", "PRAHA", "WIEN",
    "SYDNEY", "AUCKLAND", "LIMA", "RIO", "CAPETOWN", "SEOUL", "TAIPEI",
)

# Rig and antenna, for the half of a ragchew that is not the weather.
RIGS: tuple[str, ...] = (
    "IC7300", "FT991", "K3", "KX2", "KX3", "TS590", "FT710", "IC705",
    "QCX", "HOMEBREW", "TS850", "FT817", "K4", "IC7610",
)
ANTENNAS: tuple[str, ...] = (
    "DIPOLE", "VERTICAL", "EFHW", "G5RV", "YAGI", "LOOP", "INV V", "RANDOM WIRE",
    "MAGLOOP", "BEVERAGE", "HEXBEAM",
)
WEATHER: tuple[str, ...] = (
    "SUNNY", "CLDY", "RAIN", "SNOW", "FOGGY", "WINDY", "HOT", "CUL",
)
# fmt: on

# The two conversations. `me` is the operator's own callsign, `dx` the station
# being simulated; a line is one transmission, and the panel plays only the
# `dx` lines because copying your own sending is not the exercise.
#
# Written the way they are actually sent: callsigns doubled at the start when
# conditions are unknown, RST doubled, no punctuation that a key does not send.
CONTEST_SCRIPT: tuple[tuple[str, str], ...] = (
    ("dx", "CQ TEST {dx} {dx} TEST"),
    ("me", "{me}"),
    ("dx", "{me} 5NN {serial}"),
    ("me", "R 5NN {my_serial}"),
    ("dx", "TU {dx} TEST"),
)

RAGCHEW_SCRIPT: tuple[tuple[str, str], ...] = (
    ("dx", "CQ CQ CQ DE {dx} {dx} {dx} K"),
    ("me", "{dx} DE {me} {me} K"),
    (
        "dx",
        "{me} DE {dx} GE OM ES TNX FER CALL = UR RST {rst} {rst} "
        "= NAME {name} {name} = QTH {qth} {qth} = HW CPI? {me} DE {dx} KN",
    ),
    ("me", "{dx} DE {me} R FB {name} = UR RST 579 = NAME ... QTH ... = BK"),
    (
        "dx",
        "R R = RIG HR IS {rig} ES ANT IS {antenna} = WX {weather} = "
        "TNX FER FB QSO {name_of_me} = 73 ES GL DE {dx} SK",
    ),
)

SCRIPTS: dict[str, tuple[tuple[str, str], ...]] = {
    "contest": CONTEST_SCRIPT,
    "ragchew": RAGCHEW_SCRIPT,
}

_MASK = 0xFFFFFFFF


class Rng:
    """mulberry32, written out here so the browser and this module agree.

    Any PRNG would do for a trainer. What matters is that it is *the same* PRNG
    in both places, seeded the same way, so a test can assert that the browser
    produces the identical callsign for seed 12345 rather than merely producing
    something callsign-shaped. Small, public domain, and no state beyond a
    32-bit word.

    Not for anything that needs to be unguessable. It generates practice, and a
    practice callsign that someone can predict costs nothing.
    """

    def __init__(self, seed: int) -> None:
        self._a = seed & _MASK

    def next(self) -> float:
        """The next value in [0, 1)."""
        self._a = (self._a + 0x6D2B79F5) & _MASK
        t = self._a
        t = (t ^ (t >> 15)) & _MASK
        t = (t * (t | 1)) & _MASK
        t = (t ^ (t + (((t ^ (t >> 7)) * (t | 61)) & _MASK))) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    def below(self, n: int) -> int:
        """An integer in [0, n)."""
        return int(self.next() * n)

    def pick(self, items):
        return items[self.below(len(items))]


def lessons(order: str = KOCH_ORDER) -> list[dict[str, Any]]:
    """The Koch plan: lesson 1 is two characters, and each one after adds one.

    Returned in full rather than computed in the panel because a lesson number
    is the unit people track their progress in, and it should mean the same
    thing in the dashboard, the docs and the tests.
    """
    plan = []
    for index in range(FIRST_LESSON, len(order) + 1):
        plan.append(
            {
                "lesson": index - FIRST_LESSON + 1,
                "adds": order[index - 1] if index > FIRST_LESSON else order[:FIRST_LESSON],
                "alphabet": order[:index],
            }
        )
    return plan


def alphabet_for(lesson: int, order: str = KOCH_ORDER) -> str:
    """The characters a given lesson number covers, clamped to the order's length."""
    count = max(FIRST_LESSON, min(len(order), lesson + FIRST_LESSON - 1))
    return order[:count]


def groups(rng: Rng, alphabet: str, *, count: int = 5, size: int = 5) -> str:
    """Random character groups: the Koch exercise itself."""
    if not alphabet:
        return ""
    out = []
    for _ in range(count):
        out.append("".join(rng.pick(alphabet) for _ in range(size)))
    return " ".join(out)


# Weighted so that two-letter suffixes dominate, because they do: contest calls
# are short on purpose and a generator that produced W1ABC as often as W1AW
# would be practice for a band that does not exist.
_SUFFIX_WEIGHTS: tuple[tuple[int, float], ...] = ((1, 0.15), (2, 0.50), (3, 0.35))

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DIGITS = "0123456789"


def _suffix_length(rng: Rng) -> int:
    roll = rng.next()
    running = 0.0
    for length, weight in _SUFFIX_WEIGHTS:
        running += weight
        if roll < running:
            return length
    return _SUFFIX_WEIGHTS[-1][0]


def callsign(rng: Rng, prefixes: list[str]) -> str:
    """A callsign shaped like a real one, from a real DXCC prefix.

    The shape rule: a prefix already ending in a digit (KH6, KP4) takes the
    suffix directly; anything else takes a call area digit first. That gives
    KH6XY and W1AW and DL1ABC and 9A2AA from the same three lines, which is
    what real calls look like.

    Prefixes come from the table the rest of the dashboard already uses, so
    revealing the answer can also name the entity -- and a trainer that teaches
    prefixes while it teaches copy is strictly better than one that sends
    random letters.
    """
    if not prefixes:
        return ""
    prefix = rng.pick(prefixes)
    body = "" if prefix[-1] in _DIGITS else rng.pick(_DIGITS)
    suffix = "".join(rng.pick(_LETTERS) for _ in range(_suffix_length(rng)))
    return prefix + body + suffix


def callsigns(rng: Rng, prefixes: list[str], *, count: int = 5) -> list[str]:
    return [callsign(rng, prefixes) for _ in range(count)]


def entity_for(call: str, pool: list[dict[str, str]]) -> str:
    """The DXCC entity a practice callsign belongs to, longest prefix first.

    Longest-first because "K" and "KH6" are both in the table and a Hawaiian
    call must not come back as the mainland. Same scan the prefix panel does,
    over the same data; kept here so revealing a generated call can name the
    country without the trainer needing a second snapshot.
    """
    for entry in sorted(pool, key=lambda e: -len(e["prefix"])):
        if call.startswith(entry["prefix"]):
            return entry["entity"]
    return ""


@dataclass(frozen=True)
class Line:
    """One transmission in a simulated QSO."""

    speaker: str  # "dx" (played) or "me" (your turn, shown but not sent)
    text: str


def qso(
    rng: Rng,
    prefixes: list[str],
    *,
    style: str = "ragchew",
    my_call: str = "N0CALL",
    my_name: str = "OM",
) -> list[Line]:
    """A whole contact, both sides, with the other station's details filled in.

    Both sides are generated because the point is to copy *in context*: knowing
    that a callsign comes next is most of what makes a real exchange readable at
    a speed you cannot yet copy cold.
    """
    script = SCRIPTS.get(style)
    if script is None:
        raise ValueError(f"unknown QSO style: {style!r}")
    fields = {
        "dx": callsign(rng, prefixes),
        "me": my_call,
        "name": rng.pick(NAMES),
        "name_of_me": my_name,
        "qth": rng.pick(QTHS),
        "rig": rng.pick(RIGS),
        "antenna": rng.pick(ANTENNAS),
        "weather": rng.pick(WEATHER),
        "rst": f"5{rng.below(3) + 7}9",
        "serial": f"{rng.below(400) + 1:03d}",
        "my_serial": f"{rng.below(400) + 1:03d}",
    }
    return [Line(speaker, text.format(**fields)) for speaker, text in script]


def quiz_pairs() -> dict[str, list[dict[str, str]]]:
    """The question banks, built here rather than in the panel.

    Deriving them in the browser would be a third implementation to keep in
    step. They are small, they change only when the tables do, and building them
    on this side means the panel reads a list instead of reshaping one.
    """
    return {
        "phonetics": [{"prompt": row["char"], "answer": row["word"]} for row in PHONETICS],
        "q codes": [{"prompt": row["code"], "answer": row["meaning"]} for row in morse.Q_CODES],
        "abbrev": [
            {"prompt": row["code"], "answer": row["meaning"]} for row in morse.ABBREVIATIONS
        ],
    }


def quiz_question(rng: Rng, pairs: list[dict[str, str]], *, choices: int = 4) -> dict[str, Any]:
    """One multiple-choice question: a prompt, the answer, and wrong ones."""
    answer = rng.pick(pairs)
    options = [answer]
    # Bounded, because a bank with fewer distinct answers than `choices` would
    # otherwise spin here looking for a fourth wrong one that does not exist.
    tries = 0
    while len(options) < choices and tries < 200:
        tries += 1
        candidate = rng.pick(pairs)
        if not any(o["answer"] == candidate["answer"] for o in options):
            options.append(candidate)
    # Fisher-Yates, so the right answer is not always first.
    for i in range(len(options) - 1, 0, -1):
        j = rng.below(i + 1)
        options[i], options[j] = options[j], options[i]
    return {
        "prompt": answer["prompt"],
        "answer": answer["answer"],
        "options": [o["answer"] for o in options],
    }


def reference() -> dict[str, Any]:
    """The practice data the panel needs, published alongside the Morse tables."""
    return {
        "koch_order": KOCH_ORDER,
        "first_lesson": FIRST_LESSON,
        "lessons": lessons(),
        "phonetics": list(PHONETICS),
        "names": list(NAMES),
        "qths": list(QTHS),
        "rigs": list(RIGS),
        "antennas": list(ANTENNAS),
        "weather": list(WEATHER),
        "quizzes": quiz_pairs(),
        "prefixes": builtin_prefixes(),
        "scripts": {
            style: [{"speaker": s, "text": t} for s, t in script]
            for style, script in SCRIPTS.items()
        },
    }

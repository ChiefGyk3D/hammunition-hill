# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Morse code: the tables, the timing, and the shorthand.

Tier 0 in every sense -- this is reference data and arithmetic, it needs no
network, and it is as useful with the WAN unplugged as with it up. Which is the
point: the operator most likely to want a prosign chart is the one sitting at a
straight key in a field.

The canonical tables live here, in Python, rather than in the JavaScript that
renders them. Two reasons. They are testable here, and there are a great many
ways to get one character of a Morse table subtly wrong. And the browser
receives them as published data, so a panel cannot disagree with a test about
what `..-.` means.

## The prosign collision, which is not a bug

Several prosigns are *the same sound* as a punctuation mark:

    AR  .-.-.   is also  +
    BT  -...-   is also  =
    KN  -.--.   is also  (
    AS  .-...   is also  &

That is not an encoding mistake to be fixed. Morse has no capitalisation and no
punctuation namespace; `+` and AR are one pattern and always were, and context
tells an operator which is meant. The decoder therefore returns the punctuation
form and the reference chart lists both, because pretending the collision does
not exist would be the actual error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- the alphabet ---------------------------------------------------------
# fmt: off
# Fenced per the rule in CONTRIBUTING: these are data, and a Morse table is
# the archetype of one. Read as a table, checked against a chart as a table,
# and 26 letters at one per line is four screens of scrolling to verify what
# currently fits in five.
LETTERS: dict[str, str] = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
}

DIGITS: dict[str, str] = {
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}

PUNCTUATION: dict[str, str] = {
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
    ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-",
    '"': ".-..-.", "$": "...-..-", "@": ".--.-.",
}

# Accented and non-English characters that appear in international Morse. Worth
# carrying: a decoder that turns a German station's callsign into gibberish is
# not much use on 40m.
EXTENDED: dict[str, str] = {
    "Ä": ".-.-", "Á": ".--.-", "Å": ".--.-", "Ç": "-.-..", "Ð": "..--.",
    "È": ".-..-", "É": "..-..", "Ĝ": "--.-.", "Ĥ": "----", "Ĵ": ".---.",
    "Ñ": "--.--", "Ö": "---.", "Ŝ": "...-.", "Þ": ".--..", "Ü": "..--",
}

# --- prosigns -------------------------------------------------------------
# Sent as one symbol with no inter-letter gap, which is what the overbar in
# printed Morse means. The name is conventionally written with a bar over it.
PROSIGNS: tuple[dict[str, str], ...] = (
    {"sign": "AR", "code": ".-.-.", "meaning": "End of message", "also": "+"},
    {"sign": "AS", "code": ".-...", "meaning": "Wait / stand by", "also": "&"},
    {"sign": "BT", "code": "-...-", "meaning": "Separator between sections", "also": "="},
    {"sign": "KN", "code": "-.--.", "meaning": "Go ahead, named station only", "also": "("},
    {"sign": "SK", "code": "...-.-", "meaning": "End of contact", "also": ""},
    {"sign": "CT", "code": "-.-.-", "meaning": "Attention / start of message", "also": ""},
    {"sign": "SN", "code": "...-.", "meaning": "Understood", "also": ""},
    {"sign": "BK", "code": "-...-.-", "meaning": "Break — invite the other station in", "also": ""},
    {"sign": "HH", "code": "........", "meaning": "Error — disregard, starting again", "also": ""},
    {"sign": "CL", "code": "-.-..-..", "meaning": "Closing down the station", "also": ""},
)

# --- shorthand ------------------------------------------------------------
# The Q codes an operator actually meets on the air, not the full ITU list.
Q_CODES: tuple[dict[str, str], ...] = (
    {"code": "QRA", "meaning": "The name of my station is…"},
    {"code": "QRG", "meaning": "Your exact frequency is…"},
    {"code": "QRL", "meaning": "Is this frequency busy? / I am busy"},
    {"code": "QRM", "meaning": "Interference from other stations"},
    {"code": "QRN", "meaning": "Atmospheric noise / static"},
    {"code": "QRO", "meaning": "Increase power"},
    {"code": "QRP", "meaning": "Reduce power / low-power operation"},
    {"code": "QRQ", "meaning": "Send faster"},
    {"code": "QRS", "meaning": "Send more slowly"},
    {"code": "QRT", "meaning": "Stop sending / I am closing down"},
    {"code": "QRU", "meaning": "Have you anything for me? / I have nothing"},
    {"code": "QRV", "meaning": "Are you ready? / I am ready"},
    {"code": "QRX", "meaning": "Stand by, I will call again"},
    {"code": "QRZ", "meaning": "Who is calling me?"},
    {"code": "QSB", "meaning": "Your signal is fading"},
    {"code": "QSK", "meaning": "I can hear you between my characters — break in"},
    {"code": "QSL", "meaning": "I acknowledge receipt / confirmation card"},
    {"code": "QSO", "meaning": "A contact / conversation"},
    {"code": "QSY", "meaning": "Change to another frequency"},
    {"code": "QTH", "meaning": "My location is…"},
    {"code": "QTR", "meaning": "The correct time is…"},
)

ABBREVIATIONS: tuple[dict[str, str], ...] = (
    {"code": "CQ", "meaning": "Calling any station"},
    {"code": "DE", "meaning": "From (this is)"},
    {"code": "K", "meaning": "Go ahead, any station"},
    {"code": "R", "meaning": "Roger — received"},
    {"code": "TU", "meaning": "Thank you"},
    {"code": "73", "meaning": "Best regards"},
    {"code": "88", "meaning": "Love and kisses"},
    {"code": "ES", "meaning": "And"},
    {"code": "HR", "meaning": "Here"},
    {"code": "UR", "meaning": "Your / you are"},
    {"code": "RST", "meaning": "Readability, strength, tone"},
    {"code": "WX", "meaning": "Weather"},
    {"code": "PSE", "meaning": "Please"},
    {"code": "TNX", "meaning": "Thanks"},
    {"code": "OM", "meaning": "Old man — any male operator"},
    {"code": "YL", "meaning": "Young lady — any female operator"},
    {"code": "XYL", "meaning": "Wife"},
    {"code": "FB", "meaning": "Fine business — excellent"},
    {"code": "HI", "meaning": "Laughter"},
    {"code": "AGN", "meaning": "Again"},
    {"code": "ANT", "meaning": "Antenna"},
    {"code": "CFM", "meaning": "Confirm"},
    {"code": "CUL", "meaning": "See you later"},
    {"code": "GM / GA / GE", "meaning": "Good morning / afternoon / evening"},
    {"code": "GUD", "meaning": "Good"},
    {"code": "NR", "meaning": "Number"},
    {"code": "PWR", "meaning": "Power"},
    {"code": "RPT", "meaning": "Repeat"},
    {"code": "SRI", "meaning": "Sorry"},
    {"code": "WKD", "meaning": "Worked"},
    {"code": "5NN", "meaning": "599, sent with cut numbers in contests"},
)

# Cut numbers: contest operators shorten common digits because the full form is
# long and the context makes it unambiguous. Worth knowing before your first
# contest, where you will hear "5NN" and not "599".
CUT_NUMBERS: tuple[dict[str, str], ...] = (
    {"digit": "0", "cut": "T", "code": "-"},
    {"digit": "1", "cut": "A", "code": ".-"},
    {"digit": "9", "cut": "N", "code": "-."},
    {"digit": "5", "cut": "E", "code": "."},
)

# Characters that genuinely share one pattern. Á and Å are the same sound in
# international Morse -- not a table error, and not something a decoder can
# resolve without knowing the language. The decoder returns whichever comes
# first and the chart shows both, which is all anyone can honestly do.
SYNONYMS: tuple[tuple[str, ...], ...] = (("Á", "Å"),)

# --- lookups --------------------------------------------------------------
ENCODE: dict[str, str] = {**LETTERS, **DIGITS, **PUNCTUATION, **EXTENDED}

# Built by inversion, so the two directions cannot disagree. Where a pattern has
# two spellings -- "+" and AR -- the punctuation wins, because that is what a
# decoder should print; the prosign chart carries the other reading.
DECODE: dict[str, str] = {}
for _char, _code in ENCODE.items():
    DECODE.setdefault(_code, _char)

# --- timing ---------------------------------------------------------------
# "PARIS" is the standard word: 50 dit units including the trailing word gap.
# One dit at 1 WPM is 1200 ms, so a dit at N WPM is 1200/N.
PARIS_UNITS = 50
DIT_MS_AT_1_WPM = 1200.0

DAH_UNITS = 3
INTRA_CHARACTER_UNITS = 1  # between the dits and dahs of one character
INTER_CHARACTER_UNITS = 3  # between characters of one word
INTER_WORD_UNITS = 7  # between words


@dataclass(frozen=True)
class Timing:
    """Element and gap durations, in milliseconds."""

    wpm: float
    effective_wpm: float
    dit_ms: float
    dah_ms: float
    intra_character_ms: float
    inter_character_ms: float
    inter_word_ms: float

    @property
    def farnsworth(self) -> bool:
        return self.effective_wpm < self.wpm

    def to_dict(self) -> dict[str, Any]:
        return {
            "wpm": self.wpm,
            "effective_wpm": self.effective_wpm,
            "farnsworth": self.farnsworth,
            "dit_ms": round(self.dit_ms, 2),
            "dah_ms": round(self.dah_ms, 2),
            "intra_character_ms": round(self.intra_character_ms, 2),
            "inter_character_ms": round(self.inter_character_ms, 2),
            "inter_word_ms": round(self.inter_word_ms, 2),
        }


def timing(wpm: float, effective_wpm: float | None = None) -> Timing:
    """Element timings for a speed, optionally with Farnsworth spacing.

    Farnsworth sends the *characters* at full speed and stretches the gaps
    between them, so a learner hears the real rhythm of a letter from the start
    instead of a slowed-down version they will have to unlearn. The extra time
    is distributed by the ARRL's formula, which spreads it across the character
    and word gaps in a 3:7 ratio -- the same ratio the standard gaps have, so
    the result still sounds like Morse rather than like pauses.
    """
    if wpm <= 0:
        raise ValueError("wpm must be positive")
    effective = wpm if effective_wpm is None else effective_wpm
    if effective <= 0:
        raise ValueError("effective_wpm must be positive")
    if effective > wpm:
        # Sending characters slower than the overall rate is not Farnsworth,
        # it is a contradiction. Clamp rather than produce negative gaps.
        effective = wpm

    dit = DIT_MS_AT_1_WPM / wpm

    if effective == wpm:
        return Timing(
            wpm=wpm,
            effective_wpm=effective,
            dit_ms=dit,
            dah_ms=dit * DAH_UNITS,
            intra_character_ms=dit * INTRA_CHARACTER_UNITS,
            inter_character_ms=dit * INTER_CHARACTER_UNITS,
            inter_word_ms=dit * INTER_WORD_UNITS,
        )

    # ARRL: total delay to insert per "PARIS", in seconds.
    delay_seconds = (60.0 * wpm - 37.2 * effective) / (wpm * effective)
    delay_ms = delay_seconds * 1000.0

    return Timing(
        wpm=wpm,
        effective_wpm=effective,
        dit_ms=dit,
        dah_ms=dit * DAH_UNITS,
        intra_character_ms=dit * INTRA_CHARACTER_UNITS,
        inter_character_ms=delay_ms * 3.0 / 19.0,
        inter_word_ms=delay_ms * 7.0 / 19.0,
    )


def word_duration_ms(text: str, plan: Timing) -> float:
    """How long ``text`` takes to send. Used to check a timing against PARIS."""
    total = 0.0
    words = [w for w in text.upper().split(" ") if w]
    for word_index, word in enumerate(words):
        if word_index:
            total += plan.inter_word_ms
        for char_index, char in enumerate(word):
            code = ENCODE.get(char)
            if code is None:
                continue
            if char_index:
                total += plan.inter_character_ms
            for element_index, element in enumerate(code):
                if element_index:
                    total += plan.intra_character_ms
                total += plan.dah_ms if element == "-" else plan.dit_ms
    return total


# --- encoding and decoding -------------------------------------------------
def encode(text: str, *, unknown: str = "") -> str:
    """Text to Morse. Characters separated by a space, words by ``/``.

    Unknown characters are dropped by default rather than guessed at. Pass
    ``unknown="?"`` to mark them instead, which is what the panel does so a
    user can see that something did not translate.
    """
    words = []
    for word in text.upper().split():
        codes = []
        for char in word:
            code = ENCODE.get(char)
            if code is not None:
                codes.append(code)
            elif unknown:
                codes.append(unknown)
        if codes:
            words.append(" ".join(codes))
    return " / ".join(words)


def decode(code: str, *, unknown: str = "?") -> str:
    """Morse to text.

    Accepts the common spellings people actually type: ``/`` or a double space
    for a word gap, and ``·``/``•`` for a dit or ``—``/``–`` for a dah, because
    a chart copied out of a book or a web page rarely uses ASCII.
    """
    normalised = (
        code.replace("·", ".")
        .replace("•", ".")
        .replace("—", "-")
        .replace("–", "-")
        .replace("_", "-")
    )
    # A double space is the other common way to write a word gap. Convert it
    # before splitting so both spellings take the same path.
    normalised = normalised.replace("  ", " / ")

    words = []
    for chunk in normalised.split("/"):
        letters = []
        for token in chunk.split():
            if not token:
                continue
            letters.append(DECODE.get(token, unknown))
        if letters:
            words.append("".join(letters))
    return " ".join(words)


def reference() -> dict[str, Any]:
    """Everything the panel renders, as one published structure."""
    return {
        "letters": [{"char": c, "code": k} for c, k in LETTERS.items()],
        "digits": [{"char": c, "code": k} for c, k in DIGITS.items()],
        "punctuation": [{"char": c, "code": k} for c, k in PUNCTUATION.items()],
        "extended": [{"char": c, "code": k} for c, k in EXTENDED.items()],
        "prosigns": list(PROSIGNS),
        "q_codes": list(Q_CODES),
        "abbreviations": list(ABBREVIATIONS),
        "cut_numbers": list(CUT_NUMBERS),
    }

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The pocket reference: the things an operator constantly looks up.

Q signals, the number codes, RST, the phonetic alphabet, the calling
frequencies, and a short directory of the sites worth knowing. Everything here
is tier 0 -- static tables published once at startup, readable with the WAN
down, which is exactly when a field operator needs a reference most.

The line between this and the CW panel: the CW panel teaches (Koch order,
timing, drills), this one answers. The Q codes and abbreviations live in
morse.py because the CW trainer quizzes on them; this module re-publishes the
same tables so there is one canonical copy of each.

The link directory is links, not content: a plain anchor costs nothing under
the CSP (only embedded resources need an allowance) and navigates away
deliberately. Nothing here causes the dashboard itself to fetch anything.
"""

from __future__ import annotations

from typing import Any

from .cwpractice import PHONETICS
from .morse import ABBREVIATIONS, CUT_NUMBERS, PROSIGNS, Q_CODES

# fmt: off
# The RST system, as given: three digits sent, each ordinal. Worth carrying
# because the words matter -- a 559 is not an insult and a 599 from a contester
# is not a measurement.
RST_READABILITY: tuple[dict[str, str], ...] = (
    {"value": "1", "meaning": "Unreadable"},
    {"value": "2", "meaning": "Barely readable, occasional words distinguishable"},
    {"value": "3", "meaning": "Readable with considerable difficulty"},
    {"value": "4", "meaning": "Readable with practically no difficulty"},
    {"value": "5", "meaning": "Perfectly readable"},
)
RST_STRENGTH: tuple[dict[str, str], ...] = (
    {"value": "1", "meaning": "Faint signals, barely perceptible"},
    {"value": "2", "meaning": "Very weak signals"},
    {"value": "3", "meaning": "Weak signals"},
    {"value": "4", "meaning": "Fair signals"},
    {"value": "5", "meaning": "Fairly good signals"},
    {"value": "6", "meaning": "Good signals"},
    {"value": "7", "meaning": "Moderately strong signals"},
    {"value": "8", "meaning": "Strong signals"},
    {"value": "9", "meaning": "Extremely strong signals"},
)
RST_TONE: tuple[dict[str, str], ...] = (
    {"value": "1", "meaning": "Sixty-cycle AC or less, very rough and broad"},
    {"value": "2", "meaning": "Very rough AC, very harsh and broad"},
    {"value": "3", "meaning": "Rough AC tone, rectified but not filtered"},
    {"value": "4", "meaning": "Rough note, some trace of filtering"},
    {"value": "5", "meaning": "Filtered rectified AC but strongly ripple-modulated"},
    {"value": "6", "meaning": "Filtered tone, definite trace of ripple modulation"},
    {"value": "7", "meaning": "Near pure tone, trace of ripple modulation"},
    {"value": "8", "meaning": "Near perfect tone, slight trace of modulation"},
    {"value": "9", "meaning": "Perfect tone, no trace of ripple or modulation"},
)

# The number codes from the old wire-telegraph 92 Code that survived into
# amateur use. 73 and 88 everyone knows; the rest turn up in logs and QSLs.
NUMBER_CODES: tuple[dict[str, str], ...] = (
    {"code": "73", "meaning": "Best regards"},
    {"code": "88", "meaning": "Love and kisses"},
    {"code": "55", "meaning": "Best success (mostly heard from Europe)"},
    {"code": "72", "meaning": "Best regards, QRP style — low power to you too"},
    {"code": "33", "meaning": "Fondest regards (YL to YL, by tradition)"},
    {"code": "161", "meaning": "73 + 88 — best regards to the whole household"},
    {"code": "30", "meaning": "End of transmission — ancestor of CW's SK"},
)

# US calling and centre-of-activity frequencies, MHz. The ones somebody in a
# field actually keys in from memory and gets wrong. National conventions, not
# regulations: Part 97 does not assign calling frequencies, custom does.
CALLING_FREQUENCIES: tuple[dict[str, str], ...] = (
    {"mhz": "146.520", "use": "2 m FM simplex calling"},
    {"mhz": "446.000", "use": "70 cm FM simplex calling"},
    {"mhz": "52.525",  "use": "6 m FM simplex calling"},
    {"mhz": "144.200", "use": "2 m SSB calling"},
    {"mhz": "50.125",  "use": "6 m SSB calling (US)"},
    {"mhz": "14.074",  "use": "20 m FT8"},
    {"mhz": "7.074",   "use": "40 m FT8"},
    {"mhz": "3.573",   "use": "80 m FT8"},
    {"mhz": "21.074",  "use": "15 m FT8"},
    {"mhz": "28.074",  "use": "10 m FT8"},
    {"mhz": "14.070",  "use": "20 m PSK31"},
    {"mhz": "14.060",  "use": "20 m QRP CW calling"},
    {"mhz": "7.030",   "use": "40 m QRP CW calling"},
    {"mhz": "3.560",   "use": "80 m QRP CW calling"},
    {"mhz": "14.285",  "use": "20 m QRP SSB calling"},
    {"mhz": "14.230",  "use": "20 m SSTV"},
    {"mhz": "14.233",  "use": "20 m digital SSTV"},
    {"mhz": "18.100",  "use": "17 m FT8"},
    {"mhz": "24.915",  "use": "12 m FT8"},
    {"mhz": "50.313",  "use": "6 m FT8"},
)

# Sites worth a bookmark, with what each is FOR. Links, not content: clicking
# one leaves the dashboard, which is the point -- the dashboard fetches nothing
# on anyone's behalf here.
LINKS: tuple[dict[str, str], ...] = (
    {
        "name": "FCC licence search (ULS)",
        "url": "https://wireless2.fcc.gov/UlsApp/UlsSearch/searchLicense.jsp",
        "why": "The authoritative record for US callsigns",
    },
    {
        "name": "ARRL",
        "url": "https://www.arrl.org/",
        "why": "Band plans, exam sessions, bulletins",
    },
    {
        "name": "ARRL exam session search",
        "url": "https://www.arrl.org/find-an-amateur-radio-license-exam-session",
        "why": "Where to actually take the test",
    },
    {
        "name": "QRZ",
        "url": "https://www.qrz.com/",
        "why": "Callsign pages and bios",
    },
    {
        "name": "RepeaterBook",
        "url": "https://www.repeaterbook.com/",
        "why": "Repeaters near any location",
    },
    {
        "name": "PSK Reporter",
        "url": "https://pskreporter.info/pskmap.html",
        "why": "Who is hearing your digital signal right now",
    },
    {
        "name": "Reverse Beacon Network",
        "url": "https://www.reversebeacon.net/",
        "why": "Who is hearing your CW, with SNR",
    },
    {
        "name": "DX Summit",
        "url": "http://www.dxsummit.fi/",
        "why": "Cluster spots on the web",
    },
    {
        "name": "POTA",
        "url": "https://pota.app/",
        "why": "Park activations and spots",
    },
    {
        "name": "SOTA (sotawatch)",
        "url": "https://sotawatch.sota.org.uk/",
        "why": "Summit activations and spots",
    },
    {
        "name": "NOAA SWPC",
        "url": "https://www.swpc.noaa.gov/",
        "why": "The source behind the space weather panels",
    },
    {
        "name": "Time and frequency (WWV)",
        "url": "https://www.nist.gov/pml/time-and-frequency-division/time-services/wwv",
        "why": "2.5/5/10/15/20 MHz standard time",
    },
    {
        "name": "IARU",
        "url": "https://www.iaru.org/",
        "why": "Region band plans beyond the US",
    },
    {
        "name": "eCFR Part 97",
        "url": "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97",
        "why": "The rules, always-current edition — a copy also ships in the exam panel",
    },
)
# fmt: on


def snapshot_payload() -> dict[str, Any]:
    """Everything the reference panel shows, one snapshot, published at startup."""
    return {
        "q_codes": list(Q_CODES),
        "abbreviations": list(ABBREVIATIONS),
        # With the lookup views deduplicated out of the CW panel, this is where
        # someone hearing 5NN goes to decode it, so the cut numbers come along.
        "cut_numbers": list(CUT_NUMBERS),
        "prosigns": list(PROSIGNS),
        "number_codes": list(NUMBER_CODES),
        "phonetics": list(PHONETICS),
        "rst": {
            "readability": list(RST_READABILITY),
            "strength": list(RST_STRENGTH),
            "tone": list(RST_TONE),
        },
        "calling_frequencies": list(CALLING_FREQUENCIES),
        "links": list(LINKS),
    }

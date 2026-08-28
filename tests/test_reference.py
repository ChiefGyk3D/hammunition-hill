# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The pocket reference: the tables an operator reaches for mid-QSO.

These are data tests, because the module is data. What is worth asserting is
the shape the panel depends on, the internal consistency a hand-maintained
table loses first, and the handful of facts that would be embarrassing wrong
-- 146.520 is the 2 m calling frequency in the way 4 is the number after 3.
"""

from __future__ import annotations

import re

from hammunition_hill.reference import (
    CALLING_FREQUENCIES,
    LINKS,
    NUMBER_CODES,
    RST_READABILITY,
    RST_STRENGTH,
    RST_TONE,
    snapshot_payload,
)


def test_the_payload_has_every_section_the_panel_reads():
    payload = snapshot_payload()
    for key in (
        "q_codes",
        "abbreviations",
        "prosigns",
        "number_codes",
        "phonetics",
        "rst",
        "calling_frequencies",
        "links",
    ):
        assert payload.get(key), f"payload is missing {key!r}"
    assert set(payload["rst"]) == {"readability", "strength", "tone"}


def test_rst_scales_are_complete_and_ordinal():
    """R is 1-5, S and T are 1-9, each value once, in order."""
    for scale, top in ((RST_READABILITY, 5), (RST_STRENGTH, 9), (RST_TONE, 9)):
        values = [entry["value"] for entry in scale]
        assert values == [str(n) for n in range(1, top + 1)], values


def test_q_codes_cover_the_ones_actually_heard():
    codes = {entry["code"] for entry in snapshot_payload()["q_codes"]}
    heard = {"QRL", "QRM", "QRN", "QRP", "QRT", "QRZ", "QSB", "QSL", "QSO", "QSY",
             "QTH", "QRS", "QSK", "QST", "QSP", "QSX", "QTC"}  # fmt: skip
    missing = heard - codes
    assert not missing, f"Q codes missing: {sorted(missing)}"
    ordered = [entry["code"] for entry in snapshot_payload()["q_codes"]]
    assert ordered == sorted(ordered), "Q codes are shown as a lookup table; keep them sorted"


def test_the_number_codes_include_the_two_everyone_uses():
    codes = {entry["code"] for entry in NUMBER_CODES}
    assert {"73", "88"} <= codes


def test_calling_frequencies_are_plausible():
    """Each entry parses as MHz and sits inside an amateur allocation.

    The check is deliberately coarse -- inside 1.8 to 1300 MHz and matching the
    band its label names -- because the fine detail is convention, not
    regulation. What it catches is a typo: 14.652 for 146.52 survives a read
    but not a comparison against its own label.
    """
    for entry in CALLING_FREQUENCIES:
        mhz = float(entry["mhz"])
        assert 1.8 <= mhz <= 1300, entry
        label = entry["use"]
        match = re.match(r"(\d+(?:\.\d+)?)\s*(m|cm)\b", label)
        assert match, f"no band in label: {label!r}"
        metres = float(match.group(1)) / (100 if match.group(2) == "cm" else 1)
        # wavelength(m) ~ 300/f: the named band and the frequency must agree
        # loosely -- band names are nominal ("80 m" spans 3.5-4.0 MHz).
        assert 0.5 <= (300 / mhz) / metres <= 2.0, (
            f"{entry['mhz']} MHz does not live in the {label!r} band"
        )


def test_the_2m_calling_frequency_is_right():
    entries = {entry["use"]: entry["mhz"] for entry in CALLING_FREQUENCIES}
    assert entries["2 m FM simplex calling"] == "146.520"
    assert entries["70 cm FM simplex calling"] == "446.000"
    assert entries["20 m FT8"] == "14.074"


def test_links_are_https_where_the_site_offers_it():
    """And every link says what it is FOR -- a bare list of names is not a
    directory, it is a quiz."""
    for link in LINKS:
        assert link["url"].startswith(("https://", "http://")), link
        assert len(link["why"]) > 10, f"{link['name']}: no reason given"
    names = [link["name"] for link in LINKS]
    assert len(names) == len(set(names)), "duplicate link names"

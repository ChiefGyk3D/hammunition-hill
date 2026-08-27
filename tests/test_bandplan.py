# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Band plan data validation.

The band plans are hand-edited JSON, which is the point -- correcting one should
not require touching Python. These tests are what makes that safe: they fail
loudly if an edit produces a segment outside its band, a class that does not
exist, or a band name the rest of the system does not recognize.

They validate *structure*, not regulation. Nothing here can tell you whether
Part 97 actually says what the file claims, so the file is labelled reference
only and carries the revision date it was written against.
"""

import json
from pathlib import Path

import pytest

from hammunition_hill.bands import BAND_ORDER

PLANS_DIR = Path(__file__).resolve().parent.parent / "web" / "bandplans"

KNOWN_MODES = {"CW", "Digital", "Phone", "Image"}


def load(name):
    return json.loads((PLANS_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index():
    return load("index.json")


@pytest.fixture(scope="module")
def plans(index):
    return {entry["id"]: load(entry["file"]) for entry in index["available"]}


# --- the index ----------------------------------------------------------
def test_index_lists_at_least_one_plan(index):
    assert index["available"]


def test_default_plan_exists(index):
    assert index["default"] in {entry["id"] for entry in index["available"]}


def test_every_listed_file_is_present(index):
    for entry in index["available"]:
        assert (PLANS_DIR / entry["file"]).is_file(), entry["file"]


def test_plan_ids_are_unique(index):
    ids = [entry["id"] for entry in index["available"]]
    assert len(ids) == len(set(ids))


def test_file_id_matches_index_id(plans, index):
    for entry in index["available"]:
        assert plans[entry["id"]]["id"] == entry["id"]


# --- every plan ---------------------------------------------------------
@pytest.fixture
def plan_items(plans):
    return list(plans.items())


def test_required_top_level_keys(plan_items):
    for name, plan in plan_items:
        for key in ("id", "name", "authority", "revised", "note", "classes", "bands"):
            assert key in plan, f"{name}: missing {key!r}"


def test_plans_carry_a_reference_only_disclaimer(plan_items):
    """A band plan someone might transmit against must not read as authoritative."""
    for name, plan in plan_items:
        assert "reference only" in plan["note"].lower(), name
        assert plan["authority"], name


def test_class_ids_are_unique(plan_items):
    for name, plan in plan_items:
        ids = [c["id"] for c in plan["classes"]]
        assert len(ids) == len(set(ids)), name


def test_classes_run_least_to_most_privileged(plan_items):
    """Order is load-bearing: the panel renders the selector in this order."""
    for name, plan in plan_items:
        counts = []
        for klass in plan["classes"]:
            counts.append(
                sum(
                    1
                    for band in plan["bands"]
                    for segment in band["segments"]
                    if klass["id"] in segment["classes"]
                )
            )
        assert counts == sorted(counts), f"{name}: {counts}"


def test_segments_reference_declared_classes(plan_items):
    for name, plan in plan_items:
        declared = {c["id"] for c in plan["classes"]}
        for band in plan["bands"]:
            for segment in band["segments"]:
                unknown = set(segment["classes"]) - declared
                assert not unknown, f"{name} {band['band']}: unknown classes {unknown}"


def test_every_class_has_some_privilege(plan_items):
    for name, plan in plan_items:
        for klass in plan["classes"]:
            used = any(
                klass["id"] in segment["classes"]
                for band in plan["bands"]
                for segment in band["segments"]
            )
            assert used, f"{name}: {klass['id']} appears in no segment"


def test_segments_sit_inside_their_band(plan_items):
    for name, plan in plan_items:
        for band in plan["bands"]:
            low, high = band["khz"]
            for segment in band["segments"]:
                s_low, s_high = segment["khz"]
                where = f"{name} {band['band']}"
                assert low <= s_low <= high, f"{where}: {s_low} outside {low}-{high}"
                assert low <= s_high <= high, f"{where}: {s_high} outside {low}-{high}"


def test_segment_bounds_are_ordered(plan_items):
    for name, plan in plan_items:
        for band in plan["bands"]:
            for segment in band["segments"]:
                s_low, s_high = segment["khz"]
                assert s_low <= s_high, f"{name} {band['band']}: {s_low} > {s_high}"


def test_band_bounds_are_ordered(plan_items):
    for name, plan in plan_items:
        for band in plan["bands"]:
            assert band["khz"][0] < band["khz"][1], f"{name} {band['band']}"


def test_bands_ascend_in_frequency(plan_items):
    """Low band to high, the way an operator reads a band chart."""
    for name, plan in plan_items:
        lows = [band["khz"][0] for band in plan["bands"]]
        assert lows == sorted(lows), name


def test_band_names_are_unique(plan_items):
    for name, plan in plan_items:
        names = [band["band"] for band in plan["bands"]]
        assert len(names) == len(set(names)), name


def test_modes_come_from_the_known_vocabulary(plan_items):
    for name, plan in plan_items:
        for band in plan["bands"]:
            for segment in band["segments"]:
                unknown = set(segment["modes"]) - KNOWN_MODES
                assert not unknown, f"{name} {band['band']}: unknown modes {unknown}"


def test_every_segment_has_a_mode_and_a_class(plan_items):
    for name, plan in plan_items:
        for band in plan["bands"]:
            for segment in band["segments"]:
                assert segment["modes"], f"{name} {band['band']}: segment with no modes"
                assert segment["classes"], f"{name} {band['band']}: segment with no classes"


def test_band_names_match_the_band_classifier(plan_items):
    """Catches drift between the band plan and bands.py.

    A band plan naming a band '2 m' while the classifier says '2m' would put
    spots and privileges in different buckets, invisibly.
    """
    for name, plan in plan_items:
        for band in plan["bands"]:
            assert band["band"] in BAND_ORDER, (
                f"{name}: band {band['band']!r} is not in bands.py BAND_ORDER"
            )


def test_band_edges_agree_with_the_classifier(plan_items):
    """A plan's band edges must fall inside the classifier's widest allocation.

    The classifier deliberately uses the widest common allocation across IARU
    regions, so any single country's edges should sit within it.
    """
    from hammunition_hill.bands import BANDS

    edges = {band: (low, high) for band, low, high in BANDS}
    for name, plan in plan_items:
        for band in plan["bands"]:
            low, high = edges[band["band"]]
            assert low <= band["khz"][0], f"{name} {band['band']}: starts below the classifier"
            assert band["khz"][1] <= high, f"{name} {band['band']}: ends above the classifier"


# --- US specifics -------------------------------------------------------
def test_us_plan_has_all_five_classes_least_to_most(plans):
    assert [c["id"] for c in plans["us"]["classes"]] == [
        "novice",
        "technician",
        "general",
        "advanced",
        "extra",
    ]


def test_grandfathered_classes_are_marked(plans):
    """Novice and Advanced are closed to new issue; the UI says so."""
    grandfathered = {c["id"] for c in plans["us"]["classes"] if c.get("grandfathered")}
    assert grandfathered == {"novice", "advanced"}


def test_us_novice_hf_is_cw_only_below_10m(plans):
    for band_name in ("80m", "40m", "15m"):
        band = next(b for b in plans["us"]["bands"] if b["band"] == band_name)
        novice = [s for s in band["segments"] if "novice" in s["classes"]]
        assert novice, band_name
        assert all(s["modes"] == ["CW"] for s in novice), band_name


def test_us_novice_has_no_hf_phone_except_ten_metres(plans):
    """Novice phone exists only in the 28.3-28.5 MHz window."""
    for band in plans["us"]["bands"]:
        if band["band"] in ("6m", "2m", "1.25m", "70cm", "33cm", "23cm", "10m"):
            continue
        for segment in band["segments"]:
            if "novice" in segment["classes"]:
                assert "Phone" not in segment["modes"], band["band"]


def test_us_novice_vhf_is_only_222_and_23cm(plans):
    """Novice above HF is 222-225 MHz and a slice of 23cm -- not 6m, 2m or 70cm."""
    for band_name in ("6m", "2m", "70cm", "33cm"):
        band = next(b for b in plans["us"]["bands"] if b["band"] == band_name)
        assert all("novice" not in s["classes"] for s in band["segments"]), band_name
    for band_name in ("1.25m", "23cm"):
        band = next(b for b in plans["us"]["bands"] if b["band"] == band_name)
        assert any("novice" in s["classes"] for s in band["segments"]), band_name


def test_us_advanced_sits_between_general_and_extra(plans):
    """Advanced gets phone below General's edge but not Extra's bottom slice."""
    plan = plans["us"]
    twenty = next(b for b in plan["bands"] if b["band"] == "20m")

    extra_only = [s for s in twenty["segments"] if s["classes"] == ["extra"]]
    assert any(s["khz"] == [14150, 14175] for s in extra_only)

    adv = [s for s in twenty["segments"] if s["classes"] == ["advanced", "extra"]]
    assert any(s["khz"] == [14175, 14225] for s in adv)

    gen = [s for s in twenty["segments"] if s["classes"] == ["general", "advanced", "extra"]]
    assert any(s["khz"] == [14225, 14350] for s in gen)


def test_us_advanced_never_has_a_privilege_extra_lacks(plans):
    """Extra is a superset of every other class."""
    plan = plans["us"]
    for band in plan["bands"]:
        for segment in band["segments"]:
            if segment["classes"] != ["extra"]:
                assert "extra" in segment["classes"], f"{band['band']} {segment['khz']}"


def test_us_technician_is_a_superset_of_novice_on_hf(plans):
    """Technicians received the Novice HF segments; nothing should be Novice-only there."""
    for band in plans["us"]["bands"]:
        if band["band"] in ("1.25m", "23cm"):
            continue  # Novice VHF differs from Technician's; not a superset there.
        for segment in band["segments"]:
            if "novice" in segment["classes"]:
                assert "technician" in segment["classes"], f"{band['band']} {segment['khz']}"


def test_us_technician_has_no_160m(plans):
    """A real privilege boundary, and an easy one to get wrong."""
    band = next(b for b in plans["us"]["bands"] if b["band"] == "160m")
    assert all("technician" not in s["classes"] for s in band["segments"])


def test_us_technician_hf_is_cw_only_below_10m(plans):
    """Technician HF below 10m is CW only -- 80m, 40m and 15m novice segments."""
    for band_name in ("80m", "40m", "15m"):
        band = next(b for b in plans["us"]["bands"] if b["band"] == band_name)
        tech = [s for s in band["segments"] if "technician" in s["classes"]]
        assert tech, band_name
        assert all(s["modes"] == ["CW"] for s in tech), band_name


def test_us_thirty_metres_has_no_phone(plans):
    """30m is CW and digital only. Showing phone there would be a real error."""
    band = next(b for b in plans["us"]["bands"] if b["band"] == "30m")
    assert all("Phone" not in s["modes"] for s in band["segments"])


def test_us_extra_reaches_the_bottom_of_the_cw_bands(plans):
    """Extra gets the exclusive bottom slice; General starts 25 kHz up."""
    for band_name, edge in (("80m", 3500), ("40m", 7000), ("20m", 14000), ("15m", 21000)):
        band = next(b for b in plans["us"]["bands"] if b["band"] == band_name)
        bottom = [s for s in band["segments"] if s["khz"][0] == edge]
        assert bottom, band_name
        assert all(s["classes"] == ["extra"] for s in bottom), band_name


def test_us_sixty_metres_is_channelized(plans):
    band = next(b for b in plans["us"]["bands"] if b["band"] == "60m")
    assert band.get("channelized") is True
    assert len(band["segments"]) == 5
    # Channels are single frequencies, not ranges.
    assert all(s["khz"][0] == s["khz"][1] for s in band["segments"])


def test_us_technician_has_every_vhf_and_up_band(plans):
    for band_name in ("6m", "2m", "1.25m", "70cm", "33cm", "23cm"):
        band = next(b for b in plans["us"]["bands"] if b["band"] == band_name)
        assert any("technician" in s["classes"] for s in band["segments"]), band_name

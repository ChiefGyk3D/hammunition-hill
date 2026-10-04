# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The repeaters panel's filter logic, run under node against a real snapshot.

The filters live in the browser by design (nothing the operator filters for is
sent to the server), so the only place to prove them is the browser's own
module. ``web/lib/repeaters.js`` is pure functions with no DOM and no storage,
which is what makes this possible: the panel passes in rows and a filter
object, and gets rows back.

The rows come from the same snapshot the page reads, built by the collector's
own ``build_data`` from the fixture documents, so a field renamed on one side
fails here rather than on screen.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import repeaters_docs as docs

from hammunition_hill import repeaters

ROOT = Path(__file__).resolve().parents[1]
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")

DRIVER = """
import {{
  filterRows, facets, mhz, offsetLabel, bearingLabel, kmLabel, DEFAULT_FILTERS,
}} from "{lib}";

const data = {data};
const rows = data.rows;
const calls = (list) => list.map((r) => r.callsign);
const out = {{}};

out.all = calls(filterRows(rows, DEFAULT_FILTERS));
out.band2m = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, bands: ["2m"] }}));
out.band70 = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, bands: ["70cm"] }}));
out.bandNone = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, bands: ["6m"] }}));
out.modeFM = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, modes: ["FM"] }}));
out.modeDMR = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, modes: ["DMR"] }}));
out.sourceOpen = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, source: "open-repeater-json" }}));
// W1CCC is kept from the open layer and also listed by RepeaterBook.
out.sourceRb = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, source: "repeaterbook-api" }}));
out.within50 = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, withinKm: 50 }}));
out.within155 = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, withinKm: 155 }}));
const combined = {{ ...DEFAULT_FILTERS, band: "2m", withinKm: 155, modes: ["FM"] }};
out.combo = calls(filterRows(rows, combined));
out.noKm = calls(filterRows(
  rows.map((r) => ({{ ...r, km: null }})), {{ ...DEFAULT_FILTERS, withinKm: 50 }}));
out.noKmUnfiltered = calls(filterRows(rows.map((r) => ({{ ...r, km: null }})), DEFAULT_FILTERS));
out.facets = facets(rows);
out.labels = {{
  mhz: [mhz(146940000), mhz(442000000), mhz(0)],
  offset: [-600000, 600000, 5000000, null, 0].map(offsetLabel),
  bearing: [bearingLabel(62.2), bearingLabel(224.3), bearingLabel(null)],
  km: [kmLabel(153.2), kmLabel(14.04), kmLabel(null)],
}};
out.mutated = rows.length;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js():
    data = repeaters.build_data(docs.listing_document(), docs.station_document())
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "run.mjs"
        driver.write_text(
            DRIVER.format(lib=ROOT / "web/lib/repeaters.js", data=json.dumps(data)),
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=60
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# Nearest first, as the collector sorts: Hartford (5 km), Providence (108),
# Boston (153.2), New York (156.7).
def test_no_filter_keeps_every_row_in_the_collectors_order(js):
    assert js["all"] == ["W1CCC", "W1DDD", "W1AAA", "W1BBB"]


def test_band_filter(js):
    assert sorted(js["band2m"]) == ["W1AAA", "W1BBB", "W1CCC"]
    assert js["band70"] == ["W1DDD"]
    assert js["bandNone"] == []


def test_mode_filter(js):
    assert sorted(js["modeFM"]) == ["W1AAA", "W1BBB", "W1CCC"]
    assert js["modeDMR"] == ["W1DDD"]


def test_source_filter_matches_the_kept_source_and_the_also_list(js):
    assert sorted(js["sourceOpen"]) == ["W1AAA", "W1CCC", "W1DDD"]
    assert sorted(js["sourceRb"]) == ["W1BBB", "W1CCC"]


def test_within_n_km(js):
    assert js["within50"] == ["W1CCC"]
    # Boston is 153.2 km out, New York 156.7: 155 keeps one and not the other.
    assert "W1AAA" in js["within155"] and "W1BBB" not in js["within155"]


def test_filters_combine(js):
    assert sorted(js["combo"]) == ["W1AAA", "W1CCC"]


def test_a_distance_filter_cannot_judge_a_row_with_no_distance(js):
    """No grid square means no distance; 'within 50 km' then keeps nothing
    rather than pretending every repeater is near."""
    assert js["noKm"] == []
    assert len(js["noKmUnfiltered"]) == 4


def test_facets_list_what_is_present_low_band_first(js):
    assert js["facets"]["bands"] == ["2m", "70cm"]
    assert js["facets"]["modes"] == ["FM", "DMR"]
    assert js["facets"]["sources"] == ["open-repeater-json", "repeaterbook-api"]


def test_labels(js):
    assert js["labels"]["mhz"] == ["146.940", "442.000", "—"]
    assert js["labels"]["offset"] == ["-0.6", "+0.6", "+5", "—", "simplex"]
    assert js["labels"]["bearing"] == ["62° ENE", "224° SW", "—"]
    assert js["labels"]["km"] == ["153 km", "14.0 km", "—"]


def test_filtering_does_not_change_the_rows_it_is_given(js):
    assert js["mutated"] == 4


# --- the chosen centre ---------------------------------------------------------
CENTRE_DRIVER = """
import {
  parseGrid, parseLatLon, parseCentre, withCentre, distanceKm, bearingDeg,
  coverageNote, loadCentre, saveCentre, clearCentre, centreFromPoint, CENTRE_KEY,
} from "__LIB__";

const rows = __ROWS__;
const out = {};

out.grid = Object.fromEntries(
  ["FN31", "FN31pr", "fn31PR", "FN", "FN3", "FN31p", "FN31pr99", "ZZ99", "FN31yy", "", "12ab", null]
    .map((g) => [String(g), parseGrid(g)]));
out.latlon = Object.fromEntries(
  ["41.7, -72.7", "41.7 -72.7", "-33.9,151.2", "91, 0", "0, 181", "41.7", "a, b",
   "1,2,3", "N41 W72"]
    .map((t) => [t, parseLatLon(t)]));
out.centre = {
  grid: parseCentre("FN42"), point: parseCentre("40.5, -73.5"),
  name: parseCentre("Boston"), empty: parseCentre(""),
};

// The station's centre, as the collector computes it (FN31pr).
const here = parseGrid("FN31pr");
const moved = withCentre(rows, here);
out.moved = moved.map((r) => [r.callsign, r.km, r.bearing]);
out.rawInputUntouched = rows.every((r) => r.__marker === undefined);
out.sortedFromSydney = withCentre(rows, centreFromPoint(-33.9, 151.2)).map((r) => r.callsign);
out.meridian = [distanceKm(0, 0, 1, 0), bearingDeg(0, 0, 1, 0)];
out.equator = [distanceKm(0, 0, 0, 90), bearingDeg(0, 0, 0, 90)];

const sydney = withCentre(rows, centreFromPoint(-33.9, 151.2));
out.farNote = coverageNote(sydney, null);
out.nearNote = coverageNote(moved, null);
out.tightNote = coverageNote(moved, 4);
out.noRowsNote = coverageNote([], null);
out.noDistanceNote = coverageNote(rows.map((r) => ({ ...r, km: null })), null);

const make = () => {
  const map = new Map();
  return {
    map,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  };
};
const store = make();
out.empty = loadCentre(store);
saveCentre(store, parseCentre("FN42"));
out.roundTrip = loadCentre(store);
out.key = [...store.map.keys()];
store.setItem(CENTRE_KEY, "{not json");
out.garbage = loadCentre(store);
store.setItem(CENTRE_KEY, JSON.stringify({ kind: "point", lat: 95, lon: 0 }));
out.outOfRange = loadCentre(store);
saveCentre(store, centreFromPoint(10, 20));
clearCentre(store);
out.cleared = loadCentre(store);
const broken = {
  getItem() { throw new Error("blocked"); },
  setItem() { throw new Error("blocked"); },
  removeItem() { throw new Error("blocked"); },
};
saveCentre(broken, centreFromPoint(1, 2));
clearCentre(broken);
out.blocked = loadCentre(broken);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def centre_js():
    data = repeaters.build_data(docs.listing_document(), docs.station_document())
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "centre.mjs"
        driver.write_text(
            CENTRE_DRIVER.replace("__LIB__", str(ROOT / "web/lib/repeaters.js")).replace(
                "__ROWS__", json.dumps(data["rows"])
            ),
            encoding="utf-8",
        )
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=60
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_four_and_six_character_grids_are_parsed_to_their_centre(centre_js):
    g = centre_js["grid"]
    assert g["FN31"]["lat"] == pytest.approx(41.5) and g["FN31"]["lon"] == pytest.approx(-73.0)
    assert g["FN31pr"]["lat"] == pytest.approx(41.7291667, abs=1e-6)
    assert g["FN31pr"]["lon"] == pytest.approx(-72.7083333, abs=1e-6)
    assert g["fn31PR"]["grid"] == "FN31pr"


@pytest.mark.parametrize(
    "bad", ["FN", "FN3", "FN31p", "FN31pr99", "ZZ99", "FN31yy", "", "12ab", "null"]
)
def test_grids_that_are_not_four_or_six_characters_are_rejected(centre_js, bad):
    assert centre_js["grid"][bad] is None


def test_the_js_grid_agrees_with_geo_py():
    from hammunition_hill.geo import grid_to_latlon

    assert grid_to_latlon("FN31") == pytest.approx((41.5, -73.0))


def test_latitude_longitude_pairs(centre_js):
    p = centre_js["latlon"]
    assert p["41.7, -72.7"] == {"lat": 41.7, "lon": -72.7}
    assert p["41.7 -72.7"] == {"lat": 41.7, "lon": -72.7}
    assert p["-33.9,151.2"] == {"lat": -33.9, "lon": 151.2}
    for bad in ("91, 0", "0, 181", "41.7", "a, b", "1,2,3", "N41 W72"):
        assert p[bad] is None


def test_a_place_name_is_not_a_centre(centre_js):
    c = centre_js["centre"]
    assert c["grid"]["kind"] == "grid" and c["grid"]["label"] == "FN42"
    assert c["point"]["kind"] == "point" and c["point"]["label"] == "40.500, -73.500"
    assert c["name"] is None and c["empty"] is None


def test_recomputing_from_the_station_centre_gives_the_hand_computed_pairs(centre_js):
    """Boston 153.2 km at 62.2 and New York 156.7 km at 224.3, the pairs the
    collector's own test uses, now through the browser's copy of the maths."""
    by = {call: (km, brg) for call, km, brg in centre_js["moved"]}
    assert by["W1AAA"][0] == pytest.approx(153.2, abs=0.1)
    assert by["W1AAA"][1] == pytest.approx(62.2, abs=0.1)
    assert by["W1BBB"][0] == pytest.approx(156.7, abs=0.1)
    assert by["W1BBB"][1] == pytest.approx(224.3, abs=0.1)
    assert [m[0] for m in centre_js["moved"]] == ["W1CCC", "W1DDD", "W1AAA", "W1BBB"]


def test_the_browser_numbers_agree_with_the_collectors_to_a_tenth(centre_js):
    data = repeaters.build_data(docs.listing_document(), docs.station_document())
    for row, (call, km, brg) in zip(data["rows"], centre_js["moved"], strict=True):
        assert row["callsign"] == call
        assert km == pytest.approx(row["km"], abs=0.1)
        assert brg == pytest.approx(row["bearing"], abs=0.1)


def test_exact_arcs(centre_js):
    assert centre_js["meridian"] == [pytest.approx(111.195, abs=0.001), 0]
    assert centre_js["equator"] == [pytest.approx(10007.557, abs=0.01), 90]


def test_rows_re_sort_from_a_new_centre_and_the_input_is_not_changed(centre_js):
    from hammunition_hill.geo import distance_km

    data = repeaters.build_data(docs.listing_document(), docs.station_document())
    want = [
        r["callsign"]
        for r in sorted(data["rows"], key=lambda r: distance_km(-33.9, 151.2, r["lat"], r["lon"]))
    ]
    assert centre_js["sortedFromSydney"] == want
    assert centre_js["rawInputUntouched"] is True


def test_a_far_centre_says_the_data_is_only_what_was_imported(centre_js):
    note = centre_js["farNote"]
    assert "not worldwide" in note
    assert "hammunition maps repeaters fetch-repeaterbook --state CODE" in note
    assert "hammunition maps repeaters import --from-osm" in note
    assert "nearest repeater" in note


def test_coverage_note_cases(centre_js):
    assert centre_js["nearNote"] is None
    assert "beyond 4 km" in centre_js["tightNote"]
    assert centre_js["noRowsNote"].startswith("No repeaters on this machine")
    assert "fetch-repeaterbook" in centre_js["noRowsNote"]
    # Rows with no distance at all are treated as no coverage, not as near.
    assert centre_js["noDistanceNote"].startswith("No repeaters")


def test_the_centre_round_trips_through_storage(centre_js):
    assert centre_js["empty"] is None
    assert centre_js["roundTrip"]["kind"] == "grid"
    assert centre_js["roundTrip"]["label"] == "FN42"
    assert centre_js["roundTrip"]["lat"] == pytest.approx(42.5)
    assert centre_js["key"] == ["hh.repeaters.centre"]
    assert centre_js["garbage"] is None
    assert centre_js["outOfRange"] is None
    assert centre_js["cleared"] is None
    assert centre_js["blocked"] is None


def test_the_centre_is_never_sent_anywhere():
    """Browser-only: nothing in the lib or the panel may fetch, beacon or open a
    socket, and the collector snapshot never learns the centre."""
    for rel_path in ("web/lib/repeaters.js", "web/panels/repeaters/panel.js"):
        text = (ROOT / rel_path).read_text(encoding="utf-8")
        for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource"):
            assert forbidden not in text, f"{rel_path} uses {forbidden}"


# --- modes, bands and digital details (hammunition-hill #84) --------------------
MODES_DRIVER = """
import {
  filterRows, facets, shortcutModes, toggle, digitalDetails, modeText, DEFAULT_FILTERS,
  loadFilters, saveFilters, FILTERS_KEY, DIGITAL_MODES, ANALOG_MODES,
} from "__LIB__";

const data = __DATA__;
const legacy = __LEGACY__;
const rows = data.rows;
const calls = (list) => list.map((r) => r.callsign).sort();
const f = (over) => calls(filterRows(rows, { ...DEFAULT_FILTERS, ...over }));
const out = {};

out.facets = facets(rows);
out.legacyFacets = facets(legacy.rows);
out.dmr = f({ modes: ["DMR"] });
out.dmrOrYsf = f({ modes: ["DMR", "YSF"] });
out.bands2mAnd23 = f({ bands: ["2m", "23cm"] });
out.dmr70 = f({ modes: ["DMR"], bands: ["70cm"] });
out.dmrWithin = f({ modes: ["DMR"], withinKm: 110 });
out.digital = f({ modes: shortcutModes("digital", out.facets.modes) });
out.analog = f({ modes: shortcutModes("analog", out.facets.modes) });
out.shortcutSets = [
  shortcutModes("digital", out.facets.modes), shortcutModes("analog", out.facets.modes),
  shortcutModes("analog", ["DMR"]), shortcutModes("nonsense", ["FM"])];
out.toggled = [toggle([], "DMR"), toggle(["DMR"], "FM"), toggle(["DMR", "FM"], "DMR")];
out.noModeRows = f({ modes: ["DMR"] }).length;
const unknown = rows.map((r) => ({ ...r, modes: [] }));
out.unknownKept = filterRows(unknown, DEFAULT_FILTERS).length;
out.unknownFiltered = filterRows(unknown, { ...DEFAULT_FILTERS, modes: ["FM"] }).length;
out.vocab = [DIGITAL_MODES, ANALOG_MODES];

const by = (call) => rows.find((r) => r.callsign === call);
out.details = Object.fromEntries(
  ["W1DDD", "W1EEE", "W1FFF", "W1GGG", "W1HHH", "W1LLL", "W1AAA", "W1III"]
    .map((c) => [c, digitalDetails(by(c))]));
out.hostile = digitalDetails(
  { digital: { dmr_color_code: "", ysf_dgid: null, nope: "x", p25_nac: " 293 " } });
out.noDigital = [
  digitalDetails({}), digitalDetails({ digital: null }), digitalDetails({ digital: "x" })];
out.modeText = [modeText(by("W1EEE")), modeText({ modes: [], mode: "Analog" }), modeText({})];

const make = () => {
  const map = new Map();
  return { map, getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)), removeItem: (k) => map.delete(k) };
};
const store = make();
out.defaults = loadFilters(store);
saveFilters(store, { bands: ["2m"], modes: ["DMR", "M17"], source: "osm", withinKm: 50 });
out.roundTrip = loadFilters(store);
out.key = [...store.map.keys()];
const garbage = {};
for (const [name, raw] of Object.entries({
  notJson: "{nope", array: "[1,2]", string: '"x"', number: "7",
  wrongTypes: JSON.stringify({ bands: "2m", modes: 5, source: 3, withinKm: "far" }),
  unknownModes: JSON.stringify(
    { modes: ["DMR", "FANCY", 4, "<b>x</b>"], bands: ["2m", {}, "999m999"] }),
  negative: JSON.stringify({ withinKm: -5 }),
  huge: JSON.stringify({ bands: Array(500).fill("2m"), source: "x".repeat(5000) }),
})) {
  store.setItem(FILTERS_KEY, raw);
  garbage[name] = loadFilters(store);
}
out.garbage = garbage;
const blocked = { getItem() { throw new Error("no"); }, setItem() { throw new Error("no"); },
  removeItem() { throw new Error("no"); } };
saveFilters(blocked, { bands: ["2m"], modes: [], source: null, withinKm: null });
out.blocked = loadFilters(blocked);
out.rowsUntouched = rows.length;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def modes_js():
    data = repeaters.build_data(docs.modes_listing_document(), docs.station_document())
    legacy = repeaters.build_data(docs.legacy_listing_document(), docs.station_document())
    source = (
        MODES_DRIVER.replace("__LIB__", str(ROOT / "web/lib/repeaters.js"))
        .replace("__DATA__", json.dumps(data))
        .replace("__LEGACY__", json.dumps(legacy))
    )
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "modes.mjs"
        driver.write_text(source, encoding="utf-8")
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=60
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


ALL_CALLS = sorted(
    [
        "W1AAA",
        "W1BBB",
        "W1CCC",
        "W1DDD",
        "W1EEE",
        "W1FFF",
        "W1GGG",
        "W1HHH",
        "W1III",
        "W1JJJ",
        "W1KKK",
        "W1LLL",
    ]
)


def test_the_chip_set_is_what_the_snapshot_holds_in_vocabulary_order(modes_js):
    assert modes_js["facets"]["modes"] == [
        "FM",
        "DMR",
        "D-STAR",
        "YSF",
        "P25",
        "NXDN",
        "M17",
        "TETRA",
        "ATV",
    ]
    assert modes_js["facets"]["bands"] == ["2m", "1.25m", "70cm", "23cm"]


def test_each_chip_carries_its_count(modes_js):
    assert modes_js["facets"]["modeCounts"] == {
        "FM": 5,
        "DMR": 2,
        "D-STAR": 1,
        "YSF": 1,
        "P25": 1,
        "NXDN": 1,
        "M17": 1,
        "TETRA": 1,
        "ATV": 1,
    }
    assert modes_js["facets"]["bandCounts"] == {"2m": 5, "1.25m": 1, "70cm": 5, "23cm": 1}
    assert sum(modes_js["facets"]["bandCounts"].values()) == len(ALL_CALLS)


def test_a_legacy_snapshot_offers_no_mode_chips(modes_js):
    assert modes_js["legacyFacets"]["modes"] == []
    assert modes_js["legacyFacets"]["modeCounts"] == {}


def test_modes_are_multi_select_and_a_row_matches_any_of_them(modes_js):
    assert modes_js["dmr"] == ["W1DDD", "W1LLL"]
    assert modes_js["dmrOrYsf"] == ["W1DDD", "W1FFF", "W1LLL"]


def test_bands_are_multi_select(modes_js):
    assert modes_js["bands2mAnd23"] == sorted(
        ["W1AAA", "W1BBB", "W1CCC", "W1EEE", "W1LLL", "W1KKK"]
    )


def test_modes_and_bands_compose_by_and_with_within_km(modes_js):
    assert modes_js["dmr70"] == ["W1DDD"]
    # Providence is 108 km from the grid centre; Manchester NH is farther.
    assert modes_js["dmrWithin"] == ["W1DDD"]


def test_the_shortcuts_pick_the_digital_and_the_analog_chips(modes_js):
    digital, analog, analog_only_dmr, nonsense = modes_js["shortcutSets"]
    assert digital == ["DMR", "D-STAR", "YSF", "P25", "NXDN", "M17", "TETRA"]
    assert analog == ["FM", "ATV"]
    assert analog_only_dmr == [] and nonsense == []
    assert modes_js["vocab"] == [digital, ["FM", "ATV"]]
    assert "W1KKK" in modes_js["analog"] and "W1DDD" not in modes_js["analog"]
    assert "W1KKK" not in modes_js["digital"] and "W1DDD" in modes_js["digital"]
    # A mixed FM + digital repeater is reachable either way.
    assert "W1LLL" in modes_js["digital"] and "W1LLL" in modes_js["analog"]


def test_toggle_adds_removes_and_never_mutates(modes_js):
    assert modes_js["toggled"] == [["DMR"], ["DMR", "FM"], ["FM"]]


def test_a_row_of_unknown_mode_is_shown_unfiltered_and_hidden_by_a_mode_chip(modes_js):
    assert modes_js["unknownKept"] == len(ALL_CALLS)
    assert modes_js["unknownFiltered"] == 0


def test_digital_details_read_in_plain_words(modes_js):
    d = modes_js["details"]
    assert d["W1DDD"] == ["DMR CC 1, Brandmeister"]
    assert d["W1EEE"] == ["D-STAR module B, gateway W1EEE G"]
    assert d["W1FFF"] == ["YSF DG-ID 00"]
    assert d["W1GGG"] == ["P25 NAC 293"]
    assert d["W1HHH"] == ["NXDN RAN 1"]
    assert d["W1LLL"] == ["DMR CC 3, ID 310999"]


def test_absent_details_show_nothing_not_a_placeholder(modes_js):
    assert modes_js["details"]["W1AAA"] == []
    assert modes_js["details"]["W1III"] == []
    assert modes_js["hostile"] == ["P25 NAC 293"]
    assert modes_js["noDigital"] == [[], [], []]


def test_the_mode_column_prefers_the_vocabulary_and_falls_back_to_the_text(modes_js):
    assert modes_js["modeText"] == ["FM, D-STAR", "Analog", ""]


def test_filters_round_trip_through_storage(modes_js):
    assert modes_js["key"] == ["hh.repeaters.filters"]
    assert modes_js["roundTrip"] == {
        "bands": ["2m"],
        "modes": ["DMR", "M17"],
        "source": "osm",
        "withinKm": 50,
    }
    assert modes_js["defaults"] == {"bands": [], "modes": [], "source": None, "withinKm": None}


def test_garbage_in_storage_falls_back_to_defaults_field_by_field(modes_js):
    empty = modes_js["defaults"]
    garbage = modes_js["garbage"]
    for name in ("notJson", "array", "string", "number", "wrongTypes", "negative"):
        assert garbage[name] == empty, name
    assert garbage["unknownModes"]["modes"] == ["DMR"]
    assert garbage["unknownModes"]["bands"] == ["2m"]
    assert len(garbage["huge"]["bands"]) <= 20 and garbage["huge"]["source"] is None
    assert modes_js["blocked"] == empty


def test_filtering_still_does_not_change_the_rows(modes_js):
    assert modes_js["rowsUntouched"] == len(ALL_CALLS)

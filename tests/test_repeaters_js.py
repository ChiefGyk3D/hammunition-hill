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
out.band2m = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, band: "2m" }}));
out.band70 = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, band: "70cm" }}));
out.bandNone = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, band: "6m" }}));
out.modeFM = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, mode: "FM" }}));
out.modeDMR = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, mode: "DMR" }}));
out.sourceOpen = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, source: "open-repeater-json" }}));
// W1CCC is kept from the open layer and also listed by RepeaterBook.
out.sourceRb = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, source: "repeaterbook-api" }}));
out.within50 = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, withinKm: 50 }}));
out.within155 = calls(filterRows(rows, {{ ...DEFAULT_FILTERS, withinKm: 155 }}));
const combined = {{ ...DEFAULT_FILTERS, band: "2m", withinKm: 155, mode: "FM" }};
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

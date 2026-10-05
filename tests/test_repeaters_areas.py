# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The repeaters panel follows the engine's active areas (#87).

Python half: the collector keeps the active layers' rows in ``rows`` (which the
map reads) and the other areas' in ``other_rows``, and an engine that predates
areas keeps today's behaviour. JS half: the chips, the per-session add and drop,
the localStorage round trip and the centre fallback, under node against a
snapshot the collector built from the fixture.
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


def build(listing=None, **kwargs):
    return repeaters.build_data(
        docs.areas_listing_document() if listing is None else listing,
        docs.station_document(),
        **kwargs,
    )


def calls(rows):
    return sorted(r["callsign"] for r in rows)


def test_only_the_active_layers_rows_are_in_rows():
    data = build()
    assert calls(data["rows"]) == ["K1OPN", "W8OHA", "W8OHB"]
    assert data["has_areas"] is True


def test_the_other_areas_rows_are_carried_apart_for_the_chips():
    data = build()
    assert calls(data["other_rows"]) == ["W4FLA", "W8MIA"]


def test_layers_carry_their_area_and_whether_it_is_active():
    layers = {layer["id"]: layer for layer in build()["layers"]}
    assert layers["repeaterbook-OH"]["area"] == "OH" and layers["repeaterbook-OH"]["active"]
    assert layers["repeaterbook-MI"]["area"] == "MI" and not layers["repeaterbook-MI"]["active"]
    assert layers["open-repeater"]["area"] is None and layers["open-repeater"]["active"]


def test_areas_are_listed_in_layer_order_with_a_middle_from_their_rows():
    areas = build()["areas"]
    assert [a["area"] for a in areas] == ["OH", "MI", "FL"]
    assert [a["active"] for a in areas] == [True, False, False]
    oh = areas[0]
    assert oh["layers"] == ["repeaterbook-OH"] and oh["rows"] == 2
    assert oh["centre"]["lat"] == pytest.approx(40.7303, abs=1e-3)
    assert oh["centre"]["lon"] == pytest.approx(-82.3466, abs=1e-3)


def test_an_area_with_no_rows_has_no_middle():
    listing = docs.areas_listing_document()
    listing["rows"] = [r for r in listing["rows"] if r["layer"] != "repeaterbook-FL"]
    fl = next(a for a in build(listing)["areas"] if a["area"] == "FL")
    assert fl["centre"] is None


def test_the_row_cut_keeps_active_rows_ahead_of_the_other_areas():
    data = build(max_rows=2)
    assert data["truncated"] == 1
    assert len(data["rows"]) == 2
    assert calls(data["other_rows"]) == ["W4FLA", "W8MIA"]


def test_the_other_areas_rows_are_capped_on_their_own(monkeypatch):
    monkeypatch.setattr(repeaters, "INACTIVE_MAX_ROWS", 1)
    assert len(build()["other_rows"]) == 1


def test_an_engine_that_predates_areas_keeps_every_row_and_hides_the_chips():
    data = build(docs.pre_areas_listing_document())
    assert data["has_areas"] is False
    assert calls(data["rows"]) == ["K1OPN", "W4FLA", "W8MIA", "W8OHA", "W8OHB"]
    assert data["other_rows"] == [] and data["areas"] == []
    assert all(layer["active"] for layer in data["layers"])


def test_the_existing_fixture_has_no_areas_and_is_unchanged_by_them():
    data = repeaters.build_data(docs.listing_document(), docs.station_document())
    assert data["has_areas"] is False and data["other_rows"] == []


def test_the_bands_and_modes_offered_include_the_other_areas_rows():
    listing = docs.areas_listing_document()
    next(r for r in listing["rows"] if r["callsign"] == "W4FLA").update(
        output_hz=442_000_000, band="70cm", modes=["DMR"]
    )
    data = build(listing)
    assert "70cm" in data["bands"] and "DMR" in data["modes"]


def test_the_public_view_withholds_other_area_rows_and_the_areas_of_withheld_layers():
    public = repeaters.public_data(build())
    # Every state layer is RepeaterBook's, so no area survives and nothing of
    # the other areas' rows is left, only the count.
    assert public["other_rows"] == []
    assert public["areas"] == []
    assert calls(public["rows"]) == ["K1OPN"]
    assert public["withheld"] == 4
    text = json.dumps(public).lower()
    assert "repeaterbook" not in text and "w8mia" not in text and "w4fla" not in text


def test_the_public_view_keeps_an_area_whose_layer_is_not_withheld():
    listing = docs.areas_listing_document()
    for layer in listing["layers"]:
        if layer["id"] == "repeaterbook-MI":
            layer.update(
                id="open-MI", personal_use=False, sources=["open-repeater-json"], name="MI open"
            )
            layer["description"] = docs.OPEN_CREDIT
    for r in listing["rows"]:
        if r["layer"] == "repeaterbook-MI":
            r.update(personal_use=False, source="open-repeater-json", layer="open-MI")
    public = repeaters.public_data(build(listing))
    assert [a["area"] for a in public["areas"]] == ["MI"]
    assert calls(public["other_rows"]) == ["W8MIA"]


# --- the browser half --------------------------------------------------------
node = shutil.which("node")
needs_node = pytest.mark.skipif(node is None, reason="node not installed")

DRIVER = """
import {
  areaChips, toggleArea, rowsForAreas, areaCentre, AREA_FAR_KM, AREAS_KEY,
  sanitizeAreaChoice, loadAreaChoice, saveAreaChoice, viewRows, areaCutNote,
} from "__LIB__";

const data = __DATA__;
const old = __OLD__;
const calls = (list) => list.map((r) => r.callsign).sort();
const on = (chips) => chips.filter((c) => c.on).map((c) => c.area);
const out = {};

const none = sanitizeAreaChoice(null);
out.none = none;
out.chips = areaChips(data, none).map((c) => [c.area, c.engine, c.on, c.rows]);
out.defaultRows = calls(rowsForAreas(data, none));

let c = toggleArea(none, "MI", data);          // add an area the engine has not activated
out.addMI = [c, on(areaChips(data, c)), calls(rowsForAreas(data, c))];
const withMI = c;
c = toggleArea(c, "MI", data);                 // and take it off again
out.addDropMI = [c, on(areaChips(data, c))];
c = toggleArea(none, "OH", data);              // drop an area the engine has active
out.dropOH = [c, on(areaChips(data, c)), calls(rowsForAreas(data, c))];
c = toggleArea(c, "OH", data);                 // and put it back
out.dropAddOH = [c, on(areaChips(data, c))];
out.unknownArea = toggleArea(none, "ZZ", data);
out.input = [none, withMI].map((x) => JSON.stringify(x));
const all3 = toggleArea(toggleArea(none, "MI", data), "FL", data);
out.allThree = on(areaChips(data, all3));

// The centre fallback.
out.fallback = areaCentre(data, none);
out.afterDropOH = areaCentre(data, toggleArea(none, "OH", data));
out.stationChosen = areaCentre(data, { ...none, station: true });
const near = { ...data, station: { lat: 40.0, lon: -83.0 } };
out.nearStation = areaCentre(near, none);
const noStation = { ...data, station: null };
out.noStation = areaCentre(noStation, none);
out.noAreasOn = areaCentre(data, toggleArea(none, "OH", data));
out.far = AREA_FAR_KM;

// An engine that predates areas.
out.oldChips = areaChips(old, none);
out.oldRows = calls(rowsForAreas(old, none));
out.oldCentre = areaCentre(old, none);

// What the map draws is viewRows: the same set as the table.
const mapCalls = (choice, chosen = null) => calls(viewRows(data, chosen, choice).rows);
out.map = {
  default: mapCalls(none),
  addMI: mapCalls(toggleArea(none, "MI", data)),
  addMIFL: mapCalls(toggleArea(toggleArea(none, "MI", data), "FL", data)),
  dropOH: mapCalls(toggleArea(none, "OH", data)),
  dropAfterAdd: mapCalls(toggleArea(toggleArea(none, "MI", data), "MI", data)),
};
out.mapSameAsTable =
  JSON.stringify(mapCalls(withMI)) === JSON.stringify(calls(rowsForAreas(data, withMI)));
out.mapCentre = [
  viewRows(data, null, none).centre.label,
  viewRows(data, { kind: "point", lat: 1, lon: 2, label: "x" }, none).centre.label,
  viewRows(data, null, { ...none, station: true }).centre,
];
out.cut = [areaCutNote(data), areaCutNote({ ...data, other_truncated: 120 }),
  areaCutNote({ ...old, other_truncated: 120 })];

// Storage.
const make = () => {
  const map = new Map();
  return { map, getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)), removeItem: (k) => map.delete(k) };
};
const store = make();
out.empty = loadAreaChoice(store);
saveAreaChoice(store, { add: ["MI"], drop: ["OH"], station: true });
out.roundTrip = loadAreaChoice(store);
out.key = [...store.map.keys()];
const garbage = {};
for (const [name, raw] of Object.entries({
  notJson: "{nope", array: "[1]", string: '"x"', number: "7",
  wrongTypes: JSON.stringify({ add: "MI", drop: 5, station: "yes" }),
  hostile: JSON.stringify({ add: ["MI", "<b>x</b>", 4, "a".repeat(40), "../x"], drop: ["OH"] }),
  both: JSON.stringify({ add: ["MI"], drop: ["MI", "OH"] }),
  huge: JSON.stringify({ add: Array.from({ length: 900 }, (_, i) => "A" + i) }),
})) {
  store.setItem(AREAS_KEY, raw);
  garbage[name] = loadAreaChoice(store);
}
out.garbage = garbage;
out.hugeLength = garbage.huge.add.length;
const blocked = { getItem() { throw new Error("no"); }, setItem() { throw new Error("no"); } };
saveAreaChoice(blocked, { add: ["MI"], drop: [], station: false });
out.blocked = loadAreaChoice(blocked);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js():
    if node is None:
        pytest.skip("node not installed")
    data = build()
    old = build(docs.pre_areas_listing_document())
    source = (
        DRIVER.replace("__LIB__", str(ROOT / "web/lib/repeaters.js"))
        .replace("__DATA__", json.dumps(data))
        .replace("__OLD__", json.dumps(old))
    )
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "areas.mjs"
        driver.write_text(source, encoding="utf-8")
        result = subprocess.run(  # noqa: S603
            [node, str(driver)], capture_output=True, text=True, timeout=60
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


NONE = {"add": [], "drop": [], "station": False}


@needs_node
def test_the_chip_set_is_every_area_in_the_snapshot_with_the_engines_active_ones_on(js):
    assert js["chips"] == [["OH", True, True, 2], ["MI", False, False, 1], ["FL", False, False, 1]]
    assert js["defaultRows"] == ["K1OPN", "W8OHA", "W8OHB"]


@needs_node
def test_adding_an_area_shows_its_rows_for_this_session_and_changes_no_input(js):
    choice, shown, rows = js["addMI"]
    assert choice == {**NONE, "add": ["MI"]}
    assert shown == ["OH", "MI"]
    assert rows == ["K1OPN", "W8MIA", "W8OHA", "W8OHB"]
    assert js["input"][0] == json.dumps(NONE).replace(" ", "")


@needs_node
def test_dropping_an_area_hides_its_rows_and_a_layer_with_no_area_stays(js):
    choice, shown, rows = js["dropOH"]
    assert choice == {**NONE, "drop": ["OH"]}
    assert shown == []
    assert rows == ["K1OPN"]


@needs_node
def test_pressing_a_chip_twice_is_back_where_it_was(js):
    assert js["addDropMI"][0] == NONE
    assert js["dropAddOH"][0] == NONE
    assert js["allThree"] == ["OH", "MI", "FL"]
    assert js["unknownArea"] == NONE


@needs_node
def test_the_station_far_from_the_first_active_area_centres_on_the_area_and_says_so(js):
    fallback = js["fallback"]
    assert fallback["centre"]["kind"] == "area" and fallback["centre"]["label"] == "OH"
    assert fallback["centre"]["lat"] == pytest.approx(40.7303, abs=1e-3)
    message = fallback["message"]
    assert "middle of OH" in message and "300 km" in message and "STATION" in message


@needs_node
def test_the_station_is_kept_when_it_is_near_when_chosen_or_when_no_area_is_on(js):
    assert js["far"] == 300
    assert js["nearStation"] == {"centre": None, "message": ""}
    assert js["stationChosen"] == {"centre": None, "message": ""}
    assert js["afterDropOH"] == {"centre": None, "message": ""}


@needs_node
def test_no_station_at_all_also_centres_on_the_area_and_says_why(js):
    assert js["noStation"]["centre"]["label"] == "OH"
    assert "no station position is set" in js["noStation"]["message"]


@needs_node
def test_an_engine_without_areas_has_no_chips_no_filtering_and_no_fallback(js):
    assert js["oldChips"] == []
    assert js["oldRows"] == ["K1OPN", "W4FLA", "W8MIA", "W8OHA", "W8OHB"]
    assert js["oldCentre"] == {"centre": None, "message": ""}


@needs_node
def test_the_choice_round_trips_through_storage_under_its_own_key(js):
    assert js["empty"] == NONE
    assert js["roundTrip"] == {"add": ["MI"], "drop": ["OH"], "station": True}
    assert js["key"] == ["hh.repeaters.areas"]


@needs_node
def test_garbage_in_storage_costs_the_field_never_the_panel(js):
    g = js["garbage"]
    for name in ("notJson", "array", "string", "number", "wrongTypes"):
        assert g[name] == NONE, name
    assert g["hostile"] == {"add": ["MI"], "drop": ["OH"], "station": False}
    assert g["both"] == {"add": ["MI"], "drop": ["OH"], "station": False}
    assert js["hugeLength"] <= 100
    assert js["blocked"] == NONE


def test_the_panel_never_writes_to_the_engine_and_the_commands_are_unchanged():
    assert repeaters.LIST_ARGV == ("maps", "repeaters", "list", "--json")
    assert repeaters.STATION_ARGV == ("station", "show", "--json")


@needs_node
def test_a_chip_add_puts_that_areas_markers_on_the_map_and_a_drop_removes_them(js):
    m = js["map"]
    assert m["default"] == ["K1OPN", "W8OHA", "W8OHB"]
    assert m["addMI"] == ["K1OPN", "W8MIA", "W8OHA", "W8OHB"]
    assert m["addMIFL"] == ["K1OPN", "W4FLA", "W8MIA", "W8OHA", "W8OHB"]
    assert m["dropOH"] == ["K1OPN"]
    assert m["dropAfterAdd"] == m["default"]
    assert js["mapSameAsTable"] is True


@needs_node
def test_the_map_and_the_table_share_one_centre_rule(js):
    assert js["mapCentre"] == ["OH", "x", None]


@needs_node
def test_the_cap_line_appears_only_when_the_other_areas_were_cut(js):
    assert js["cut"][0] == "" and js["cut"][2] == ""
    assert "cut at 3000 rows" in js["cut"][1] and "hammunition maps activate" in js["cut"][1]


def test_the_map_panel_draws_what_the_table_shows():
    source = (ROOT / "web/panels/map/panel.js").read_text(encoding="utf-8")
    assert "viewRows(" in source and "loadAreaChoice" in source


def test_the_collector_counts_the_other_areas_rows_it_cut(monkeypatch):
    monkeypatch.setattr(repeaters, "INACTIVE_MAX_ROWS", 1)
    assert build()["other_truncated"] == 1
    assert (
        build()["other_rows"] and build(docs.pre_areas_listing_document())["other_truncated"] == 0
    )

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

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Aurora, NOAA scales, and SWPC alerts.

The aurora reduction is the interesting one: a quarter-million-point grid has to
become something a browser can draw, without losing the thing operators care
about -- the equatorward edge of the oval.
"""

import json

import httpx
import pytest

from hammunition_hill.config import SourceConfig
from hammunition_hill.sources.aurora import MAX_CELLS, VISIBLE_THRESHOLD, AuroraSource
from hammunition_hill.sources.base import FetchError
from hammunition_hill.sources.swpc_text import NoaaScalesSource, SwpcAlertsSource


async def run(source, body, content_type="application/json"):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": content_type})
    )
    cfg = SourceConfig(id="t", kind=source.kind, url="https://services.example/x")
    async with httpx.AsyncClient(transport=transport) as client:
        return await source.fetch(client, cfg)


def ovation(cells):
    """SWPC's shape: [longitude 0..359 east, latitude, probability]."""
    return json.dumps(
        {
            "Observation Time": "2026-08-26T23:00:00Z",
            "Forecast Time": "2026-08-26T23:30:00Z",
            "coordinates": cells,
        }
    )


# --- aurora reduction ----------------------------------------------------
async def test_the_grid_reduces_to_ovals_and_cells():
    body = ovation([[0, 65, 40], [0, 70, 60], [4, 66, 30], [0, -65, 25]])
    data = await run(AuroraSource(), body)
    assert data["peak_probability"] == 60
    assert data["north_oval"]
    assert data["south_oval"]


async def test_the_oval_is_the_equatorward_edge():
    """65 north and 75 north both have aurora; the edge is 65."""
    body = ovation([[0, 65, 20], [0, 75, 90], [0, 80, 90]])
    data = await run(AuroraSource(), body)
    assert data["north_oval"] == [[0, 65]]


def _south(data):
    return dict(data["south_oval"])


async def test_the_southern_oval_edge_is_the_least_negative():
    body = ovation([[0, -80, 90], [0, -62, 20]])
    data = await run(AuroraSource(), body)
    assert _south(data)[0] == -62


async def test_faint_cells_are_dropped_from_the_oval():
    """Below the visibility threshold there is nothing worth drawing."""
    body = ovation([[0, 55, VISIBLE_THRESHOLD - 1], [0, 70, 50]])
    data = await run(AuroraSource(), body)
    assert data["north_oval"] == [[0, 70]]


async def test_eastern_longitudes_become_signed():
    """SWPC counts 0..359 east; everything else here uses -180..180."""
    body = ovation([[350, 70, 50]])
    data = await run(AuroraSource(), body)
    assert data["north_oval"][0][0] == -10


async def test_a_quiet_grid_produces_no_oval():
    body = ovation([[0, 70, 0], [10, 65, 1]])
    data = await run(AuroraSource(), body)
    assert data["north_oval"] == []
    assert data["cells"] == []
    assert data["peak_probability"] == 1


async def test_cells_are_capped_and_the_strongest_kept():
    """A browser must not be handed a quarter of a million points."""
    grid = []
    for lon in range(0, 360, 4):
        for lat in range(-90, 90, 2):
            grid.append([lon, lat, 90 if lat > 60 else 10])
    data = await run(AuroraSource(), ovation(grid))

    assert len(data["cells"]) <= MAX_CELLS
    assert data["truncated"] is True
    # The cap keeps the strongest, so the intense polar cells must survive.
    assert any(c[2] == 90 for c in data["cells"])


async def test_cells_come_back_in_a_stable_order():
    grid = [[lon, 70, 50] for lon in range(0, 40, 4)]
    data = await run(AuroraSource(), ovation(grid))
    assert data["cells"] == sorted(data["cells"], key=lambda c: (c[0], c[1]))


async def test_timestamps_are_preserved():
    data = await run(AuroraSource(), ovation([[0, 70, 50]]))
    assert data["observed_at"] == "2026-08-26T23:00:00Z"
    assert data["forecast_at"] == "2026-08-26T23:30:00Z"


async def test_a_grid_with_no_coordinates_is_an_error():
    with pytest.raises(FetchError, match="no coordinates grid"):
        await run(AuroraSource(), '{"Observation Time": "x"}')


async def test_malformed_rows_are_skipped():
    body = ovation([[0, 70], [0, 72, 50], []])
    data = await run(AuroraSource(), body)
    assert data["peak_probability"] == 50


# --- NOAA scales ---------------------------------------------------------
SCALES_BODY = json.dumps(
    {
        "-1": {
            "R": {"Scale": "1", "Text": "Minor"},
            "S": {"Scale": None, "Text": "none"},
            "G": {"Scale": "0", "Text": "none"},
        },
        "0": {
            "R": {"Scale": "2", "Text": "Moderate", "DateStamp": "2026-08-26"},
            "S": {"Scale": None, "Text": "none"},
            "G": {"Scale": "4", "Text": "Severe"},
        },
    }
)


async def test_scales_read_today_not_yesterday():
    data = await run(NoaaScalesSource(), SCALES_BODY)
    assert data["scales"]["R"]["scale"] == 2
    assert data["scales"]["G"]["scale"] == 4


async def test_a_null_scale_reads_as_zero():
    """SWPC sends null rather than 0 when nothing is happening."""
    data = await run(NoaaScalesSource(), SCALES_BODY)
    assert data["scales"]["S"]["scale"] == 0
    assert data["scales"]["S"]["label"] == "S0"


async def test_scale_severity_maps_onto_three_levels():
    data = await run(NoaaScalesSource(), SCALES_BODY)
    assert data["scales"]["S"]["level"] == "good"
    assert data["scales"]["R"]["level"] == "warn"
    assert data["scales"]["G"]["level"] == "critical"


async def test_worst_scale_is_reported():
    data = await run(NoaaScalesSource(), SCALES_BODY)
    assert data["worst"] == 4


async def test_scales_reject_a_list():
    with pytest.raises(FetchError, match="expected an object"):
        await run(NoaaScalesSource(), "[]")


# --- SWPC alerts ---------------------------------------------------------
ALERTS_BODY = json.dumps(
    [
        {
            "product_id": "K04A",
            "issue_datetime": "2026-08-26 22:00:00",
            "message": "ALERT: Geomagnetic K-index of 4\n\nThreshold Reached: 22:00 UTC",
        },
        {"product_id": "WARK05", "issue_datetime": "2026-08-26 21:00:00", "message": "   "},
    ]
)


async def test_alerts_take_the_first_line_as_the_headline():
    data = await run(SwpcAlertsSource(), ALERTS_BODY)
    assert data["alerts"][0]["headline"] == "ALERT: Geomagnetic K-index of 4"


async def test_empty_alerts_are_dropped():
    data = await run(SwpcAlertsSource(), ALERTS_BODY)
    assert data["count"] == 1


async def test_long_alert_text_is_bounded():
    body = json.dumps([{"product_id": "X", "message": "A" * 5000}])
    data = await run(SwpcAlertsSource(), body)
    assert len(data["alerts"][0]["message"]) <= 400


async def test_alerts_reject_an_object():
    with pytest.raises(FetchError, match="expected a list"):
        await run(SwpcAlertsSource(), "{}")

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""NOAA SWPC products.

Written after the planetary K product changed shape under a running collector.
SWPC had served it as a header row followed by positional rows; it now serves a
list of objects. The parser indexed positionally, raised `KeyError` rather than
`FetchError`, and that escaped the TaskGroup and took the whole dashboard down
with it. Two defects, tested in two places: the shape here, the blast radius in
test_collector_resilience.py.
"""

import httpx
import pytest

from hammunition_hill.config import SourceConfig
from hammunition_hill.sources.base import FetchError
from hammunition_hill.sources.swpc import SwpcSource


async def run(body, product, *, url="https://services.swpc.noaa.gov/x.json"):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": "application/json"})
    )
    cfg = SourceConfig(id="t", kind="swpc", url=url, options={"product": product})
    async with httpx.AsyncClient(transport=transport) as client:
        return await SwpcSource().fetch(client, cfg)


# --- planetary K ---------------------------------------------------------
# The shape SWPC serves as of 2026-08-27.
KP_OBJECTS = """[
 {"time_tag":"2026-08-27T00:00:00","Kp":3.33,"a_running":18,"station_count":8},
 {"time_tag":"2026-08-27T03:00:00","Kp":5.67,"a_running":40,"station_count":8}
]"""

# The shape it served before that, kept working on purpose.
KP_ROWS = """[
 ["time_tag","Kp","a_running","station_count"],
 ["2026-08-27T00:00:00","3.33","18","8"],
 ["2026-08-27T03:00:00","5.67","40","8"]
]"""


@pytest.mark.parametrize("body", [KP_OBJECTS, KP_ROWS], ids=["objects", "header-rows"])
async def test_both_kindex_shapes_read_the_same(body):
    """The format change must be invisible above the parser."""
    data = await run(body, "planetary_k_index")

    assert data["kp"] == pytest.approx(5.67)
    assert data["observed_at"] == "2026-08-27T03:00:00"
    assert data["storm_level"] == "G1"
    assert [h["kp"] for h in data["history"]] == pytest.approx([3.33, 5.67])


async def test_kindex_reads_the_newest_row_not_the_first():
    """`kp` is the current reading, and these series run oldest-first."""
    data = await run(KP_OBJECTS, "planetary_k_index")
    assert data["kp"] != pytest.approx(3.33)


async def test_an_empty_kindex_series_is_a_fetch_error():
    """A source failure must arrive as FetchError, which degrades one panel."""
    with pytest.raises(FetchError):
        await run("[]", "planetary_k_index")


async def test_a_header_with_no_data_rows_is_a_fetch_error():
    with pytest.raises(FetchError):
        await run('[["time_tag","Kp"]]', "planetary_k_index")


async def test_kindex_carries_a_gauge():
    data = await run(KP_OBJECTS, "planetary_k_index")
    assert data["gauge"]["level"]


# --- F10.7 ---------------------------------------------------------------
# services.swpc.noaa.gov/products/10cm-flux-30-day.json, oldest first.
FLUX = """[
 {"time_tag":"2026-08-26T20:00:00","flux":143},
 {"time_tag":"2026-08-27T20:00:00","flux":122}
]"""


async def test_f107_reads_the_last_row_as_current():
    """The configured endpoint is oldest-first, and this is why it has to be.

    /json/f107_cm_flux.json is also live and serves newest-first. Pointing this
    parser at it would report the oldest sample in the window as today's flux --
    a wrong number rather than a missing one. config.example.toml says so too.
    """
    data = await run(FLUX, "f107_flux")

    assert data["flux"] == 122
    assert data["observed_at"] == "2026-08-27T20:00:00"


async def test_an_empty_flux_series_is_a_fetch_error():
    with pytest.raises(FetchError):
        await run("[]", "f107_flux")


# --- protons -------------------------------------------------------------
# The real feed carries eight energies interleaved; these are the two that
# matter for picking the wrong one.
PROTONS = """[
 {"time_tag":"2026-08-28T23:00:00Z","energy":">=1 MeV","flux":10.44},
 {"time_tag":"2026-08-28T23:00:00Z","energy":">=10 MeV","flux":0.19},
 {"time_tag":"2026-08-28T23:05:00Z","energy":">=1 MeV","flux":11.02},
 {"time_tag":"2026-08-28T23:05:00Z","energy":">=10 MeV","flux":0.2547}
]"""


async def test_protons_reads_the_ten_mev_channel():
    """The S scale is defined on >=10 MeV, and the channels differ by decades.

    >=1 MeV was 10.44 pfu in this sample while >=10 MeV was 0.25. Taking the
    wrong row does not fail, it just reports a quiet day as an S1 storm.
    """
    data = await run(PROTONS, "proton_flux")

    assert data["flux"] == pytest.approx(0.2547)
    assert data["observed_at"] == "2026-08-28T23:05:00Z"


async def test_protons_report_the_day_peak():
    data = await run(PROTONS, "proton_flux")
    assert data["peak_today"]["flux"] == pytest.approx(0.2547)


async def test_a_feed_without_the_ten_mev_channel_is_a_fetch_error():
    """Better one dead dial than a dial drawn on whatever row came first."""
    only_low = '[{"time_tag":"2026-08-28T23:00:00Z","energy":">=1 MeV","flux":10.44}]'
    with pytest.raises(FetchError):
        await run(only_low, "proton_flux")


async def test_protons_carry_a_gauge_on_the_proton_scale():
    data = await run(PROTONS, "proton_flux")
    assert data["gauge"]["id"] == "protons"
    assert data["gauge"]["level"] == "good"  # 0.25 pfu is background


# --- product routing -----------------------------------------------------
async def test_an_unknown_product_names_the_valid_ones():
    """The config error a typo produces should say what to type instead."""
    with pytest.raises(FetchError) as exc:
        await run("[]", "not_a_product")

    assert "planetary_k_index" in str(exc.value)

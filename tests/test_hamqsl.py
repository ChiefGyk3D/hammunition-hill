# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""HamQSL XML parsing, including the ordering property the UI depends on."""

import httpx
import pytest

from hammunition_hill.config import SourceConfig
from hammunition_hill.sources.hamqsl import HamQslSource

SAMPLE = """<?xml version="1.0"?>
<solar><solardata>
<updated>26 Aug 2026 1500 GMT</updated>
<solarflux>168</solarflux><aindex>7</aindex><kindex>3</kindex>
<sunspots>112</sunspots><xray>C2.1</xray><geomagfield>QUIET</geomagfield>
<calculatedconditions>
<band name="80m-40m" time="day">Fair</band>
<band name="80m-40m" time="night">Good</band>
<band name="30m-20m" time="day">Good</band>
<band name="30m-20m" time="night">Good</band>
<band name="12m-10m" time="day">Poor</band>
<band name="12m-10m" time="night">Poor</band>
</calculatedconditions>
<calculatedvhfconditions>
<phenomenon name="vhf-aurora" location="northern_hemi">Band Closed</phenomenon>
</calculatedvhfconditions>
</solardata></solar>
"""


async def fetch(body=SAMPLE, status=200):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text=body, headers={"content-type": "text/xml"})
    )
    cfg = SourceConfig(id="hamqsl", kind="hamqsl", url="https://www.hamqsl.com/solarxml.php")
    async with httpx.AsyncClient(transport=transport) as client:
        return await HamQslSource().fetch(client, cfg)


async def test_scalar_fields():
    data = await fetch()
    assert data["solarflux"] == "168"
    assert data["sunspots"] == "112"
    assert data["geomagfield"] == "QUIET"


async def test_band_conditions_keep_publication_order():
    """Low band to high, the way an operator reads them.

    Snapshots serialize with sorted keys, so a mapping here would come back out
    alphabetically -- 12m-10m ahead of 80m-40m. A list keeps order as data.
    """
    data = await fetch()
    assert [b["band"] for b in data["hf_conditions"]] == ["80m-40m", "30m-20m", "12m-10m"]


async def test_band_entries_pair_day_and_night():
    first = (await fetch())["hf_conditions"][0]
    assert first == {"band": "80m-40m", "day": "Fair", "night": "Good"}


async def test_vhf_conditions_parsed():
    data = await fetch()
    assert data["vhf_conditions"][0]["phenomenon"] == "vhf-aurora"


async def test_missing_solardata_is_an_error():
    from hammunition_hill.sources.base import FetchError

    with pytest.raises(FetchError, match="no <solardata>"):
        await fetch("<solar></solar>")


async def test_malformed_xml_is_an_error():
    from hammunition_hill.sources.base import FetchError

    with pytest.raises(FetchError, match="XML parse failed"):
        await fetch("<solar><unclosed>")

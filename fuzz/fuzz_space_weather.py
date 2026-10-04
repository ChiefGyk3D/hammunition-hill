# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fuzz the space-weather feeds: NOAA SWPC JSON, the scales and alerts, HamQSL XML, the ionosonde roster.

Each source's real `fetch` runs against an `httpx.MockTransport` that answers
with the fuzzer's bytes, so `get_bounded`, the JSON or XML decoder and the
reducer are all exercised. `FetchError` is the contract for a feed that is not
what it should be, and the one thing a source may raise.
"""

import sys

import atheris

with atheris.instrument_imports():
    from hammunition_hill.config import SourceConfig
    from hammunition_hill.sources.base import FetchError
    from hammunition_hill.sources.hamqsl import HamQslSource
    from hammunition_hill.sources.ionosonde import IonosondeSource
    from hammunition_hill.sources.swpc import SwpcSource
    from hammunition_hill.sources.swpc_text import NoaaScalesSource, SwpcAlertsSource

import _support

_URL = "https://services.swpc.noaa.gov/fuzz.json"

_TARGETS = [
    (SwpcSource(), SourceConfig("k", "swpc", _URL, options={"product": "planetary_k_index"})),
    (SwpcSource(), SourceConfig("f", "swpc", _URL, options={"product": "f107_flux"})),
    (SwpcSource(), SourceConfig("x", "swpc", _URL, options={"product": "xray_flux"})),
    (SwpcSource(), SourceConfig("p", "swpc", _URL, options={"product": "proton_flux"})),
    (NoaaScalesSource(), SourceConfig("s", "noaa_scales", _URL)),
    (SwpcAlertsSource(), SourceConfig("a", "swpc_alerts", _URL)),
    (HamQslSource(), SourceConfig("h", "hamqsl", _URL)),
    (IonosondeSource(), SourceConfig("i", "ionosonde", _URL)),
]

_JSON_KEYS = [
    "time_tag",
    "Kp",
    "flux",
    "energy",
    "0",
    "-1",
    "R",
    "S",
    "G",
    "Scale",
    "Text",
    "DateStamp",
    "product_id",
    "issue_datetime",
    "message",
    "station",
    "code",
    "name",
    "latitude",
    "longitude",
    "time",
    "cs",
    "fof2",
    "mufd",
    "md",
    "hmf2",
    "tec",
    "source",
]
_JSON_STRINGS = ["0.1-0.8nm", ">=10 MeV", "2026-01-01T00:00:00", "2026-01-01T00:00:00Z", "Kp"]
_XML_TAGS = [
    "solar",
    "solardata",
    "sunspots",
    "kindex",
    "aindex",
    "xray",
    "solarflux",
    "solarwind",
    "signalnoise",
    "geomagfield",
    "calculatedconditions",
    "band",
    "calculatedvhfconditions",
    "phenomenon",
    "updated",
    "protonflux",
    "fof2",
]

SEEDS = [
    b"",
    b'\x00[{"time_tag":"2026-01-01T00:00:00","Kp":2.33}]',
    b'\x00[["time_tag","Kp"],["2026-01-01T00:00:00","2.33"]]',
    b'\x01[{"time_tag":"2026-01-01T00:00:00","flux":120}]',
    b'\x02[{"energy":"0.1-0.8nm","flux":1e-6,"time_tag":"t"}]',
    b'\x03[{"energy":">=10 MeV","flux":0.25,"time_tag":"t"}]',
    b'\x04{"0":{"R":{"Scale":"0","Text":"none"},"S":{"Scale":"1"},"G":{"Scale":"2"},"DateStamp":"d"}}',
    b'\x05[{"product_id":"A1","issue_datetime":"t","message":"Space Weather Message\\r\\nWATCH"}]',
    b"\x06<solar><solardata><sunspots>10</sunspots><kindex>2</kindex></solardata></solar>",
    b'\x07[{"station":{"code":"X","latitude":"38","longitude":"-77"},"time":"2026-01-01T00:00:00","cs":90,"fof2":5.0}]',
]


def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    source, cfg = _TARGETS[fdp.ConsumeIntInRange(0, len(_TARGETS) - 1)]
    if fdp.ConsumeBool():
        if isinstance(source, HamQslSource):
            body = _support.xml_text(fdp, _XML_TAGS).encode()
        else:
            body = _support.json_text(fdp, _JSON_KEYS, _JSON_STRINGS).encode()
    else:
        body = fdp.ConsumeBytes(fdp.remaining_bytes())
    try:
        _support.fetch_with_body(source, cfg, body)
    except FetchError:
        pass


if __name__ == "__main__":
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()

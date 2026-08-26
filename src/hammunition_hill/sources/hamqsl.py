"""HamQSL solar XML (N0NBH).

This is the feed behind the solar banner on half the dashboards in the hobby.
The banner is a PNG, which means the numbers are unreadable to software and the
layout is someone else's. We take the XML instead and render it ourselves, which
also means one fewer third-party image load from every operator's browser.

Parsed with defusedxml: this is remote XML, and stock ElementTree will happily
follow entity declarations into places we do not want to go.
"""

from __future__ import annotations

from typing import Any

import httpx
from defusedxml import ElementTree as DefusedET

from ..config import SourceConfig
from .base import FetchError, get_bounded

# Scalars we lift verbatim from <solardata>.
_FIELDS = (
    "solarflux",
    "aindex",
    "kindex",
    "sunspots",
    "xray",
    "heliumline",
    "protonflux",
    "electonflux",  # HamQSL's spelling, not a typo on our side
    "aurora",
    "solarwind",
    "magneticfield",
    "geomagfield",
    "signalnoise",
    "fof2",
    "latdegree",
    "updated",
)


def _text(node: Any, tag: str) -> str | None:
    found = node.find(tag)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


class HamQslSource:
    kind = "hamqsl"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        response = await get_bounded(client, cfg.url)
        try:
            root = DefusedET.fromstring(response.text)
        except Exception as exc:  # defusedxml raises several distinct types
            raise FetchError(f"{cfg.url}: XML parse failed ({exc})") from exc

        data = root.find("solardata")
        if data is None:
            raise FetchError(f"{cfg.url}: no <solardata> element")

        result: dict[str, Any] = {field: _text(data, field) for field in _FIELDS}

        # HF band conditions, as an ordered list rather than a mapping. HamQSL
        # emits these low band to high, which is how operators read them -- and
        # snapshots serialize with sorted keys, so a dict here would come back
        # out alphabetically, 12m-10m ahead of 80m-40m. Order is data.
        bands: list[dict[str, str]] = []
        index: dict[str, dict[str, str]] = {}
        calculated = data.find("calculatedconditions")
        if calculated is not None:
            for band in calculated.findall("band"):
                name = band.get("name")
                when = band.get("time")
                if not (name and when and band.text):
                    continue
                if name not in index:
                    index[name] = {"band": name}
                    bands.append(index[name])
                index[name][when] = band.text.strip()
        result["hf_conditions"] = bands

        vhf: list[dict[str, str]] = []
        vhf_index: dict[str, dict[str, str]] = {}
        calc_vhf = data.find("calculatedvhfconditions")
        if calc_vhf is not None:
            for phen in calc_vhf.findall("phenomenon"):
                name = phen.get("name")
                where = phen.get("location")
                if not (name and where and phen.text):
                    continue
                if name not in vhf_index:
                    vhf_index[name] = {"phenomenon": name}
                    vhf.append(vhf_index[name])
                vhf_index[name][where] = phen.text.strip()
        result["vhf_conditions"] = vhf

        return result

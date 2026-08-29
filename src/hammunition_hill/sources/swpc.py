# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""NOAA Space Weather Prediction Center.

SWPC publishes clean, unauthenticated JSON and is the authoritative source for
the numbers every ham dashboard shows. We normalize each product down to the few
fields a panel actually renders, rather than passing multi-megabyte time series
to the browser.

Related: ChiefGyk3D/solarstorm_scout already ingests several of these products.
Where the parsing logic converges it is worth extracting into a shared library
rather than maintaining two readings of the same feed.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import SourceConfig
from ..severity import classify
from .base import FetchError, get_bounded


def _kindex_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Normalize either shape SWPC has served this product in.

    It used to be a header row followed by positional rows, CSV rendered as
    JSON. It is now a list of objects. Both are accepted because the change
    happened without notice and could happen back, and because the difference
    is three lines here against a dead panel in the field.
    """
    if not rows:
        raise FetchError("planetary K index: no data rows")
    if isinstance(rows[0], dict):
        return rows
    header, *data = rows
    if not data:
        raise FetchError("planetary K index: no data rows")
    idx = {name: i for i, name in enumerate(header)}
    time_at, kp_at = idx.get("time_tag", 0), idx.get("Kp", 1)
    return [{"time_tag": row[time_at], "Kp": row[kp_at]} for row in data]


def _latest_kindex(rows: list[Any]) -> dict[str, Any]:
    data = _kindex_rows(rows)
    latest = data[-1]
    kp = float(latest["Kp"])
    return {
        "kp": kp,
        "observed_at": latest["time_tag"],
        # G-scale is what tells an operator whether to care.
        "storm_level": _g_scale(kp),
        "history": [{"at": row["time_tag"], "kp": float(row["Kp"])} for row in data[-24:]],
    }


def _g_scale(kp: float) -> str:
    if kp >= 9:
        return "G5"
    if kp >= 8:
        return "G4"
    if kp >= 7:
        return "G3"
    if kp >= 6:
        return "G2"
    if kp >= 5:
        return "G1"
    return "quiet"


def _latest_f107(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise FetchError("F10.7 flux: no data rows")
    latest = rows[-1]
    return {
        "flux": latest.get("flux"),
        "observed_at": latest.get("time_tag"),
        "history": [{"at": r.get("time_tag"), "flux": r.get("flux")} for r in rows[-30:]],
    }


def _latest_xray(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """GOES long-band X-ray flux, reduced to the current class and the day's peak."""
    long_band = [r for r in rows if r.get("energy") == "0.1-0.8nm"]
    if not long_band:
        raise FetchError("GOES X-ray: no long-band samples")
    latest = long_band[-1]
    peak = max(long_band, key=lambda r: r.get("flux") or 0.0)
    return {
        "flux": latest.get("flux"),
        "class": _xray_class(latest.get("flux")),
        "observed_at": latest.get("time_tag"),
        "peak_today": {
            "flux": peak.get("flux"),
            "class": _xray_class(peak.get("flux")),
            "at": peak.get("time_tag"),
        },
    }


def _xray_class(flux: float | None) -> str:
    """Watts/m^2 to the A/B/C/M/X letter class hams actually talk in."""
    if not flux or flux <= 0:
        return "A0.0"
    for letter, floor in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7)):
        if flux >= floor:
            return f"{letter}{flux / floor:.1f}"
    return f"A{flux / 1e-8:.1f}"


def _latest_protons(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """GOES integral proton flux at >=10 MeV.

    That channel specifically, because it is the one NOAA's S scale is defined
    on and the one "proton flux" means unqualified. The same feed carries eight
    energies from >=1 MeV to >=500 MeV, and they differ by orders of magnitude:
    >=1 MeV read 10.4 pfu while >=10 MeV read 0.25 on the day this was written.
    Taking the wrong row would not fail, it would just be wrong.
    """
    channel = [r for r in rows if r.get("energy") == ">=10 MeV"]
    if not channel:
        raise FetchError("GOES protons: no >=10 MeV samples")
    latest = channel[-1]
    peak = max(channel, key=lambda r: r.get("flux") or 0.0)
    return {
        "flux": latest.get("flux"),
        "observed_at": latest.get("time_tag"),
        "peak_today": {"flux": peak.get("flux"), "at": peak.get("time_tag")},
    }


_PRODUCTS = {
    "planetary_k_index": _latest_kindex,
    "f107_flux": _latest_f107,
    "xray_flux": _latest_xray,
    "proton_flux": _latest_protons,
}

# Which severity scale a product is drawn on, and the field that feeds it.
# This was a loop testing `product.startswith(scale_id[:3])` against a list of
# explicit pairs -- the prefix arm matched by coincidence ("f107_flux" against
# "sfi" did not, so the pair list carried it), and adding a fourth product was
# a coin flip on which arm caught it. A dict says the same thing once.
_GAUGES = {
    "planetary_k_index": ("kindex", "kp"),
    "f107_flux": ("sfi", "flux"),
    "xray_flux": ("xray", "flux"),
    "proton_flux": ("protons", "flux"),
}


class SwpcSource:
    kind = "swpc"

    async def fetch(self, client: httpx.AsyncClient, cfg: SourceConfig) -> Any:
        product = cfg.options.get("product")
        if product not in _PRODUCTS:
            raise FetchError(
                f"source {cfg.id!r}: options.product must be one of "
                f"{', '.join(sorted(_PRODUCTS))}, got {product!r}"
            )
        response = await get_bounded(client, cfg.url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError(f"{cfg.url}: response was not JSON ({exc})") from exc
        data = {"product": product, **_PRODUCTS[product](payload)}

        # Attach a dial where the product maps onto a known scale.
        scale = _GAUGES.get(product)
        if scale is not None:
            gauge = classify(scale[0], data.get(scale[1]))
            if gauge is not None:
                data["gauge"] = gauge

        return data

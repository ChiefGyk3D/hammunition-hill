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
from .base import FetchError, get_bounded


def _latest_kindex(rows: list[list[Any]]) -> dict[str, Any]:
    """SWPC planetary K is a header row followed by [time, kp, ...] rows."""
    if len(rows) < 2:
        raise FetchError("planetary K index: no data rows")
    header, *data = rows
    idx = {name: i for i, name in enumerate(header)}
    latest = data[-1]
    kp = float(latest[idx.get("Kp", 1)])
    return {
        "kp": kp,
        "observed_at": latest[idx.get("time_tag", 0)],
        # G-scale is what tells an operator whether to care.
        "storm_level": _g_scale(kp),
        "history": [
            {"at": row[idx.get("time_tag", 0)], "kp": float(row[idx.get("Kp", 1)])}
            for row in data[-24:]
        ],
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


_PRODUCTS = {
    "planetary_k_index": _latest_kindex,
    "f107_flux": _latest_f107,
    "xray_flux": _latest_xray,
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
        return {"product": product, **_PRODUCTS[product](payload)}

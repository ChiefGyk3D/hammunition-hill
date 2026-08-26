# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The NCDXF/IARU International Beacon Project schedule.

Eighteen beacons around the world share five frequencies on a strict
three-minute cycle. Because the schedule is fixed and synchronised to UTC, you
can work out exactly which beacon is transmitting on which band at any instant
**with no network at all** -- it is arithmetic on the clock.

That makes this the most useful offline panel in the dashboard. Tune 14.100,
watch which beacon should be on, and whether you hear it tells you more about
whether the band is open to that part of the world than any prediction does.

Each beacon sends for ten seconds: its callsign, then four one-second dashes at
100 W, 10 W, 1 W and 100 mW. Which dashes you can still hear is a rough
signal-strength measurement you can take by ear.

The schedule is the schedule. Individual beacons go off the air for maintenance
or for good, so "should be transmitting" is not "is transmitting" -- which is
part of what makes listening informative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

SLOT_SECONDS = 10
CYCLE_SECONDS = 180  # 18 beacons x 10 seconds


@dataclass(frozen=True)
class Beacon:
    index: int
    callsign: str
    location: str
    grid: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Band:
    index: int
    name: str
    khz: float


# Transmission order. Beacon i starts its 20m slot at slot i, and moves up one
# band every ten seconds, so at any moment five beacons are on the air at once.
BEACONS: tuple[Beacon, ...] = (
    Beacon(0, "4U1UN", "United Nations, New York", "FN30as", 40.75, -73.97),
    Beacon(1, "VE8AT", "Inuvik, NT, Canada", "CP38gh", 68.38, -133.72),
    Beacon(2, "W6WX", "Mt Umunhum, California", "CM97bd", 37.15, -121.90),
    Beacon(3, "KH6RS", "Maui, Hawaii", "BL10ts", 20.79, -156.46),
    Beacon(4, "ZL6B", "Masterton, New Zealand", "RE78tw", -40.95, 175.61),
    Beacon(5, "VK6RBP", "Rolystone, Australia", "OF87av", -32.10, 116.05),
    Beacon(6, "JA2IGY", "Mt Asama, Japan", "PM84jk", 34.45, 136.79),
    Beacon(7, "RR9O", "Novosibirsk, Russia", "NO14kx", 54.98, 82.89),
    Beacon(8, "VR2B", "Hong Kong", "OL72bg", 22.28, 114.16),
    Beacon(9, "4S7B", "Colombo, Sri Lanka", "MJ96wv", 6.91, 79.87),
    Beacon(10, "ZS6DN", "Pretoria, South Africa", "KG33rq", -25.90, 28.28),
    Beacon(11, "5Z4B", "Kikuyu, Kenya", "KI88ks", -1.25, 36.68),
    Beacon(12, "4X6TU", "Tel Aviv, Israel", "KM72jb", 32.05, 34.78),
    Beacon(13, "OH2B", "Lohja, Finland", "KP20eh", 60.25, 24.40),
    Beacon(14, "CS3B", "Madeira", "IM12jr", 32.68, -16.93),
    Beacon(15, "LU4AA", "Buenos Aires, Argentina", "GF05tj", -34.62, -58.38),
    Beacon(16, "OA4B", "Lima, Peru", "FH17mw", -12.05, -77.05),
    Beacon(17, "YV5B", "Caracas, Venezuela", "FJ69cc", 10.42, -66.98),
)

BANDS: tuple[Band, ...] = (
    Band(0, "20m", 14100.0),
    Band(1, "17m", 18110.0),
    Band(2, "15m", 21150.0),
    Band(3, "12m", 24930.0),
    Band(4, "10m", 28200.0),
)


def slot_at(moment: datetime | None = None) -> int:
    """Which of the eighteen ten-second slots the cycle is in, 0..17."""
    moment = (moment or datetime.now(UTC)).astimezone(UTC)
    seconds = moment.hour * 3600 + moment.minute * 60 + moment.second
    return (seconds % CYCLE_SECONDS) // SLOT_SECONDS


def seconds_into_slot(moment: datetime | None = None) -> int:
    moment = (moment or datetime.now(UTC)).astimezone(UTC)
    seconds = moment.hour * 3600 + moment.minute * 60 + moment.second
    return seconds % SLOT_SECONDS


def beacon_on(band: Band | int, moment: datetime | None = None) -> Beacon:
    """Which beacon should be transmitting on a band right now.

    Beacon i is on 20m during slot i and climbs one band every slot, so on band
    b the beacon currently sending is ``slot - b`` wrapped into range.
    """
    band_index = band.index if isinstance(band, Band) else band
    return BEACONS[(slot_at(moment) - band_index) % len(BEACONS)]


def next_slot_for(beacon: Beacon, band: Band | int, moment: datetime | None = None) -> int:
    """Seconds until this beacon next starts on this band."""
    band_index = band.index if isinstance(band, Band) else band
    target = (beacon.index + band_index) % len(BEACONS)
    now_slot = slot_at(moment)
    into = seconds_into_slot(moment)
    slots_away = (target - now_slot) % len(BEACONS)
    return slots_away * SLOT_SECONDS - into if slots_away or into else 0


def schedule(moment: datetime | None = None) -> list[dict[str, object]]:
    """Who is on the air on each band right now."""
    return [
        {
            "band": band.name,
            "khz": band.khz,
            "beacon": beacon_on(band, moment).callsign,
            "index": beacon_on(band, moment).index,
        }
        for band in BANDS
    ]


def export() -> dict[str, object]:
    """The static data the panel needs. The timing it works out itself."""
    return {
        "note": (
            "NCDXF/IARU International Beacon Project. The schedule is fixed and "
            "synchronised to UTC, so this needs no network. Individual beacons "
            "may be off the air."
        ),
        "slot_seconds": SLOT_SECONDS,
        "cycle_seconds": CYCLE_SECONDS,
        "bands": [{"index": b.index, "name": b.name, "khz": b.khz} for b in BANDS],
        "beacons": [
            {
                "index": b.index,
                "callsign": b.callsign,
                "location": b.location,
                "grid": b.grid,
                "lat": b.lat,
                "lon": b.lon,
            }
            for b in BEACONS
        ],
    }

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Callsign to DXCC entity, continent, and approximate coordinates.

Two sources, in order of preference:

1. **cty.dat**, if the operator has one. AD1C's country file is the reference
   every logging program uses, it is updated as entities change, and it is free
   to redistribute -- but it is a moving target, so we read it rather than vendor
   a snapshot that would silently go stale.
2. **A compact built-in table** covering the entities most operators actually
   see. Approximate by construction: it resolves the common cases and will get
   edge cases wrong. Point the config at a cty.dat when accuracy matters.

Which one answered is reported on every lookup, so the UI can say "approximate"
rather than implying a precision it does not have.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Suffixes that describe the operator's situation rather than their location.
_PORTABLE_NOISE = frozenset({"P", "M", "MM", "AM", "QRP", "A", "LH", "B"})

_CALL_CHARS = re.compile(r"^[A-Z0-9/]+$")


@dataclass(frozen=True)
class Entity:
    """A DXCC entity, as far as we can tell."""

    name: str
    prefix: str
    continent: str
    lat: float
    lon: float
    cq_zone: int | None = None
    approximate: bool = False


# --- built-in fallback ----------------------------------------------------
# (prefix, name, continent, lat, lon). Longest prefix wins at lookup time.
# Coordinates are entity centroids, good enough for a beam heading at HF
# distances and not good enough for anything else.
# fmt: off
# ruff format is enabled for this project, and deliberately switched off for the
# data tables below. The formatter's value is consistency in *code*; these are
# *data*, laid out as a table because that is how they are read and reviewed.
# Expanding the prefix table to one field per line adds 414 lines and makes a
# reviewer scroll a screen to check what currently fits in a glance.
_BUILTIN: tuple[tuple[str, str, str, float, float], ...] = (
    ("K", "United States", "NA", 37.5, -91.7), ("W", "United States", "NA", 37.5, -91.7),
    ("N", "United States", "NA", 37.5, -91.7), ("A", "United States", "NA", 37.5, -91.7),
    ("KH6", "Hawaii", "OC", 21.3, -157.8), ("KL", "Alaska", "NA", 61.2, -149.9),
    ("KP4", "Puerto Rico", "NA", 18.2, -66.5), ("KP2", "US Virgin Islands", "NA", 17.7, -64.8),
    ("VE", "Canada", "NA", 51.0, -95.0), ("VA", "Canada", "NA", 51.0, -95.0),
    ("VO", "Canada", "NA", 48.0, -56.0), ("VY", "Canada", "NA", 64.0, -96.0),
    ("XE", "Mexico", "NA", 23.0, -102.0), ("XF4", "Revillagigedo", "NA", 18.8, -110.9),
    ("CO", "Cuba", "NA", 22.0, -80.0), ("CM", "Cuba", "NA", 22.0, -80.0),
    ("HI", "Dominican Republic", "NA", 18.7, -70.2), ("HH", "Haiti", "NA", 19.0, -72.4),
    ("6Y", "Jamaica", "NA", 18.2, -77.5), ("ZF", "Cayman Islands", "NA", 19.3, -81.2),
    ("V3", "Belize", "NA", 17.2, -88.7), ("TG", "Guatemala", "NA", 15.5, -90.3),
    ("YS", "El Salvador", "NA", 13.8, -88.9), ("HR", "Honduras", "NA", 14.8, -86.2),
    ("YN", "Nicaragua", "NA", 12.9, -85.2), ("TI", "Costa Rica", "NA", 9.9, -84.1),
    ("HP", "Panama", "NA", 8.5, -80.0), ("C6", "Bahamas", "NA", 24.7, -77.9),
    ("8P", "Barbados", "NA", 13.2, -59.5), ("9Y", "Trinidad & Tobago", "NA", 10.5, -61.3),
    ("PJ", "Curacao", "SA", 12.2, -69.0), ("P4", "Aruba", "SA", 12.5, -70.0),
    ("FM", "Martinique", "NA", 14.6, -61.0), ("FG", "Guadeloupe", "NA", 16.2, -61.5),
    ("J3", "Grenada", "NA", 12.1, -61.7), ("V4", "St Kitts & Nevis", "NA", 17.3, -62.7),
    ("PY", "Brazil", "SA", -14.0, -52.0), ("PP", "Brazil", "SA", -14.0, -52.0),
    ("PT", "Brazil", "SA", -14.0, -52.0), ("PU", "Brazil", "SA", -14.0, -52.0),
    ("LU", "Argentina", "SA", -34.0, -64.0), ("CE", "Chile", "SA", -33.5, -70.7),
    ("CX", "Uruguay", "SA", -33.0, -56.0), ("ZP", "Paraguay", "SA", -23.4, -58.4),
    ("CP", "Bolivia", "SA", -16.5, -64.6), ("OA", "Peru", "SA", -10.0, -76.0),
    ("HC", "Ecuador", "SA", -1.5, -78.5), ("HK", "Colombia", "SA", 4.0, -73.0),
    ("YV", "Venezuela", "SA", 8.0, -66.0), ("8R", "Guyana", "SA", 5.0, -58.8),
    ("PZ", "Suriname", "SA", 4.0, -56.0), ("FY", "French Guiana", "SA", 4.0, -53.0),
    ("G", "England", "EU", 52.5, -1.5), ("M", "England", "EU", 52.5, -1.5),
    ("2E", "England", "EU", 52.5, -1.5), ("GM", "Scotland", "EU", 56.8, -4.2),
    ("GW", "Wales", "EU", 52.3, -3.6), ("GI", "Northern Ireland", "EU", 54.6, -6.5),
    ("GD", "Isle of Man", "EU", 54.2, -4.5), ("GJ", "Jersey", "EU", 49.2, -2.1),
    ("GU", "Guernsey", "EU", 49.5, -2.6), ("EI", "Ireland", "EU", 53.2, -8.0),
    ("F", "France", "EU", 46.5, 2.5), ("DL", "Germany", "EU", 51.0, 10.0),
    ("DA", "Germany", "EU", 51.0, 10.0), ("DB", "Germany", "EU", 51.0, 10.0),
    ("DD", "Germany", "EU", 51.0, 10.0), ("DF", "Germany", "EU", 51.0, 10.0),
    ("DG", "Germany", "EU", 51.0, 10.0), ("DH", "Germany", "EU", 51.0, 10.0),
    ("DJ", "Germany", "EU", 51.0, 10.0), ("DK", "Germany", "EU", 51.0, 10.0),
    ("DM", "Germany", "EU", 51.0, 10.0), ("DO", "Germany", "EU", 51.0, 10.0),
    ("PA", "Netherlands", "EU", 52.2, 5.5), ("PB", "Netherlands", "EU", 52.2, 5.5),
    ("PD", "Netherlands", "EU", 52.2, 5.5), ("PE", "Netherlands", "EU", 52.2, 5.5),
    ("ON", "Belgium", "EU", 50.7, 4.5), ("LX", "Luxembourg", "EU", 49.8, 6.1),
    ("HB", "Switzerland", "EU", 46.8, 8.2), ("HB0", "Liechtenstein", "EU", 47.1, 9.5),
    ("OE", "Austria", "EU", 47.6, 14.1), ("I", "Italy", "EU", 42.8, 12.6),
    ("IS", "Sardinia", "EU", 40.0, 9.0), ("EA", "Spain", "EU", 40.3, -3.7),
    ("EA6", "Balearic Islands", "EU", 39.6, 2.9), ("EA8", "Canary Islands", "AF", 28.3, -15.7),
    ("EA9", "Ceuta & Melilla", "AF", 35.9, -5.3), ("CT", "Portugal", "EU", 39.5, -8.0),
    ("CT3", "Madeira", "AF", 32.7, -16.9), ("CU", "Azores", "EU", 38.5, -28.2),
    ("SM", "Sweden", "EU", 62.0, 15.0), ("SA", "Sweden", "EU", 62.0, 15.0),
    ("LA", "Norway", "EU", 62.0, 10.0), ("OZ", "Denmark", "EU", 56.0, 10.0),
    ("OH", "Finland", "EU", 62.0, 26.0), ("OH0", "Aland Islands", "EU", 60.2, 20.0),
    ("TF", "Iceland", "EU", 64.9, -19.0), ("OY", "Faroe Islands", "EU", 62.0, -6.8),
    ("OK", "Czech Republic", "EU", 49.8, 15.5), ("OM", "Slovakia", "EU", 48.7, 19.5),
    ("SP", "Poland", "EU", 52.0, 19.5), ("HA", "Hungary", "EU", 47.2, 19.5),
    ("HG", "Hungary", "EU", 47.2, 19.5), ("YO", "Romania", "EU", 45.9, 25.0),
    ("LZ", "Bulgaria", "EU", 42.8, 25.2), ("YU", "Serbia", "EU", 44.0, 21.0),
    ("9A", "Croatia", "EU", 45.1, 15.5), ("S5", "Slovenia", "EU", 46.1, 14.8),
    ("E7", "Bosnia-Herzegovina", "EU", 44.0, 18.0), ("Z3", "North Macedonia", "EU", 41.6, 21.7),
    ("ZA", "Albania", "EU", 41.0, 20.0), ("SV", "Greece", "EU", 39.0, 22.0),
    ("SV5", "Dodecanese", "EU", 36.4, 28.2), ("SV9", "Crete", "EU", 35.2, 24.9),
    ("5B", "Cyprus", "AS", 35.1, 33.4), ("TA", "Turkey", "AS", 39.0, 35.0),
    ("YL", "Latvia", "EU", 56.9, 24.6), ("LY", "Lithuania", "EU", 55.3, 23.9),
    ("ES", "Estonia", "EU", 58.6, 25.0), ("EU", "Belarus", "EU", 53.7, 27.9),
    ("EW", "Belarus", "EU", 53.7, 27.9), ("UR", "Ukraine", "EU", 49.0, 32.0),
    ("UT", "Ukraine", "EU", 49.0, 32.0), ("UX", "Ukraine", "EU", 49.0, 32.0),
    ("ER", "Moldova", "EU", 47.0, 28.9), ("4L", "Georgia", "AS", 42.0, 43.5),
    ("EK", "Armenia", "AS", 40.2, 45.0), ("4J", "Azerbaijan", "AS", 40.4, 47.6),
    ("UA", "European Russia", "EU", 55.8, 37.6), ("RA", "European Russia", "EU", 55.8, 37.6),
    ("RU", "European Russia", "EU", 55.8, 37.6), ("RV", "European Russia", "EU", 55.8, 37.6),
    ("UA9", "Asiatic Russia", "AS", 56.0, 85.0), ("UA0", "Asiatic Russia", "AS", 56.0, 105.0),
    ("RA9", "Asiatic Russia", "AS", 56.0, 85.0), ("RA0", "Asiatic Russia", "AS", 56.0, 105.0),
    ("UA2", "Kaliningrad", "EU", 54.7, 20.5), ("UN", "Kazakhstan", "AS", 48.0, 68.0),
    ("EX", "Kyrgyzstan", "AS", 41.2, 74.8), ("EY", "Tajikistan", "AS", 38.9, 71.3),
    ("EZ", "Turkmenistan", "AS", 39.0, 59.0), ("UK", "Uzbekistan", "AS", 41.4, 64.6),
    ("JA", "Japan", "AS", 36.0, 138.0), ("JE", "Japan", "AS", 36.0, 138.0),
    ("JF", "Japan", "AS", 36.0, 138.0), ("JG", "Japan", "AS", 36.0, 138.0),
    ("JH", "Japan", "AS", 36.0, 138.0), ("JI", "Japan", "AS", 36.0, 138.0),
    ("JJ", "Japan", "AS", 36.0, 138.0), ("JK", "Japan", "AS", 36.0, 138.0),
    ("JL", "Japan", "AS", 36.0, 138.0), ("JM", "Japan", "AS", 36.0, 138.0),
    ("JN", "Japan", "AS", 36.0, 138.0), ("JO", "Japan", "AS", 36.0, 138.0),
    ("JP", "Japan", "AS", 36.0, 138.0), ("JQ", "Japan", "AS", 36.0, 138.0),
    ("JR", "Japan", "AS", 36.0, 138.0), ("JS", "Japan", "AS", 36.0, 138.0),
    ("7K", "Japan", "AS", 36.0, 138.0), ("7L", "Japan", "AS", 36.0, 138.0),
    ("8J", "Japan", "AS", 36.0, 138.0), ("HL", "South Korea", "AS", 36.5, 127.8),
    ("DS", "South Korea", "AS", 36.5, 127.8), ("P5", "North Korea", "AS", 39.0, 126.0),
    ("BY", "China", "AS", 35.0, 105.0), ("BG", "China", "AS", 35.0, 105.0),
    ("BA", "China", "AS", 35.0, 105.0), ("BD", "China", "AS", 35.0, 105.0),
    ("BV", "Taiwan", "AS", 23.7, 121.0), ("VR", "Hong Kong", "AS", 22.3, 114.2),
    ("XX9", "Macao", "AS", 22.2, 113.5), ("VU", "India", "AS", 22.0, 79.0),
    ("AP", "Pakistan", "AS", 30.0, 70.0), ("S2", "Bangladesh", "AS", 24.0, 90.0),
    ("4S", "Sri Lanka", "AS", 7.5, 80.7), ("8Q", "Maldives", "AS", 3.2, 73.2),
    ("9N", "Nepal", "AS", 28.2, 84.0), ("XZ", "Myanmar", "AS", 21.0, 96.0),
    ("HS", "Thailand", "AS", 15.0, 101.0), ("E2", "Thailand", "AS", 15.0, 101.0),
    ("XU", "Cambodia", "AS", 12.5, 105.0), ("XW", "Laos", "AS", 18.0, 105.0),
    ("3W", "Vietnam", "AS", 16.0, 107.0), ("9M2", "West Malaysia", "AS", 4.0, 102.0),
    ("9M6", "East Malaysia", "OC", 5.5, 117.0), ("9V", "Singapore", "AS", 1.3, 103.8),
    ("YB", "Indonesia", "OC", -2.0, 118.0), ("DU", "Philippines", "OC", 13.0, 122.0),
    ("VK", "Australia", "OC", -25.0, 134.0), ("VK9", "Australian External", "OC", -29.0, 168.0),
    ("ZL", "New Zealand", "OC", -41.0, 174.0), ("FK", "New Caledonia", "OC", -21.3, 165.5),
    ("FO", "French Polynesia", "OC", -17.6, -149.5), ("KH2", "Guam", "OC", 13.4, 144.8),
    ("KH0", "Mariana Islands", "OC", 15.2, 145.7), ("V7", "Marshall Islands", "OC", 7.1, 171.4),
    ("T8", "Palau", "OC", 7.5, 134.6), ("V6", "Micronesia", "OC", 6.9, 158.2),
    ("3D2", "Fiji", "OC", -18.0, 178.0), ("5W", "Samoa", "OC", -13.8, -172.1),
    ("A3", "Tonga", "OC", -21.2, -175.2), ("E5", "Cook Islands", "OC", -21.2, -159.8),
    ("P2", "Papua New Guinea", "OC", -6.0, 147.0), ("H4", "Solomon Islands", "OC", -9.4, 160.0),
    ("YJ", "Vanuatu", "OC", -17.7, 168.3), ("T2", "Tuvalu", "OC", -8.5, 179.2),
    ("T30", "Western Kiribati", "OC", 1.4, 173.0), ("C2", "Nauru", "OC", -0.5, 166.9),
    ("ZS", "South Africa", "AF", -29.0, 24.0), ("V5", "Namibia", "AF", -22.0, 17.0),
    ("A2", "Botswana", "AF", -22.3, 24.7), ("Z2", "Zimbabwe", "AF", -19.0, 30.0),
    ("7Q", "Malawi", "AF", -13.5, 34.0), ("C9", "Mozambique", "AF", -18.0, 35.0),
    ("9J", "Zambia", "AF", -14.0, 28.0), ("5H", "Tanzania", "AF", -6.0, 35.0),
    ("5Z", "Kenya", "AF", 0.5, 37.9), ("5X", "Uganda", "AF", 1.3, 32.3),
    ("ET", "Ethiopia", "AF", 9.0, 39.0), ("ST", "Sudan", "AF", 15.5, 32.5),
    ("SU", "Egypt", "AF", 26.0, 30.0), ("5A", "Libya", "AF", 27.0, 17.0),
    ("3V", "Tunisia", "AF", 34.0, 9.5), ("7X", "Algeria", "AF", 28.0, 3.0),
    ("CN", "Morocco", "AF", 32.0, -6.0), ("5T", "Mauritania", "AF", 20.0, -11.0),
    ("6W", "Senegal", "AF", 14.5, -14.5), ("C5", "The Gambia", "AF", 13.4, -15.5),
    ("9G", "Ghana", "AF", 8.0, -1.2), ("5N", "Nigeria", "AF", 9.5, 8.0),
    ("TJ", "Cameroon", "AF", 6.0, 12.5), ("TR", "Gabon", "AF", -0.6, 11.8),
    ("9Q", "Dem Rep of Congo", "AF", -3.0, 23.0), ("D2", "Angola", "AF", -12.0, 17.5),
    ("FR", "Reunion", "AF", -21.1, 55.5), ("3B8", "Mauritius", "AF", -20.3, 57.6),
    ("3B9", "Rodrigues Island", "AF", -19.7, 63.4), ("5R", "Madagascar", "AF", -19.0, 47.0),
    ("S7", "Seychelles", "AF", -4.6, 55.5), ("D4", "Cape Verde", "AF", 16.0, -24.0),
    ("ZD7", "St Helena", "AF", -15.9, -5.7), ("ZD8", "Ascension Island", "AF", -7.9, -14.4),
    ("ZD9", "Tristan da Cunha", "AF", -37.1, -12.3), ("A4", "Oman", "AS", 21.0, 57.0),
    ("A6", "United Arab Emirates", "AS", 24.0, 54.0), ("A7", "Qatar", "AS", 25.3, 51.2),
    ("A9", "Bahrain", "AS", 26.0, 50.5), ("9K", "Kuwait", "AS", 29.3, 47.7),
    ("HZ", "Saudi Arabia", "AS", 24.0, 45.0), ("7Z", "Saudi Arabia", "AS", 24.0, 45.0),
    ("YI", "Iraq", "AS", 33.0, 44.0), ("EP", "Iran", "AS", 32.0, 53.0),
    ("JY", "Jordan", "AS", 31.2, 36.5), ("OD", "Lebanon", "AS", 33.9, 35.9),
    ("YK", "Syria", "AS", 35.0, 38.0), ("4X", "Israel", "AS", 31.5, 35.0),
    ("4Z", "Israel", "AS", 31.5, 35.0), ("A9C", "Bahrain", "AS", 26.0, 50.5),
    ("VP8", "Falkland Islands", "SA", -51.7, -59.2), ("CE9", "Antarctica", "AN", -75.0, 0.0),
    ("KC4", "Antarctica", "AN", -75.0, 0.0), ("VP2", "Anguilla", "NA", 18.2, -63.1),
    ("VP5", "Turks & Caicos", "NA", 21.8, -71.8), ("VP9", "Bermuda", "NA", 32.3, -64.8),
    ("OX", "Greenland", "NA", 72.0, -40.0), ("JW", "Svalbard", "EU", 78.0, 16.0),
    ("JX", "Jan Mayen", "EU", 71.0, -8.3), ("TK", "Corsica", "EU", 42.2, 9.1),
    ("9H", "Malta", "EU", 35.9, 14.4), ("T7", "San Marino", "EU", 43.9, 12.5),
    ("HV", "Vatican", "EU", 41.9, 12.5), ("3A", "Monaco", "EU", 43.7, 7.4),
    ("C3", "Andorra", "EU", 42.5, 1.5), ("ZB2", "Gibraltar", "EU", 36.1, -5.3),
)

# Longest first, so a longest-prefix match is a simple linear scan.
# fmt: on

_BUILTIN_SORTED = tuple(sorted(_BUILTIN, key=lambda row: -len(row[0])))


def builtin_prefixes() -> list[dict[str, str]]:
    """The built-in prefixes as (prefix, entity) pairs.

    Exposed for the CW trainer, which generates practice callsigns from real
    DXCC prefixes so that revealing the answer can also name the country. The
    built-in table rather than a loaded cty.dat, because the trainer must work
    with no data files present -- that is the whole claim of a tier 0 panel.
    """
    return [{"prefix": row[0], "entity": row[1]} for row in _BUILTIN]


def base_call(callsign: str) -> str:
    """Strip portable designators down to the part that identifies the entity.

    ``W1AW/4`` is in the US fourth district, ``DL/W1AW`` is in Germany. The
    convention is that a *prefix* qualifier comes first and a *suffix* qualifier
    comes last, so the shorter side of a split is usually the location -- except
    when the suffix is one of the well-known noise words like /P or /QRP.
    """
    call = callsign.strip().upper()
    if "/" not in call:
        return call

    parts = [p for p in call.split("/") if p]
    if not parts:
        return call
    if len(parts) == 1:
        return parts[0]

    head, *rest = parts
    tail = rest[-1]

    # A trailing /P, /M, /QRP and friends says nothing about location.
    if tail in _PORTABLE_NOISE and len(rest) == 1:
        return head
    # A trailing single digit is a district within the same entity.
    if tail.isdigit():
        return head
    # Otherwise the shorter fragment is the qualifying prefix: DL/W1AW -> DL.
    candidates = [p for p in parts if p not in _PORTABLE_NOISE]
    if not candidates:
        return head
    return min(candidates, key=len)


# --- cty.dat --------------------------------------------------------------
_ALIAS_NOISE = re.compile(r"\([0-9]+\)|\[[0-9]+\]|<[^>]*>|\{[^}]*\}|~[^~]*~")


class PrefixTable:
    """Callsign lookup, backed by cty.dat when one is available."""

    def __init__(self, cty_path: Path | None = None) -> None:
        self._exact: dict[str, Entity] = {}
        self._prefixes: list[tuple[str, Entity]] = []
        self._source = "builtin"

        if cty_path is not None:
            try:
                self._load_cty(cty_path)
                self._source = str(cty_path)
                log.info("prefix table loaded from %s (%d prefixes)", cty_path, len(self._prefixes))
            except (OSError, ValueError) as exc:
                log.warning(
                    "could not read %s (%s); falling back to the built-in table", cty_path, exc
                )

        if not self._prefixes:
            self._load_builtin()

    @property
    def source(self) -> str:
        return self._source

    @property
    def approximate(self) -> bool:
        return self._source == "builtin"

    def _load_builtin(self) -> None:
        self._prefixes = [
            (
                prefix,
                Entity(name, prefix, continent, lat, lon, approximate=True),
            )
            for prefix, name, continent, lat, lon in _BUILTIN_SORTED
        ]

    def _load_cty(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        entries: list[tuple[str, Entity]] = []

        for record in text.split(";"):
            record = record.strip()
            if not record:
                continue
            header, _, aliases = record.partition("\n")
            fields = [f.strip() for f in header.split(":")]
            if len(fields) < 8:
                continue
            name, cq, _itu, continent, lat_s, lon_s, _gmt, primary = fields[:8]
            try:
                lat = float(lat_s)
                # cty.dat records west longitude as positive; the rest of the
                # world does the opposite.
                lon = -float(lon_s)
                cq_zone = int(cq)
            except ValueError:
                continue

            entity = Entity(name, primary.lstrip("*"), continent, lat, lon, cq_zone)

            for raw in aliases.replace("\n", " ").split(","):
                alias = _ALIAS_NOISE.sub("", raw).strip().upper()
                if not alias:
                    continue
                if alias.startswith("="):
                    self._exact[alias[1:]] = entity
                else:
                    entries.append((alias, entity))

            entries.append((entity.prefix.upper(), entity))

        if not entries:
            raise ValueError("no usable records")
        self._prefixes = sorted(entries, key=lambda row: -len(row[0]))

    def export(self) -> dict[str, object]:
        """The table in a form the browser can do its own lookups against.

        Published as a snapshot so the callsign panel resolves locally and
        instantly, with no request per lookup -- which also means the collector
        keeps its "no request-driven work" property. Entries are longest-first,
        so the browser's match is the same linear scan this class does.
        """
        return {
            "source": self._source,
            "approximate": self.approximate,
            "exact": {
                call: [e.name, e.continent, e.lat, e.lon, e.cq_zone]
                for call, e in self._exact.items()
            },
            "prefixes": [
                [prefix, e.name, e.continent, e.lat, e.lon, e.cq_zone]
                for prefix, e in self._prefixes
            ],
        }

    def lookup(self, callsign: str) -> Entity | None:
        """Resolve a callsign, longest matching prefix wins."""
        call = base_call(callsign)
        if not call or not _CALL_CHARS.match(call):
            return None

        exact = self._exact.get(call)
        if exact is not None:
            return exact

        for prefix, entity in self._prefixes:
            if call.startswith(prefix):
                return entity
        return None


_DEFAULT: PrefixTable | None = None


def default_table(cty_path: Path | None = None) -> PrefixTable:
    """Process-wide table, built once."""
    global _DEFAULT  # noqa: PLW0603
    if _DEFAULT is None or cty_path is not None:
        _DEFAULT = PrefixTable(cty_path)
    return _DEFAULT

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""config.example.toml is the file every new user copies.

If it rots, the first experience of this project is a stack trace. It is also
mostly *comments* -- the interesting parts are commented-out blocks people
uncomment -- and a commented-out example is exactly the kind of thing that goes
stale without anyone noticing, because nothing loads it.

So both halves are checked: the live config parses and every source it names is
real, and the commented-out examples are extracted, parsed, and validated the
same way.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from hammunition_hill.config import parse_config
from hammunition_hill.egress import ALLOWED_SCHEMES, STREAM_SCHEMES
from hammunition_hill.lookup import PROVIDERS
from hammunition_hill.sources import REGISTRY
from hammunition_hill.sources.local import LOCAL_KINDS
from hammunition_hill.streams import STREAM_KINDS

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config.example.toml"
RAW = EXAMPLE.read_text(encoding="utf-8")

ALL_KINDS = set(REGISTRY) | set(STREAM_KINDS) | set(LOCAL_KINDS)

# Commented-out config looks like "# [table]" or "# key = value". Prose comments
# do not, which is what makes them separable.
_COMMENTED = re.compile(r"^#\s?((?:\[|[A-Za-z_][A-Za-z0-9_-]*\s*=).*)$")


def commented_config() -> dict:
    """The commented-out examples, uncommented and parsed.

    Tables get flattened oddly when a header is live but its keys are commented,
    so this is used to validate *values* -- kinds, URLs, provider names -- not
    document structure.
    """
    lines = [m[1] for line in RAW.splitlines() if (m := _COMMENTED.match(line))]
    return tomllib.loads("\n".join(lines))


def all_source_tables() -> list[dict]:
    live = tomllib.loads(RAW).get("sources", [])
    return list(live) + list(commented_config().get("sources", []))


# --- the live config ------------------------------------------------------
def test_example_parses(tmp_path):
    parse_config(tomllib.loads(RAW), base_dir=tmp_path)


def test_example_is_loopback_only(tmp_path):
    """Shipping a default that binds to the LAN would be indefensible."""
    config = parse_config(tomllib.loads(RAW), base_dir=tmp_path)
    assert config.server.is_loopback_only


def test_example_ships_lookup_off(tmp_path):
    config = parse_config(tomllib.loads(RAW), base_dir=tmp_path)
    assert not config.lookup.enabled, "lookup must be opt-in"


def test_example_ships_logging_off(tmp_path):
    config = parse_config(tomllib.loads(RAW), base_dir=tmp_path)
    assert not config.logging.enabled, "the one write path must be opt-in"


def test_example_ships_no_imagery(tmp_path):
    """Tier 2 is opt-in. A default tile would make every install phone out."""
    config = parse_config(tomllib.loads(RAW), base_dir=tmp_path)
    assert config.imagery == ()


# --- the commented-out examples -------------------------------------------
def test_commented_examples_are_still_valid_toml():
    """A stale commented block is a stack trace for whoever uncomments it."""
    assert commented_config(), "no commented-out examples found; has the format changed?"


@pytest.mark.parametrize("table", all_source_tables(), ids=lambda t: t.get("id", "?"))
def test_every_example_source_kind_exists(table):
    kind = table.get("kind")
    assert kind in ALL_KINDS, (
        f"source {table.get('id')!r} uses kind {kind!r}, which is not registered. "
        f"Known kinds: {', '.join(sorted(ALL_KINDS))}"
    )


@pytest.mark.parametrize("table", all_source_tables(), ids=lambda t: t.get("id", "?"))
def test_every_example_source_url_uses_an_allowed_scheme(table):
    url = table.get("url")
    if not url:
        return  # a file source
    scheme = urlsplit(url).scheme.lower()
    assert scheme in (ALLOWED_SCHEMES | STREAM_SCHEMES), (
        f"source {table.get('id')!r} uses scheme {scheme!r}, which the guard refuses"
    )


@pytest.mark.parametrize("table", all_source_tables(), ids=lambda t: t.get("id", "?"))
def test_polled_example_sources_are_https(table):
    """An http upstream would ship plaintext by default. Local gear is exempt."""
    url = table.get("url", "")
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return
    if table.get("local"):
        return
    assert scheme == "https", f"source {table.get('id')!r} is not https"


def test_example_lookup_providers_exist():
    lookup = commented_config().get("lookup", {})
    for name in lookup.get("providers", []):
        assert name in PROVIDERS, f"example names unknown provider {name!r}"


def test_example_imagery_is_https():
    for tile in commented_config().get("imagery", []):
        assert urlsplit(tile["url"]).scheme == "https", f"tile {tile['id']!r} is not https"


def test_example_source_ids_are_unique():
    ids = [t.get("id") for t in all_source_tables()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate example source ids: {duplicates}"


# --- the coupling that actually breaks panels -----------------------------
# Snapshots the collector publishes without a [[sources]] entry.
# Snapshots the collector publishes without a [[sources]] entry: config it
# derives, and the propagation model, which reads other snapshots rather than
# fetching anything of its own.
BUILT_IN_SNAPSHOTS = {
    "station",
    "prefixes",
    "imagery",
    "logbooks",
    "lookups",
    "propagation",
}


def test_every_shipped_panel_can_get_its_data():
    """A panel naming a snapshot id nothing produces is a silently blank panel.

    This is the coupling documented in PANELS.md, and it is invisible until a
    dashboard renders empty with no error anywhere.
    """
    import json

    available = {t.get("id") for t in all_source_tables()} | BUILT_IN_SNAPSHOTS

    problems = []
    for directory in sorted((ROOT / "web" / "panels").iterdir()):
        if not directory.is_dir():
            continue
        manifest = json.loads((directory / "panel.json").read_text())
        for source_id in manifest.get("sources", []):
            if source_id not in available:
                problems.append(f"{manifest['id']} reads {source_id!r}")

    assert not problems, (
        "panels read snapshot ids that config.example.toml does not produce: "
        + "; ".join(problems)
    )

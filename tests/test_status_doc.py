# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Keep the status tables honest.

The README used to say "Twelve panels work end to end" long after there were
nineteen, and listed greyline, aurora and weather alerts as still ahead of
parity after all three had shipped. Nobody lied; a hand-maintained count simply
rotted, and a status page that overclaims is worse than not having one.

So the numbers in README.md and docs/STATUS.md are asserted against the code
that produces them. If you add a panel or a source kind, one of these fails and
tells you which sentence to edit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
STATUS = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
DOCS = {"README.md": README, "docs/STATUS.md": STATUS}


def panel_dirs() -> list[Path]:
    return sorted(p for p in (ROOT / "web" / "panels").iterdir() if p.is_dir())


def dashboards() -> list[dict]:
    index = json.loads((ROOT / "web" / "panels" / "index.json").read_text())
    return index["dashboards"]


@pytest.mark.parametrize("name", sorted(DOCS))
def test_panel_and_dashboard_counts(name):
    text = DOCS[name]
    match = re.search(r"(\d+) across (\d+) dashboards", text)
    assert match, f"{name}: no 'N across M dashboards' claim found"
    claimed_panels, claimed_dashboards = int(match[1]), int(match[2])
    assert claimed_panels == len(panel_dirs()), (
        f"{name} claims {claimed_panels} panels; there are {len(panel_dirs())}"
    )
    assert claimed_dashboards == len(dashboards()), (
        f"{name} claims {claimed_dashboards} dashboards; there are {len(dashboards())}"
    )


@pytest.mark.parametrize("name", sorted(DOCS))
def test_source_kind_counts(name):
    from hammunition_hill.sources import REGISTRY
    from hammunition_hill.sources.local import LOCAL_KINDS
    from hammunition_hill.streams import STREAM_KINDS

    match = re.search(r"(\d+) polled, (\d+) stream, (\d+) file", DOCS[name])
    assert match, f"{name}: no 'N polled, M stream, K file' claim found"
    assert int(match[1]) == len(REGISTRY), f"{name}: polled count is {len(REGISTRY)}"
    assert int(match[2]) == len(STREAM_KINDS), f"{name}: stream count is {len(STREAM_KINDS)}"
    assert int(match[3]) == len(LOCAL_KINDS), f"{name}: file count is {len(LOCAL_KINDS)}"


@pytest.mark.parametrize("name", sorted(DOCS))
def test_severity_scale_count(name):
    from hammunition_hill.severity import SCALES

    match = re.search(r"(\d+) scales", DOCS[name])
    assert match, f"{name}: no 'N scales' claim found"
    assert int(match[1]) == len(SCALES), f"{name}: there are {len(SCALES)} severity scales"


@pytest.mark.parametrize("name", sorted(DOCS))
def test_lookup_provider_count(name):
    from hammunition_hill.lookup import PROVIDERS

    match = re.search(r"(\d+) providers", DOCS[name])
    assert match, f"{name}: no 'N providers' claim found"
    assert int(match[1]) == len(PROVIDERS), f"{name}: there are {len(PROVIDERS)} providers"


def test_tier_zero_panels_named_in_status_are_actually_tier_zero():
    """The offline list is the one people will rely on when the WAN drops."""
    match = re.search(r"they work with the internet unplugged: (.+?)\.\s", STATUS, re.S)
    assert match, "STATUS.md: no tier 0 panel list found"
    claimed = set(re.findall(r"`([a-z]+)`", match[1]))

    actual = {
        d.name
        for d in panel_dirs()
        if json.loads((d / "panel.json").read_text())["tier"] == 0
    }
    assert claimed == actual, f"STATUS.md tier 0 list is {claimed}; the manifests say {actual}"


def test_every_panel_dir_has_a_manifest_and_module():
    """A half-added panel would inflate the count without working."""
    for directory in panel_dirs():
        assert (directory / "panel.json").is_file(), f"{directory.name}: no panel.json"
        assert (directory / "panel.js").is_file(), f"{directory.name}: no panel.js"


def test_every_dashboard_panel_exists():
    names = {d.name for d in panel_dirs()}
    for dash in dashboards():
        for panel in dash["panels"]:
            assert panel in names, f"dashboard {dash['id']} lists unknown panel {panel!r}"


def test_status_doc_is_linked_from_the_readme():
    assert "docs/STATUS.md" in README


def test_unbuilt_features_are_not_described_as_working():
    """The query endpoint shipped as a config flag with no route behind it.

    It was documented in the present tense and `hamhill check` reported it as
    ENABLED. Whatever else changes, the docs must not call it built while the
    server has no route for it.
    """
    from hammunition_hill import server

    source = Path(server.__file__).read_text(encoding="utf-8")
    implemented = "/lookup/" in source

    if not implemented:
        assert "not written" in STATUS or "NOT built" in STATUS or "not built" in STATUS, (
            "STATUS.md must say the query endpoint is not built while it is not built"
        )
        assert "NOT IMPLEMENTED" in (ROOT / "src/hammunition_hill/cli.py").read_text(), (
            "hamhill check must not report query_endpoint as ENABLED"
        )

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
        d.name for d in panel_dirs() if json.loads((d / "panel.json").read_text())["tier"] == 0
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


def test_every_documentation_page_is_linked_from_the_readme():
    """A page nobody links to is a page nobody reads.

    docs/LOGBOOK.md was written, committed, and left out of the README's
    documentation table, so the only way to find it was to list the directory.
    Adding a page and linking it are separate acts, and the second one is the
    one that gets forgotten.
    """
    pages = sorted(p.name for p in (ROOT / "docs").glob("*.md"))
    assert pages, "no documentation pages found"
    missing = [name for name in pages if f"docs/{name}" not in README]
    assert not missing, f"README.md does not link: {', '.join(missing)}"


def test_no_documentation_page_links_to_a_file_that_does_not_exist():
    """Relative links rot silently: nothing renders them until someone clicks.

    This covers every markdown file in the repository, not just the README,
    because a page is as likely to link a sibling page as the index is. Anchors
    are not checked -- only that the file on the other end is there at all.
    """
    docs = sorted(list(ROOT.glob("*.md")) + list((ROOT / "docs").glob("*.md")))
    assert len(docs) > 15, f"only found {len(docs)} docs; the glob is wrong"

    broken = []
    for doc in docs:
        for target in re.findall(
            r"\]\((?!https?:|mailto:)([^)\s]+)\)", doc.read_text(encoding="utf-8")
        ):
            path = target.partition("#")[0]
            if path and not (doc.parent / path).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, "broken relative links:\n  " + "\n  ".join(broken)


def status_rows() -> dict[str, str]:
    """Every ``| feature | status | ...`` row in STATUS.md, feature -> status cell.

    Later rows win. A feature named in both the at-a-glance summary and its own
    section is the case this exists for: the detail row is the one written when
    the feature lands, and the summary is the one that gets forgotten.
    """
    rows: dict[str, str] = {}
    for line in STATUS.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("- ") or not cells[0]:
            continue
        rows[cells[0].strip("*` ").lower()] = cells[1]
    return rows


# Feature as STATUS.md names it -> a callable that is true when it is built.
# Keep the probe something that would break if the feature were removed, not a
# mere import of a name.
BUILT = {
    "satellites": lambda: __import__("hammunition_hill.satellites", fromlist=["passes"]).passes,
    "rbn": lambda: __import__("hammunition_hill.streams", fromlist=["STREAM_KINDS"]).STREAM_KINDS[
        "rbn"
    ],
    "licence exam practice": lambda: (
        __import__("hammunition_hill.exam", fromlist=["build_exam"]).build_exam
    ),
    "prometheus metrics endpoint": lambda: (
        __import__("hammunition_hill.metrics", fromlist=["Registry"]).Registry
    ),
}


@pytest.mark.parametrize("feature", sorted(BUILT))
def test_built_features_are_not_described_as_unwritten(feature):
    """The mirror of the test below, and the failure that actually happened.

    Satellites, RBN and the exporter all shipped, and all three had their own
    detail row rewritten at the time. The at-a-glance table at the top of the
    page still said "not written" for every one of them, because updating a
    summary is a separate act from updating the thing it summarises. A reader
    who stops at the summary -- which is what a summary is for -- came away
    believing three shipped subsystems did not exist.
    """
    BUILT[feature]()  # raises if the feature is not there, which is the point
    status = status_rows().get(feature)
    assert status is not None, f"STATUS.md has no row for {feature!r}"
    assert "❌" not in status, f"STATUS.md calls {feature!r} unwritten: {status!r}"


def test_every_source_kind_is_named_in_the_status_prose():
    """The counts above this were right while the list beside them was wrong.

    ``N polled, M stream, K file`` was correct and tested. The very next lines
    enumerate the kinds by name, and that list was missing ``tle`` and ``rbn``
    -- a count test cannot see a name that is absent when the number is right,
    because the number is not derived from the list.
    """
    from hammunition_hill.sources import REGISTRY
    from hammunition_hill.sources.local import LOCAL_KINDS
    from hammunition_hill.streams import STREAM_KINDS

    for kind in sorted({*REGISTRY, *STREAM_KINDS, *LOCAL_KINDS}):
        assert f"`{kind}`" in STATUS, f"STATUS.md never names the {kind!r} source kind"


def test_the_tier_breakdown_adds_up_to_the_panel_count():
    """STATUS.md said "19 panels" in prose while the table above it said 26.

    The existing count test matches the first "N across M dashboards" it finds
    and stops, so a second statement of the same fact further down the page was
    free to rot -- and did, through seven panels being added. The tier
    breakdown beside it stayed correct the whole time, which is what made the
    contradiction survive a read: nine plus sixteen plus one is twenty-six, so
    only the headline was wrong.
    """
    counts = {0: 0, 1: 0, 2: 0}
    for directory in panel_dirs():
        manifest = json.loads((directory / "panel.json").read_text(encoding="utf-8"))
        counts[manifest["tier"]] += 1

    words = {9: "Nine", 16: "Sixteen", 1: "One"}
    assert f"{sum(counts.values())} panels, {len(dashboards())} dashboards" in STATUS, (
        f"STATUS.md prose disagrees: there are {sum(counts.values())} panels"
    )
    for tier, total in counts.items():
        word = words.get(total, str(total))
        assert (
            f"{word} are **tier {tier}**" in STATUS
            or f"{word} is tier {tier}" in STATUS
            or (f"{word} are tier {tier}" in STATUS)
        ), f"STATUS.md does not say {word} panels are tier {tier}"


PARITY = (ROOT / "docs" / "PARITY.md").read_text(encoding="utf-8")

# Row label as PARITY.md writes it -> a probe that is true when it is built.
PARITY_BUILT = {
    "RBN spots": lambda: __import__(
        "hammunition_hill.streams", fromlist=["STREAM_KINDS"]
    ).STREAM_KINDS["rbn"],
    "Satellites": lambda: __import__("hammunition_hill.satellites", fromlist=["passes"]).passes,
    "Education": lambda: __import__("hammunition_hill.exam", fromlist=["build_exam"]).build_exam,
}


@pytest.mark.parametrize("feature", sorted(PARITY_BUILT))
def test_parity_does_not_call_a_built_feature_planned(feature):
    """The comparison page drifts the same way the status page did, and worse.

    PARITY.md carried four stale rows at once: RBN spots and its SNR matrix,
    satellites, and -- the one that actually contradicted the product --
    Education marked "not planned" with the reasoning that study sites do it
    better, while licence exam practice was built, documented, and shipping
    three question pools.

    A comparison against someone else's product is exactly the page a reader
    trusts to be current, because its whole purpose is to be a snapshot of two
    moving things.
    """
    PARITY_BUILT[feature]()
    rows = [line for line in PARITY.splitlines() if line.startswith(f"| {feature} |")]
    assert rows, f"PARITY.md has no row for {feature!r}"
    for row in rows:
        assert "**planned**" not in row and "**not planned**" not in row, (
            f"PARITY.md calls {feature!r} planned: {row}"
        )


CONFIGURATION = (ROOT / "docs" / "CONFIGURATION.md").read_text(encoding="utf-8")


def test_configuration_documents_every_source_kind():
    """The README calls this page "every option, every source kind". It was not.

    Twelve of eighteen kinds had a section. `aurora`, `noaa_scales`,
    `swpc_alerts`, `tle`, `rbn`, `gpsd` and `nmea` had none at all -- four of
    them shipped after the page was written, and the page was never revisited.
    The example config carried all of them, so the information existed; it was
    only the reference that did not have it, which is the worse of the two to
    be missing when someone is looking a kind up.
    """
    from hammunition_hill.sources import REGISTRY
    from hammunition_hill.sources.local import LOCAL_KINDS
    from hammunition_hill.streams import STREAM_KINDS

    kinds = {*REGISTRY, *STREAM_KINDS, *LOCAL_KINDS}
    headings = set(re.findall(r"^### `([a-z_]+)`", CONFIGURATION, re.M))
    headings |= set(re.findall(r"^### `([a-z_]+)` / `([a-z_]+)`", CONFIGURATION, re.M))
    # A heading of the form "### `pota` / `sota`" documents both.
    for left, right in re.findall(r"^### `([a-z_]+)` / `([a-z_]+)`", CONFIGURATION, re.M):
        headings |= {left, right}

    missing = sorted(k for k in kinds if k not in headings)
    assert not missing, f"CONFIGURATION.md has no section for: {', '.join(missing)}"


@pytest.mark.parametrize("section", ["[satellites]", "[metrics]", "[server]", "[station]"])
def test_configuration_documents_every_config_table(section):
    """The same gap, for the top level tables rather than the source kinds."""
    assert f"## `{section}`" in CONFIGURATION, f"CONFIGURATION.md does not document {section}"


ARCHITECTURE = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


def test_architecture_lists_every_module():
    """The module map is what orients somebody opening the source for the first time.

    It listed eleven modules while twenty-four existed. Everything added after
    the page was written -- the whole tier 0 half of the product, satellites,
    metrics, the exam pools -- was simply absent, so the map described a
    smaller, older program than the one in the repository. A map that is
    missing half the territory is worse than no map, because it is read as
    complete.
    """
    package = ROOT / "src" / "hammunition_hill"
    modules = {path.name for path in package.glob("*.py") if not path.name.startswith("__")}
    assert len(modules) > 15, f"only found {len(modules)} modules; the glob is wrong"

    missing = sorted(name for name in modules if f"`{name}`" not in ARCHITECTURE)
    assert not missing, f"ARCHITECTURE.md does not list: {', '.join(missing)}"


INSTALL = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")


def test_install_documents_every_optional_extra():
    """An extra nobody is told about is an extra nobody installs.

    INSTALL.md showed `pip install -e .` and stopped. Satellite pass prediction
    needs `[satellites]` and the page never said so, so the only way to find out
    was to read pyproject.toml or to notice the panel explaining itself. The
    install page is where somebody looks once, at the start.
    """
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = set(pyproject["project"]["optional-dependencies"])
    assert extras, "no optional extras declared"

    missing = sorted(name for name in extras if f'".[{name}]"' not in INSTALL)
    assert not missing, f"docs/INSTALL.md does not mention the extras: {', '.join(missing)}"

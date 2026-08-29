# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The frontend has no unit tests. These are the checks that need none.

Roughly three thousand lines of JavaScript ship in web/, and until now nothing
looked at any of it. A syntax error in one panel module is caught by the host's
try/catch and turns into one broken panel on one dashboard -- which is exactly
the kind of thing that reaches a release.

None of this is a substitute for rendering the page, which is done in CI with a
real browser. It is the part that can run anywhere, in under a second, without
Node being a hard requirement.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
EXAMPLE = ROOT / "config.example.toml"

JS_FILES = sorted(p for p in WEB.rglob("*.js"))
JSON_FILES = sorted(p for p in WEB.rglob("*.json"))
PANEL_DIRS = sorted(p for p in (WEB / "panels").iterdir() if p.is_dir())

# XML namespace URIs are identifiers, not fetch targets -- createElementNS needs
# the SVG one and nothing ever requests it. Narrow on purpose: this is an
# allowlist of two strings, not a pattern that could grow to cover a real host.
XML_NAMESPACES = ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink")

node = shutil.which("node")
needs_node = pytest.mark.skipif(node is None, reason="node not installed")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


# A line comment is `//` NOT preceded by a colon. The negative lookbehind is
# load-bearing: without it this eats the `//` in `https://`, which would leave
# `"https:` behind and make the hardcoded-URL check below silently pass on
# exactly the thing it exists to catch.
_COMMENT = re.compile(r"(?<!:)//[^\n]*|/\*.*?\*/", re.S)


def code_only(path: Path) -> str:
    """Source with comments removed.

    Comments legitimately discuss innerHTML and cite upstream URLs -- the note
    in app.js literally reads "never innerHTML". Checking raw text flags the
    documentation instead of the code.
    """
    return _COMMENT.sub("", path.read_text(encoding="utf-8"))


# --- syntax ---------------------------------------------------------------
@needs_node
@pytest.mark.parametrize("path", JS_FILES, ids=rel)
def test_javascript_parses(path):
    result = subprocess.run(  # noqa: S603
        [node, "--check", str(path)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"{rel(path)}:\n{result.stderr}"


@pytest.mark.parametrize("path", JSON_FILES, ids=rel)
def test_json_is_valid(path):
    json.loads(path.read_text(encoding="utf-8"))


# --- the panel contract ---------------------------------------------------
@pytest.mark.parametrize("directory", PANEL_DIRS, ids=lambda d: d.name)
def test_panel_has_both_files(directory):
    assert (directory / "panel.json").is_file(), f"{directory.name}: no panel.json"
    assert (directory / "panel.js").is_file(), f"{directory.name}: no panel.js"


@pytest.mark.parametrize("directory", PANEL_DIRS, ids=lambda d: d.name)
def test_panel_manifest_is_well_formed(directory):
    manifest = json.loads((directory / "panel.json").read_text())
    assert manifest["id"] == directory.name, "manifest id must match the directory"
    assert manifest["tier"] in (0, 1, 2), f"tier {manifest['tier']!r} is not 0, 1 or 2"
    assert isinstance(manifest["sources"], list)
    assert manifest.get("name"), "a panel needs a display name"
    if "span" in manifest:
        assert 1 <= manifest["span"] <= 3, "span is capped at 3 by the grid"


@pytest.mark.parametrize("directory", PANEL_DIRS, ids=lambda d: d.name)
def test_panel_exports_render(directory):
    source = (directory / "panel.js").read_text(encoding="utf-8")
    assert re.search(r"export\s+function\s+render\s*\(", source), (
        f"{directory.name}/panel.js must export a render() function -- see docs/PANELS.md"
    )


@pytest.mark.parametrize("directory", PANEL_DIRS, ids=lambda d: d.name)
def test_tier_zero_panels_declare_no_external_hosts(directory):
    """Tier 0 means nothing originated off this machine. It has to stay true."""
    manifest = json.loads((directory / "panel.json").read_text())
    if manifest["tier"] == 0:
        assert not manifest.get("embed_hosts"), (
            f"{directory.name} is tier 0 but declares embed hosts"
        )


# --- the rules the whole frontend rests on --------------------------------
@pytest.mark.parametrize("path", JS_FILES, ids=rel)
def test_no_innerhtml(path):
    """Panels render with textContent. innerHTML is how this stops being safe.

    Snapshot data is upstream text -- spot comments, RSS titles, alert bodies,
    callsign names from a third-party lookup. The collector strips markup on the
    way in, and the browser never interprets it on the way out. Both, because
    either alone is one mistake from an injection.
    """
    source = code_only(path)
    for pattern in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert pattern not in source, f"{rel(path)} uses {pattern}"


@pytest.mark.parametrize("path", JS_FILES, ids=rel)
def test_no_dynamic_code_execution(path):
    source = code_only(path)
    assert not re.search(r"\beval\s*\(", source), f"{rel(path)} calls eval()"
    assert not re.search(r"\bnew\s+Function\s*\(", source), f"{rel(path)} uses new Function()"


@pytest.mark.parametrize("path", JS_FILES, ids=rel)
def test_no_hardcoded_external_urls(path):
    """The browser talks to this origin and to configured imagery hosts.

    A URL baked into a panel would be a tier 2 fetch that no config declared, no
    CSP anticipated, and no operator agreed to. Imagery tiles come from the
    snapshot the collector publishes, which is why that panel needs no URL of
    its own.
    """
    found = [
        url
        for url in re.findall(r"""["'`](https?://[^"'`\s]+)""", code_only(path))
        if not url.startswith(XML_NAMESPACES)
    ]
    assert not found, f"{rel(path)} hardcodes external URLs: {found}"


def test_dashboards_reference_real_panels():
    index = json.loads((WEB / "panels" / "index.json").read_text())
    names = {d.name for d in PANEL_DIRS}
    for dash in index["dashboards"]:
        assert dash.get("id") and dash.get("name"), f"malformed dashboard: {dash}"
        for panel in dash["panels"]:
            assert panel in names, f"dashboard {dash['id']} lists unknown panel {panel!r}"


def test_every_panel_appears_on_a_dashboard():
    """An orphaned panel is dead code that still inflates the count."""
    index = json.loads((WEB / "panels" / "index.json").read_text())
    used = {p for dash in index["dashboards"] for p in dash["panels"]}
    orphans = {d.name for d in PANEL_DIRS} - used
    assert not orphans, f"panels on no dashboard: {sorted(orphans)}"


def test_a_panel_whose_source_ships_disabled_does_not_claim_to_be_waiting():
    """ "Waiting for the first collector cycle" has to be able to end.

    Some sources ship commented out on purpose -- `wxalerts` needs an area
    filter and there is no sensible default for one -- so on a fresh install
    their snapshot is never written and never will be. A panel that says it is
    waiting for a cycle that is not coming is the same lie a blank panel tells,
    and it tells it to every new operator on the default config. Say the source
    is not configured, the way the GPS and logbook panels do.
    """
    raw = EXAMPLE.read_text(encoding="utf-8")
    live = {s["id"] for s in tomllib.loads(raw).get("sources", []) if "id" in s}
    # Commented-out config looks like "# id = ..." -- prose comments do not,
    # which is what separates a disabled source from a paragraph about one.
    disabled = set(re.findall(r'^#\s?id\s*=\s*"([^"]+)"', raw, re.MULTILINE)) - live

    offenders = []
    for directory in PANEL_DIRS:
        manifest = json.loads((directory / "panel.json").read_text())
        sources = manifest.get("sources") or []
        # A panel reading any live source really is waiting, briefly. A panel
        # whose sources are all derived (propagation, station -- published by
        # the collector with no [[sources]] entry to appear in either list) is
        # waiting for something that arrives at startup. The forever-wait is a
        # panel with no live source and at least one that ships commented out.
        if any(s in live for s in sources):
            continue
        if not any(s in disabled for s in sources):
            continue
        # The whole file, not a `!snapshot` guard: the first version of this
        # test anchored on that variable name, and the contests panel spelled
        # its guard `if (!events)` -- the message this test exists to catch,
        # invisible to it. code_only because the fix for an offender names the
        # phrase in a comment explaining why it is not used.
        if "waiting for the first collector" in code_only(directory / "panel.js"):
            offenders.append(f"{directory.name} (sources: {sources})")

    assert not offenders, (
        "these panels claim to be waiting for a collector cycle that the default "
        f"config never runs: {offenders}. Say the source is not configured and "
        "name the doc that turns it on."
    )


def test_index_html_loads_only_local_scripts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    external = re.findall(r'<script[^>]+src=["\'](https?://[^"\']+)', html)
    assert not external, f"index.html loads external scripts: {external}"


def test_css_has_no_external_imports():
    """A remote @import would need a CSP hole and leak every page load."""
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert "@import" not in css
    remote = re.findall(r"url\(\s*['\"]?https?://", css)
    assert not remote, "style.css references remote resources"


def test_every_css_variable_is_defined():
    """An undefined var() is not an error -- the property is just dropped.

    That is the failure mode this catches: text that renders in the browser's
    default colour on a dark panel, or a border that silently is not there, on
    a page that otherwise looks fine. Nothing else in the suite would notice,
    and it is easy to write `--line` in a repo whose variable is `--rule`.
    """
    css = (WEB / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.MULTILINE))
    used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", css))
    # A fallback makes the reference safe whether or not the variable exists.
    with_fallback = set(re.findall(r"var\(\s*(--[a-z0-9-]+)\s*,", css))
    missing = sorted(used - defined - with_fallback)
    assert not missing, f"style.css uses undefined variables: {missing}"


def test_panel_scripts_use_only_variables_the_stylesheet_defines():
    """Same check, for classes styled inline from a panel module."""
    css = (WEB / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.MULTILINE))
    for path in JS_FILES:
        used = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", path.read_text(encoding="utf-8")))
        missing = sorted(used - defined)
        assert not missing, f"{path.relative_to(ROOT)} uses undefined CSS variables: {missing}"


def test_panel_views_are_not_referenced_by_names_they_no_longer_have():
    """A renamed view leaves a dead comparison behind, and it fails silently.

    The CW panel's speed controls were gated on `s.view === "practice"` after
    the view was renamed to "trainer", so the trainer sent at whatever speed
    happened to be in local storage and offered no way to change it. Nothing
    threw. This checks every string compared against `s.view` is a view the
    panel actually has.
    """
    for path in sorted((WEB / "panels").glob("*/panel.js")):
        source = path.read_text(encoding="utf-8")
        declared = re.search(r"^const VIEWS = \[([^\]]*)\]", source, re.MULTILINE)
        if not declared:
            continue
        views = set(re.findall(r'"([^"]+)"', declared.group(1)))
        compared = set(re.findall(r's\.view === "([^"]+)"', source))
        unknown = sorted(compared - views)
        assert not unknown, f"{path.relative_to(ROOT)} compares s.view to unknown views: {unknown}"

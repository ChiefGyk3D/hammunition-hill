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
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

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

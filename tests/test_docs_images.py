# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The screenshots in the docs, and whether they still describe the program.

A stale screenshot is worse than none: it is a confident claim about what the
software looks like, made by a version that no longer exists, and nothing about
it looks wrong. So the images are generated (`make screenshots`, the same script
the frontend CI job runs) rather than taken by hand, and these checks make sure
the set stays in step with the dashboards the code actually defines.

What this cannot check is whether an image is *current* -- only a person looking
at it can say that. What it can check is that one exists for every dashboard,
that nothing references a file that is not there, and that no orphan is left
behind when a dashboard is renamed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
MARKDOWN = sorted([*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")])

# The slug render_check.py writes each dashboard's screenshot under.
DASHBOARDS = json.loads((ROOT / "web" / "panels" / "index.json").read_text())["dashboards"]


def slug(name: str) -> str:
    """Must match the slug in .github/scripts/render_check.py."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower())


# Absolute links to this repository's own files, which is how the README has to
# spell them -- see test_the_readme_links_images_absolutely below.
RAW = "https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/"


def referenced_images(text: str) -> set[str]:
    """Every image a document points at, as a repository-relative path.

    Three spellings appear: markdown `![](path)`, the `<img src>` and `<a href>`
    of the gallery. A raw.githubusercontent link to this repository is folded
    back to the path it names, so a README written in absolute URLs is checked
    against the files on disk exactly as a relative one would be. Without that,
    switching the README to absolute links would have made every check in this
    file pass on an empty set.
    """
    markdown = re.findall(r"!\[[^\]]*\]\(([^)\s]+)", text)
    html = re.findall(r'<img[^>]+src="([^"]+)"', text)
    anchors = re.findall(r'<a[^>]+href="([^"]*docs/images/[^"]+)"', text)

    found = set()
    for ref in [*markdown, *html, *anchors]:
        if ref.startswith(RAW):
            found.add(ref[len(RAW) :])
        elif not ref.startswith(("http://", "https://")):
            found.add(ref)
        # Anything else points at somebody else's server, which is not ours to
        # check and not something this README should be doing.
    return found


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: p.name)
def test_every_referenced_image_exists(path):
    """A broken image on GitHub renders as alt text and a grey box."""
    refs = referenced_images(path.read_text(encoding="utf-8"))
    for ref in refs:
        # A folded absolute URL is repo-relative; a plain relative path is
        # relative to the document. Try the document first, then the root.
        candidates = [(path.parent / ref).resolve(), (ROOT / ref).resolve()]
        assert any(c.exists() for c in candidates), (
            f"{path.name} references {ref}, which does not exist"
        )


@pytest.mark.parametrize("dash", DASHBOARDS, ids=lambda d: d["id"])
def test_every_dashboard_has_a_screenshot(dash):
    """Adding a dashboard and not showing it is how a README goes stale."""
    expected = IMAGES / f"{slug(dash['name'])}.png"
    assert expected.exists(), (
        f"no screenshot for the {dash['name']!r} dashboard -- run `make screenshots`"
    )


def test_no_screenshot_is_left_over_from_a_dashboard_that_is_gone():
    """The other direction: a renamed dashboard leaves its old image behind, and
    the README goes on displaying a page that no longer exists."""
    expected = {f"{slug(dash['name'])}.png" for dash in DASHBOARDS}
    actual = {path.name for path in IMAGES.glob("*.png")}
    orphans = sorted(actual - expected)
    assert not orphans, f"docs/images has screenshots for no current dashboard: {orphans}"


def test_every_dashboard_screenshot_is_shown_in_the_readme():
    """Six dashboards and five pictures is a README that quietly hides one."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    shown = referenced_images(readme)
    for dash in DASHBOARDS:
        ref = f"docs/images/{slug(dash['name'])}.png"
        assert ref in shown, f"the README never shows the {dash['name']!r} dashboard"


def test_the_screenshots_are_a_reasonable_size_for_a_git_repository():
    """They are regenerated on every visual change, so each one is a new blob in
    history forever. A megabyte apiece would be a problem within a year."""
    for path in sorted(IMAGES.glob("*.png")):
        size = path.stat().st_size
        assert size < 1_000_000, f"{path.name} is {size / 1000:.0f} kB -- too big to keep redoing"
        assert size > 2_000, f"{path.name} is {size} bytes -- did the render fail?"


def test_the_makefile_can_regenerate_them():
    """The rule that makes this maintainable rather than a chore people skip."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^screenshots:", makefile, re.MULTILINE), "no `make screenshots` target"
    assert "RENDER_SHOTS=docs/images" in makefile, (
        "`make screenshots` does not point the render script at docs/images"
    )


def test_the_slug_here_matches_the_one_the_render_script_writes():
    """These are two copies of the same rule and the whole file rests on them
    agreeing. If the script changes its slug, every check above goes vacuous."""
    script = (ROOT / ".github" / "scripts" / "render_check.py").read_text(encoding="utf-8")
    assert "tab.toLowerCase().replace(/[^a-z0-9]+/g, '-')" in script, (
        "render_check.py changed how it names screenshots -- update slug() here"
    )


def test_the_readme_links_images_absolutely():
    """A relative image path renders on GitHub and nowhere else.

    `pyproject.toml` sets `readme = "README.md"`, so this file ships as the
    package long description. PyPI has no repository to resolve `docs/images/`
    against and renders a blank box; `twine check --strict` does not look at
    images, so the `build` job passes and nobody finds out until the project
    page is up.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    markdown = re.findall(r"!\[[^\]]*\]\(([^)\s]+)", readme)
    html = re.findall(r'<img[^>]+src="([^"]+)"', readme)
    relative = sorted(ref for ref in [*markdown, *html] if not ref.startswith("https://"))
    assert not relative, (
        f"README.md links images relatively: {relative}. They render on github.com "
        f"and break on PyPI, which also serves this file. Use {RAW}<path>."
    )


def test_the_readme_only_shows_images_from_this_repository():
    """The other half: absolute is not a licence to hotlink somebody's server.

    A README that pulled an image from an arbitrary host would leak a request
    to it on every view of the project page, which is precisely the posture
    this project exists to avoid.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    sources = re.findall(r'<img[^>]+src="([^"]+)"', readme)
    sources += re.findall(r"!\[[^\]]*\]\((https?://[^)\s]+)", readme)
    foreign = sorted(ref for ref in sources if not ref.startswith(RAW))
    assert not foreign, f"README.md loads images from elsewhere: {foreign}"

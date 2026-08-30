# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The release is a claim about a version number. These check the claim.

A release goes wrong in quiet ways: a wheel whose metadata says one version
while the CLI prints another, a tag with no changelog entry behind it, a
changelog whose newest section is not the version being shipped. Each of those
is invisible until someone downloads the artefact and finds two answers to
"what am I running".

The release workflow makes the same checks on the runner before publishing.
These run in `make check`, so the answer arrives while the change is still in
front of you rather than after a tag has been pushed and has to be deleted.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path

import pytest

from hammunition_hill import __version__

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
RELEASE_WORKFLOW = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")
# "## [1.0.0] — 2026-08-30", em dash or hyphen, because both get typed.
SECTION = re.compile(r"^## \[(?P<version>[^\]]+)\](?:\s*[—-]\s*(?P<date>[\d-]+))?", re.M)


def sections() -> list[tuple[str, str | None]]:
    return [(m.group("version"), m.group("date")) for m in SECTION.finditer(CHANGELOG)]


def released() -> list[tuple[str, str | None]]:
    return [(v, d) for v, d in sections() if v.lower() != "unreleased"]


# --- the version is one number, in one place ------------------------------
def test_the_version_is_semver():
    assert SEMVER.match(__version__), f"{__version__!r} is not a semantic version"


def test_pyproject_does_not_carry_a_second_copy_of_the_version():
    """Two hand-edited copies is one too many; they drift at the worst moment."""
    assert "version" in PYPROJECT["project"].get("dynamic", []), (
        "pyproject should declare version dynamic, not restate it"
    )
    assert PYPROJECT["project"].get("version") is None
    attr = PYPROJECT["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "hammunition_hill.__version__"


def test_the_installed_metadata_agrees_with_the_module():
    """What `pip show` reports and what `hamhill --version` prints, in one test."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("hammunition-hill")
    except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
        pytest.skip("package is not installed in this environment")
    assert installed == __version__, (
        f"installed metadata says {installed}, the module says {__version__}. "
        "After a version bump an editable install keeps the old .dist-info: "
        "reinstall (`pip install -e .` / `uv pip install -e .`) and run again."
    )


# --- the changelog is a real record ---------------------------------------
def test_the_changelog_has_a_section_for_this_version():
    """The release workflow greps for exactly this, and refuses the tag without it."""
    versions = [v for v, _ in released()]
    assert __version__ in versions, (
        f"CHANGELOG.md has no '## [{__version__}]' section. "
        f"It has: {versions[:5]}. A release without an entry is a release "
        "nobody can read the shape of."
    )


def test_the_newest_released_section_is_the_current_version():
    """A changelog whose top entry is not what ships teaches people to distrust it."""
    newest = released()[0][0]
    assert newest == __version__, (
        f"the newest changelog section is {newest} but the package is {__version__}"
    )


def test_every_released_section_carries_a_date_that_is_not_in_the_future():
    today = date.today()
    for version, stamp in released():
        assert stamp, f"{version} has no date"
        when = date.fromisoformat(stamp)
        assert when <= today, f"{version} is dated {when}, which is in the future"


def test_released_sections_descend():
    def key(v: str) -> tuple[int, ...]:
        return tuple(int(part) for part in SEMVER.match(v).groups()[:3])

    order = [key(v) for v, _ in released()]
    assert order == sorted(order, reverse=True), "changelog sections are out of order"


def test_the_changelog_keeps_an_unreleased_heading():
    """Where the next change goes. Without it, the next one lands in the release."""
    assert any(v.lower() == "unreleased" for v, _ in sections())


def test_every_released_section_has_a_link_definition():
    """A version heading whose link goes nowhere renders as broken markdown."""
    for version, _ in released():
        assert f"[{version}]: https://" in CHANGELOG, f"{version} has no link definition"


# --- the workflow checks the same things ----------------------------------
def test_the_release_workflow_refuses_a_mismatched_tag():
    """The check that makes a hand-typed tag safe. Its absence is silent."""
    assert 'if [ "v$version" != "$TAG" ]' in RELEASE_WORKFLOW
    assert 'grep -q "^## \\[$version\\]" CHANGELOG.md' in RELEASE_WORKFLOW


def test_the_release_workflow_installs_the_built_wheel_before_publishing():
    """Packaging has broken web/ once. Publishing an unopened box is how it ships."""
    assert "pip install --disable-pip-version-check dist/*.whl" in RELEASE_WORKFLOW
    assert "check --offline" in RELEASE_WORKFLOW


def test_the_release_workflow_publishes_checksums():
    assert "sha256sum" in RELEASE_WORKFLOW


def test_the_release_workflow_verifies_the_tag_object():
    """--verify-tag refuses to invent a tag that is not already pushed."""
    assert "--verify-tag" in RELEASE_WORKFLOW


def test_only_the_publish_job_can_write():
    """The build job installs third-party code; it must not hold a write token."""
    body = RELEASE_WORKFLOW.split("  publish:")[0]
    assert "contents: write" not in body, (
        "a job before publish grants contents: write -- keep the write token out "
        "of the job that runs pip install"
    )

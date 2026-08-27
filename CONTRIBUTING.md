# Contributing

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
| `lint` | ruff, including the security rules |
| `test` | pytest on 3.11–3.13, on x86, ARM and macOS |
| `example-config` | the file every new user copies having rotted |
| `smoke` | the collector→snapshot→HTTP loop breaking, and the security headers going missing |
| `frontend` | a panel that throws, or the browser reaching a host it should not |
| `audit` | advisories against the two runtime dependencies |
| `build` | a wheel that builds but does not install |
| `upstreams` | *(weekly)* an upstream host disappearing |

ARM is in the matrix because a Raspberry Pi is the primary deployment target,
not an afterthought.

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

Hand-formatted; `ruff format` is deliberately not enforced. Match the
surrounding code. Line length, import order and the security rules are checked
by `ruff check`, which `make lint` runs.

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

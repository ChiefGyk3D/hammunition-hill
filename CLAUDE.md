# Hammunition Hill — Claude Code Context

A ham radio dashboard that runs on your own machine, on your own network, and
talks to nobody you did not name. Companion to
[Hammunition](https://github.com/ChiefGyk3D/Hammunition).

Binary: `hamhill`. Python package: `hammunition_hill`. Licence: MPL-2.0.

---

## Standing rule: robust CI and tests are not optional

**Every project here gets working CI and a real test suite. Treat their absence
as a defect to fix, not a state to work around.** This is a maintainer
preference, stated once and applying from here on — do not wait to be asked
again, and do not let a feature branch land in a repo that has no way to check
itself.

What "robust" means in practice, learned the hard way in this repo:

- **Put checks in the test suite; let CI run the test suite.** A CI-only script
  rots, because nobody can run it locally and nobody notices when it stops
  meaning anything. `make check` must reproduce the pipeline minus the matrix.
- **A check must be falsifiable.** Before trusting a new check, break the thing
  it watches and confirm it goes red with a message naming the fix. Several
  checks here were verified this way; one of them (hardcoded external URLs) was
  silently passing on the exact input it existed to catch, because naive
  comment-stripping ate the `//` in `https://`.
- **Test the matrix, not just your machine.** The ElementTree truthiness bug in
  `lookup/session_xml.py` passed on 3.11 — the dev venv — and failed on 3.12+.
  It was a real bug, not a warning to silence. The matrix earned its place on
  its first run.
- **A check nobody trusts is worse than no check.** Two things are deliberately
  not enforced for this reason: `ruff format --check` (would reflow 36
  hand-formatted files for no defect caught) and whole-environment dependency
  auditing (would report advisories against the runner's own pip). Both are
  documented in `.github/workflows/ci.yml` with the reasoning.
- **Prove properties, not just behaviour.** `tests/conftest.py` blocks every
  socket to anywhere but loopback, so the suite cannot quietly depend on the
  real internet. `tests/test_status_doc.py` asserts the feature counts in the
  README against the code, because the README claimed twelve panels for months
  after there were nineteen.
- **Run it and look at it.** Tests pass on things that are visibly wrong. The
  A-index dial read "Quiet" while looking alarming; a Severe Thunderstorm
  Warning sorted above a Tornado Warning; the greyline was invisible. All three
  passed every test and were found by rendering the page. `.github/scripts/`
  has a smoke test and a browser render for exactly this.
- **Measure before claiming.** The FCC ULS importer's first version would have
  needed ~620 MB of RAM at real scale — more than a Pi Zero has — while its
  docstring claimed the opposite. Measuring changed the design to a streaming
  one at ~4 MB, flat.

Run before pushing: `make check`. Heavier: `make smoke`, `make render`,
`make audit`, `make build`. See `CONTRIBUTING.md`.

---

## Architecture invariants

These are the load-bearing properties. A change that breaks one is wrong even
if it passes.

1. **No request causes a fetch.** The collector polls on a fixed schedule and
   writes atomic JSON snapshots; the server reads bytes from disk and sends
   them. There is no code path from the HTTP server into the collector. Nothing
   an attacker sends can steer an outbound request.
2. **Sources never construct URLs.** The full URL, query string included, lives
   in `config.toml`. A source that assembles a query from a response turns
   "nothing we read changes what we fetch" from an architectural property into
   a per-source audit. This is why `nws_alerts` takes its area filter in the
   configured URL.
3. **Egress is a closed allowlist**, and every resolved address is checked, not
   just the first. Private, loopback and reserved addresses are refused unless
   a source opts in with `local = true`.
4. **Three tiers, declared honestly.** Tier 0 originated nothing off this
   machine; tier 1 the collector fetched; tier 2 the browser loads foreign
   content. The tier is shown in the UI. Tier is about *reach*, not whether a
   file is involved.
5. **The CSP is derived from config**, never hand-maintained. `[[imagery]]`
   hosts reach `img-src` only — an image cannot run script, a frame from the
   same host can — and are deliberately absent from the collector's egress
   allowlist. Two nearly-identical lists; the smaller one is smaller on purpose.
6. **Degrade honestly.** Keep the last good snapshot with `fetched_at` and the
   failure reason. A stale panel and a blank panel are different problems, and
   with the WAN down that distinction is the point.
7. **The browser renders with `textContent`.** No `innerHTML`, no `eval`, no
   hardcoded external URLs in `web/`. Enforced by `tests/test_frontend.py`.

## Conventions

- **Local and LAN first.** No authentication by design; the network is the
  access control. Loopback by default, and binding wider prints a warning every
  time. Never suggest exposing it to the internet — ZTNA or a VPN (Twingate,
  NetBird, Tailscale, Headscale, WireGuard).
- **Opt in, one line at a time.** Lookup providers, the logbook, imagery tiles
  and LAN binding are all off by default, because each costs something real.
- **Hand-formatted.** Match the surrounding code; `ruff check` enforces what
  matters. Comments explain *why*, especially where an obvious-looking
  alternative is wrong.
- **Alpha: merge to main.** Feature branch → PR → squash merge. Keep README and
  every affected doc current in the same PR.
- **`docs/STATUS.md` is the feature inventory** and the page kept current;
  `docs/PARITY.md` answers the narrower "how does this compare to hamdash.com".
  `tests/test_status_doc.py` fails when the counts drift.
- **Correct the record.** Where an earlier decision was wrong, say so in the
  doc rather than quietly changing it — `docs/LOGBOOK.md` opens with the
  reversal, and `docs/IMAGERY.md` corrects a proxying rationale that did not
  hold up.

## Known gaps

`docs/STATUS.md` is authoritative. The ones most likely to bite:

- The wheel carries the CLI and **not** `web/`. A git clone is the supported
  install; `serve` and `check` now say so rather than serving 404s.
- `query_endpoint` parses and does nothing. Designed, not built.
- Upstream endpoint URLs rot and several could not be verified from the build
  environment. `hamhill check` on real hardware is how that gets found.

## Sibling projects

`ChiefGyk3D/solarstorm_scout` and `ChiefGyk3D/penguin-overlord` are the same
author's, both MPL-2.0, so logic ports by copy-paste. See `docs/REUSE.md`.
Porting is not copying: solarstorm_scout's D-layer model uses
`abs(utc_hour - 12)` as a solar-noon proxy, which is correct for a global bot
and about five hours wrong for a US east-coast operator. This project knows the
grid square, so the port must compute a real solar zenith.

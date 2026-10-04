# Changelog

Notable changes, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at 1.0.0. Everything before it happened in the open — every
feature below arrived as its own reviewed pull request against `main`, and
`git log` is the finer-grained record — but there were no releases to write
entries for, and inventing them retroactively would be a worse history than
saying so.

## [Unreleased]

### Security

- Security and quality sweep of the CodeQL, Semgrep and Scorecard findings: the
  satellite sub-point radius uses `math.hypot` (the naive form overflowed), the
  ULS lookup log line carries a sanitised callsign, the CSP tests parse the
  directive instead of matching a substring, the session-XML provider hooks
  raise `NotImplementedError` rather than returning `None`, the Dockerfile
  and CI install from hash-checked locks (`requirements/`) on digest-pinned
  base images, and the repository gains `SECURITY.md`.

### Added

- **Atheris fuzz targets for the parsers** (`fuzz/`), run on every pull request
  for 30 s each and weekly for 600 s each by the shared GYST `python-fuzz.yml`
  (`fuzz` in `ci.yml`, and in `all-green`'s `needs`): the RBN and DX cluster
  streams, the gpsd JSON and NMEA lines, the FCC ULS importer, the HamQTH and
  QRZ XML, the NOAA SWPC, scales, alerts, HamQSL and ionosonde feeds, and the
  Celestrak element sets. `tests/test_fuzz_targets.py` keeps them honest in the
  ordinary suite.

### Changed

- **Every GYST caller moves from v1.6.3 to v1.10.0** (one pin, as the pin test requires). No input the callers pass was renamed or removed. New defaults now apply: Snyk runs weekly, the Semgrep job's egress is `block`, and `container-release` runs hadolint, requires a non-root image and fails on Trivy findings that have a fix.

### Fixed

- **A checksum-valid element set with nonsense elements no longer reaches SGP4.** An epoch day of 1.1e11 makes the C propagator loop without returning, and `upcoming()` calls it inline from the collector, so one such set in a Celestrak listing would have frozen the dashboard. `parse_tles` now checks the epoch, angles, eccentricity and mean motion against their physical ranges. Found by the new fuzz target's first CI run (a hang, not a crash).
- **A Unicode digit in an element set no longer crashes the parser.**
  `tle_checksum` summed `int(char)` for every `char.isdigit()`, which is also
  true of `²` and `⓼`; `parse_tles` raised `ValueError` out of the Celestrak
  fetch instead of skipping that one satellite. Found by the new fuzz target.
- **The SWPC feeds answer a wrong shape with `FetchError`.** Valid JSON that was
  not the feed (`null`, a number, a list of non-objects, a non-numeric `Kp` or
  `flux`) raised `TypeError`, `AttributeError` or `ValueError` out of `fetch`;
  rows that cannot be read are skipped and a feed with none left is a
  `FetchError`. Found by the new fuzz target.

## [1.2.0] — 2026-10-04

### Added

- **Repeaters panel (tier 0)**, closing #82. The collector runs two read-only
  Hammunition commands (`maps repeaters list --json`, `station show --json`)
  and stores the layers with distance and bearing from the grid square's
  centre; the panel filters by band, mode, source and distance in the browser,
  prints the credits, and the map gains an off-by-default RPTR layer. Rows the
  engine marks `personal_use` (RepeaterBook, D-081) are served to this
  machine's own page only: any other host, or any proxied request, gets the
  snapshot without them, and nothing exports them. The centre defaults to the
  station; a typed grid, coordinates or a map click or long press can replace
  it (remembered in the browser only, distances recomputed there), and a centre
  far from every row says the data is only what was imported. `[repeaters] enabled`.
  See [docs/REPEATERS.md](docs/REPEATERS.md).
- **Repeaters by mode and band**, closing #84. One multi-select chip per mode
  (FM, DMR, D-STAR, YSF, P25, NXDN, M17, TETRA, ATV) and per band present, each
  with its count, plus DIGITAL and ANALOG shortcuts, composing with the centre,
  source and within-km filters and remembered in the browser. Rows show the
  details an operator keys in (DMR colour code and network, D-STAR module, YSF
  DG-ID, P25 NAC, NXDN RAN) and nothing for a detail the source did not supply.
  Reads the engine's `modes`, `digital` fields (Hammunition #316); an older
  engine still works, without chips, and the MODE row says to update it. The
  map's RPTR layer follows the same filters.

### Changed

- **CI runs through git-your-ship-together's reusable workflows**, pinned by
  commit: `python-ci.yml` (lint, the pytest matrix, smoke, container build,
  workflow lint), `security.yml` (CodeQL, gitleaks, Semgrep, dependency review
  and audit, replacing `codeql.yml`) and `artifact-release.yml` (the release,
  now signed, with provenance). The browser render, the Debian container job
  and the weekly upstream check stay local, with an `all-green` aggregate.
  Branch protection must require `ci / CI green`, `shell / CI green`,
  `all checks passed` and `package / Build, verify`. This completes #79, which
  moved the generic legs and left the browser render, the example-config and
  smoke checks, the Debian container job, the weekly upstream check and the
  workflow tests out of CI.

## [1.1.0] — 2026-09-28

### Added

- **A parity page against [OpenHamClock](https://github.com/accius/openhamclock)**,
  walked against its own panel registry rather than its README —
  `docs/OPENHAMCLOCK.md`. Sixty-eight of their built-in panels against our
  thirty-three, in both directions, with the differences that are *decisions*
  separated from the ones that are gaps. The deployment trade-off that drives
  most of the rows is stated at the top: theirs is an Express proxy that
  fetches when a browser asks, ours is a collector on a schedule with no code
  path from the server into it.
- **Azimuthal equidistant projection** on the map — `AZ` in the view row,
  centred on your station. Every bearing out of the middle is a straight line
  and distance along it is linear to the antipode on the rim, which is the
  projection HamClock made its default and the one a beam operator actually
  wants. `tests/test_globe_projection.py` asserts exactly that against
  `geo.py`'s own bearings and distances, because a projection that is subtly
  wrong still draws a convincing coastline.
- **Sun & Moon panel** (tier 0) — sunrise, sunset, transit, daylight length and
  the civil-twilight greyline window; moonrise, moonset, phase, illuminated
  fraction, distance, live look angles and how much of the EME window is left.
- **Meteor Showers panel** (tier 0) — which of the IMO major showers are
  running, when each peaks, and where its radiant is in *your* sky now, which
  is the thing that decides whether meteor scatter is worth trying. The panel
  says on its face that ZHR is a visual rate and not what you will hear.
- **Frequencies panel** (tier 0) — memory channels with export and import,
  each one checked against the band plan for your licence class. A memory is a
  frequency you are about to key up on, and a list that silently contains one
  you may not transmit on is worse than no list, because it looks checked.
- **`ephemeris.py` and `web/lib/ephemeris.js`** — where the moon is, and when
  either body rises, sets or transits here. Two implementations of the
  *Astronomical Almanac*'s low-precision series, pinned to each other by
  `tests/test_ephemeris_drift.py` and to Meeus's worked example and two known
  syzygies by `tests/test_ephemeris.py`. The accuracy is stated on the panel
  rather than implied: half a moon-width, which is fine for planning a window
  and not fine for pointing a dish open-loop.

- **Ionosondes panel** (tier 1) — measured `foF2` and MUF(3000) from the GIRO
  and NOAA sounder networks via KC2G, ranked by distance from your station,
  because the sounder 200 km away is about *your* path and one on the far side
  of the world is a fact about somewhere else. This is the only propagation
  input here that is measured rather than modelled; where a sounder is near the
  path it beats MINIMUF outright.

  The fetch was the easy half. The feed is a **roster, not a snapshot** — every
  station KC2G knows about appears in every response carrying whatever sounding
  it last managed, and in a real response Austin reported `fof2` 8.6 with a
  confidence score of 100 and a timestamp six months old, while Beijing carried
  a reading from 2021. Publishing those beside a live sounding would have put a
  precise, confident, badly wrong number on the panel, which is the failure the
  proton dial already exists to avoid. Anything older than 90 minutes is
  dropped and the count of what went is published, so the panel can tell "the
  sounders are quiet" from "we discarded the feed". Worth recording that the
  confidence score does *not* catch this: it grades how well a sounding was
  scaled, not when it was taken, and the stale reading outscored every live one.

### Changed

- **The flat map's greyline is solved rather than traced.** It was drawn by
  projecting the terminator ring and sorting the points by screen x, which
  assumes the curve is a function of x; near an equinox it is not, and at the
  March 2026 equinox 361 ring points land on 18 distinct columns against 344 at
  the solstice. It is worth saying what that did and did not cost, because the
  first write-up of it here overstated the case: the sorted points all still
  lay on the terminator, so the shading was correct — 0.00% of a 65,000-point
  grid mis-shaded, measured against `solarElevation` from 0.06 to 23.4 degrees
  of declination — and the two versions render within a pixel of each other.
  Nothing visible was wrong. What was missing was any reason to believe that:
  correctness rested on disordered points cancelling out in the fill.
  `flatTerminator()` now solves `tan(lat) = -cos(lon - lonSun) / tan(dec)` per
  column, single-valued by construction, and `tests/test_flat_terminator.py`
  pins the greyline against `solarElevation` for the first time — every drawn
  point on the horizon, the shaded side the dark side, over a grid.
- **`docs/HAMCLOCK.md` corrects its own KC2G gate.** 1.0.1 shipped the page
  saying to write to KC2G before any source polled his API. That confused
  redistribution, which is what HamClock's backend does and what its
  permission covers, with one operator's collector reading public JSON on a
  timer. The page now says so, and the `ionosonde` source ships on by default
  at a 900 s interval with KC2G and GIRO credited where the numbers are read.

## [1.0.1] — 2026-09-28

### Security

- A callsign that failed a ULS lookup was written to the log with `%s`, so a
  callsign carrying control characters — and callsigns arrive from DX
  cluster spots and WSJT-X decodes, which are other people's text — could
  forge a log line. It is logged with `%r` now, escaped and quoted (#75, a
  CodeQL `py/log-injection` finding).

### Added

- `docs/HAMCLOCK.md`: feature by feature against HamClock's user guide and
  the open continuation, what "MUF" means in each of its four uses, and every
  endpoint fetched on 2026-09-13, the dead ones included (#63).

### Changed

- **The record on VOACAP is corrected.** `docs/STATUS.md` and
  `docs/PROPAGATION.md` said bundling the ITSHFBC binaries was the only route
  to it. `voacapl` is a Debian package and ran a full point-to-point table in
  17 ms; the pages now say so, along with its one hazard — a missing antenna
  file makes it hang silently (#63).

### Fixed

- The release workflow built only the wheel and the sdist, so **v1.0.0
  published without the Debian package** that `docs/INSTALL.md` tells operators
  to download. The `.deb` was built from the v1.0.0 tag, installed and served
  on Debian 13, and attached to that release by hand, with `SHA256SUMS`
  regenerated over all three artefacts. The workflow now builds the package,
  installs it in a `debian:trixie-slim` container and makes it answer before
  publishing, so the next release cannot miss it.

## [1.0.0] — 2026-08-30

The first release. Alpha ended when the dashboard had been run against real
upstreams on real hardware, every configured endpoint had been fetched and
parsed rather than assumed, and there was a package to install rather than a
repository to clone.

### The shape of it

A ham radio dashboard that runs on your own machine, on your own network, and
talks to nobody you did not name. A collector polls upstream sources on a fixed
schedule and writes atomic JSON snapshots; a static file server hands those
files to the browser. No request causes a fetch, so nothing an attacker sends
can steer an outbound one.

- **30 panels across 7 dashboards** — Home, Map, Space Weather, Operating,
  Toolbox, Activity, Field & Weather.
- **20 source kinds** — 13 polled, 6 streamed, 1 read from a local file.
- **Space weather**: eight NOAA scales, solar flux, K index, X-ray flux,
  protons, aurora oval, SWPC alerts, all as dials that agree with NOAA's own
  wording rather than a scale of their own.
- **Propagation**: MUF, LUF and D-layer absorption computed from a real solar
  zenith angle at your grid square, plus the DX Path chart (MINIMUF 3.5).
- **Your log drives the display**: ADIF in, needed-slot colouring on every
  spot, DXCC and Worked All States progress with honest denominators.
- **Operating**: DX cluster, Reverse Beacon Network, WSJT-X, `rigctld`, PSK
  Reporter and WSPR reception reports, POTA/SOTA, contests, satellites with
  Doppler and look angles, NCDXF beacons.
- **Tools**: antenna and feedline calculators, Ohm's law, decibels, wire and
  battery sizing, grid-path distance and bearing, CW/Morse with audio, a
  pocket reference, the US band plan by licence class, and licence exam
  practice across all three US pools.
- **Field**: GPS auto-grid, NWS alerts with real severity ordering, radar and
  satellite imagery, and an opaque image mode for operators who would rather
  the collector fetch a tile than the browser.

### Security posture

- Egress is a closed allowlist, and every resolved address is checked — not
  just the first.
- Sources never construct URLs; the full URL lives in `config.toml`.
- The Content-Security-Policy is derived from that config and cannot drift.
- Three tiers, declared in the UI: tier 0 originated nothing off this machine,
  tier 1 the collector fetched, tier 2 the browser loads foreign content.
- No authentication, deliberately, and no settings endpoint at all: the
  absence of a write path *is* the model. Reach it over ZTNA or a VPN, never
  a port forward. See [docs/SECURITY.md](docs/SECURITY.md).

### Added in the run-up to 1.0

- `hamhill setup` — a guided first config that names, before each opt-in,
  exactly what saying yes will send and to whom.
- `hamhill check --fetch` — fetches every configured source once through the
  real client, guard and parser, so "the host resolves" and "this program
  still understands the answer" stop being the same claim.
- A 2D map beside the 3D globe, path plotting with distance and both
  bearings, and distance-on-click for any spot.
- A browser-side callsign and QTH, per display, with the collector's own
  identity left in `config.toml` where it belongs.
- Kiosk rotation for the wall display, watch-list notifications for callsigns
  and band openings, and an about card with the project's own links.
- Debian packaging: `hamhill` installs as a service, with a system user, a
  config in `/etc/hammunition-hill/`, and a hardened systemd unit.

### Fixed

- **`Permissions-Policy: geolocation=()` disabled the dashboard's own
  geolocation**, not merely embedded content — so **FIND MY GRID** on the map
  could never work, in any browser, for any operator, and the panel reported a
  permission denial for a prompt nobody was ever shown. It is `(self)` now;
  camera, microphone, USB and payment stay fully denied.
- **The Debian package installed a service it never enabled.** `postinst` used
  `deb-systemd-helper was-enabled` to tell a first install from an upgrade, and
  that answered differently on Debian and on Kali. It now uses the argument
  dpkg already provides, so a first install enables and starts while an upgrade
  leaves a deliberately stopped service alone.
- **The packaged config wrote its snapshots under `/etc`**, which the unit
  makes read-only, so the service crash-looped on its first write. The build
  rewrites `data_dir` and refuses to produce a package if the line it rewrites
  is not there.

### Known limits, stated plainly

- Band plans and exam pools are **US only**. The loaders are generic and the
  schema is tested; another regulator's allocations are a contribution from
  someone who transmits under them.
- Propagation is an **indicator, not a prediction**. VOACAP answers a question
  this does not.
- Weather outside the US is feeds and images, without structured severity.

[Unreleased]: https://github.com/ChiefGyk3D/hammunition-hill/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/ChiefGyk3D/hammunition-hill/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ChiefGyk3D/hammunition-hill/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/ChiefGyk3D/hammunition-hill/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ChiefGyk3D/hammunition-hill/releases/tag/v1.0.0

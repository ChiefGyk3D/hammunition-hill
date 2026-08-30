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

[Unreleased]: https://github.com/ChiefGyk3D/hammunition-hill/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ChiefGyk3D/hammunition-hill/releases/tag/v1.0.0

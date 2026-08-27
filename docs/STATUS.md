# Status: what works, what doesn't

Complete feature inventory. Every subsystem, honestly marked.

**Version 0.1.0 — alpha.** It runs, it is useful, and it is not finished. The
distinction this page cares about is between *working*, *partial*, and *not
written*, because "planned" in a README has a habit of reading like "present".

Legend: ✅ working · 🟡 partial · ❌ not written · ⛔ deliberately not planned

Related pages answer different questions. [PARITY.md](PARITY.md) asks *how does
this compare to hamdash.com*, feature by feature against their published guide.
This page asks *what can I use today*, including everything hamdash does not
have. Where the two disagree, this page is the one kept current.

---

## At a glance

| | Status |
|---|---|
| Collector, snapshot architecture, static server | ✅ working |
| Egress allowlist, CSP, path handling | ✅ working |
| Panels | ✅ 20 across 6 dashboards |
| Source kinds | ✅ 10 polled, 3 stream, 1 file |
| Space weather dials | ✅ 8 scales |
| Your log driving spot colouring | ✅ working |
| Rig and WSJT-X integration | ✅ working |
| Logbook | ✅ working, off by default |
| Callsign lookup | ✅ 4 providers, chained, offline-capable |
| Band plans | 🟡 US only |
| Propagation | 🟡 MUF/LUF/absorption indicator; **no VOACAP** |
| Weather outside the US | 🟡 feeds and images, no structured severity |
| Callsign query endpoint | ❌ **not written** — config flag exists and does nothing |
| GPS / portable auto-grid | ❌ **not written** |
| Satellites | ❌ **not written** |
| RBN | ❌ **not written** |
| CW / Morse tools | ❌ **not written** |
| Metrics export to Grafana | ❌ **not written** |
| Opaque image mode | ❌ **not written** |
| Packaging (Docker, distro packages) | ❌ **not written** |
| CI, CodeQL, dependency audit | ✅ working |

---

## Core

The parts everything else sits on.

| Feature | Status | Notes |
|---|---|---|
| Snapshot collector | ✅ | Fixed schedule in, atomic JSON files out. No request causes a fetch. |
| Static file server | ✅ | Two directories, no routes, no query parsing. |
| Egress allowlist | ✅ | Closed by default. Every resolved address checked, not just the first. |
| Private-address guard | ✅ | Refuses RFC1918/loopback/link-local unless `local = true`. |
| Content-Security-Policy | ✅ | Generated from config; cannot drift from what is enabled. |
| Path traversal handling | ✅ | Components dropped, then containment re-checked. |
| Graceful staleness | ✅ | Last good snapshot kept, with `fetched_at` and the failure reason. |
| Stream self-healing | ✅ | Exponential backoff; one dead stream cannot take down the run. |
| `hamhill serve` / `check` / `fcc-import` | ✅ | |
| Config validation with actionable errors | ✅ | |
| Tests | ✅ | 952, ruff clean. |
| CI | ✅ | Nine jobs: lint, pytest across 3.11–3.13 on x86, ARM and macOS, example-config validation, an end-to-end smoke test, a real-browser render of every dashboard, dependency audit, wheel build, and a weekly upstream-liveness check. |
| CodeQL | ✅ | Python and JavaScript, weekly and per-PR. |
| Dependabot | ✅ | Actions and pip, weekly. |
| Tests cannot reach the network | ✅ | Enforced by a conftest guard, not convention. |
| `make check` reproduces CI locally | ✅ | |
| Docker image | ❌ | systemd is documented; a container is not built. |
| Distro packages | ❌ | |

## Sources

**Polled** (10 kinds): `swpc`, `hamqsl`, `rss`, `pota`, `sota`, `ics`, `aurora`,
`noaa_scales`, `swpc_alerts`, `nws_alerts`.
**Stream** (3): `dxcluster`, `wsjtx`, `rigctl`.
**File** (1): `adif`.

| Feature | Status | Notes |
|---|---|---|
| NOAA SWPC space weather | ✅ | K, A, SFI, X-ray, solar wind, protons, noise |
| HamQSL solar XML | ✅ | N0NBH's band conditions |
| RSS / Atom feeds | ✅ | Parsed here, stripped to text. No third-party JSON proxy. |
| iCalendar | ✅ | Generic, so any contest calendar works |
| POTA / SOTA spots | ✅ | |
| OVATION aurora | ✅ | Quarter-million points reduced to oval + cells before publishing |
| NOAA R/S/G scales, SWPC alerts | ✅ | |
| NWS weather alerts | ✅ | Sorted on NWS severity, coloured on our three-step ramp |
| DX cluster (telnet) | ✅ | Filtered client-side, coloured by what you still need |
| WSJT-X (UDP) | ✅ | Your own decodes, live |
| `rigctld` | ✅ | Live frequency and mode |
| ADIF log ingest | ✅ | Drives needed-slot colouring |
| RBN | ❌ | The cluster client pointed at a different feed; aggregation is the work |
| PSK Reporter | ❌ | |
| Satellite passes | ❌ | Needs cached TLEs and SGP4 |
| WWFF / WWBOTA | ❌ | Same shape as POTA/SOTA |
| Repeater directory | ❌ | RepeaterBook has a public API |
| GPS (gpsd / NMEA) | ❌ | Planned: auto grid square and disciplined time when portable, published at Maidenhead precision rather than raw fix |

## Panels

19 panels, 6 dashboards: **Home**, **Map**, **Space Weather**, **Operating**,
**Activity**, **Field & Weather**. Regroup them by editing
`web/panels/index.json`.

Five are **tier 0** — they work with the internet unplugged: `clock`,
`bandplan`, `beacons`, `callsign`, `logbook`. Fourteen are tier 1. One is
tier 2 (`imagery`).

| Feature | Status | Notes |
|---|---|---|
| Rotatable globe with greyline | ✅ | Orthographic projection on 2D canvas. No WebGL, no library. |
| Spots on the map with great-circle arcs | ✅ | |
| Aurora oval as a globe layer | ✅ | |
| Severity dials | ✅ | 8 scales, with the number alongside — both, not either |
| Colour-blind-safe status ramp | ✅ | Validated for separation; see the comment in `style.css` before changing it |
| NCDXF/IARU beacon schedule | ✅ | Computed offline from the 180-second cycle |
| Band plan by licence class | ✅ | Including grandfathered Novice and Advanced |
| Callsign lookup with bearing and distance | ✅ | Resolves in the browser from the published prefix table |
| Logbook with multiple books | ✅ | Off by default |
| Log statistics | ✅ | |
| Weather alerts | ✅ | |
| Tier 2 imagery tiles | ✅ | Radar, satellite, lightning, solar — one config line each |
| Freshness shown, never hidden | ✅ | Stale and blank are different problems and look different |
| Drag-to-reorder layout | ❌ | Dashboards are configurable in JSON; dragging is not built |
| "AT YOUR QTH" vs "OPEN ELSEWHERE" band pills | ❌ | Spotted in hamdash; outstanding |
| CW / Morse reference tools | ❌ | Tier 0, self-contained, promised and not yet built |
| Ionospheric map | ❌ | |
| Built-in SDR receiver | ⛔ | WebUSB needs a secure context, which would force TLS onto a LAN appliance for one panel. Point a tier 2 panel at your own OpenWebRX+ or KiwiSDR instead. |

## Callsign lookup

| Feature | Status | Notes |
|---|---|---|
| Prefix table (entity, continent, CQ zone) | ✅ | Tier 0, in the browser, nothing sent anywhere |
| Bearing, distance, short and long path | ✅ | Tier 0 |
| Worked/confirmed from your own log | ✅ | Tier 0 |
| `cty.dat` support | ✅ | Falls back to a built-in table documented as approximate |
| Provider chains | ✅ | Ordered, tried left to right |
| `fcc_uls` — offline US index | ✅ | SQLite, no per-lookup network at all |
| `callook`, `hamqth`, `qrz` | ✅ | |
| Offline-aware resolution | ✅ | Network providers skipped when the WAN is gone |
| Stale cache served, flagged | ✅ | An old record beats a blank panel in a field |
| Automatic ULS refresh | ❌ | `fcc-import` is manual on purpose; a scheduled option is not built |
| Query endpoint (`/lookup/<callsign>`) | ❌ | **`query_endpoint = true` parses and does nothing.** The endpoint is designed in [CALLSIGN-LOOKUP.md](CALLSIGN-LOOKUP.md) and not implemented. |

## Propagation

| Feature | Status | Notes |
|---|---|---|
| Band conditions | ✅ | From HamQSL |
| MUF / LUF / D-layer absorption | ✅ | Computed locally from SFI, K and solar zenith at your station. Tier 1 (its inputs are fetched); the arithmetic never leaves the machine. |
| Solar terminator / greyline | ✅ | Computed offline from the solar subpoint |
| MUF predictor | ✅ | Derived from SFI, K and the sun's height over *your* station. An indicator, not a prediction — see [PROPAGATION.md](PROPAGATION.md) |
| D-layer absorption | ✅ | Real solar zenith at your grid square, not a UTC-hour proxy |
| VOACAP point-to-point | ❌ | The genuinely hard one, and still open: this indicator is not it. Either bundle the public-domain ITSHFBC binaries and shell out, or accept that a path-free estimate is where this stops. |
| FT8 propagation globes | ❌ | Needs PSK Reporter |

## Weather

| Feature | Status | Notes |
|---|---|---|
| US alerts (`api.weather.gov`) | ✅ | Tier 1, so it survives the WAN dropping |
| Radar, satellite, lightning imagery | ✅ | Tier 2 tiles |
| Solar imagery (SDO) | ✅ | A tile like any other |
| EU alerts (MeteoAlarm) | 🟡 | Atom feeds and their map work; structured CAP severity needs a `meteoalarm` source |
| Met Office warnings | 🟡 | Warning map as a tile; no structured feed parsed |
| Field weather conditions | ❌ | Needs the `/points` → gridpoint chain done properly rather than letting a source build URLs from a response |
| Opaque image mode | ❌ | Collector-cached tiles, so the browser never contacts a third party. Needs content-type discipline first — see [IMAGERY.md](IMAGERY.md) |

## Data and reference

| Feature | Status | Notes |
|---|---|---|
| US band plan, all licence classes | ✅ | Technician, General, Extra, plus Novice and Advanced |
| Bundled world outline for the globe | ✅ | Natural Earth, public domain, simplified |
| NCDXF beacon list | ✅ | |
| International band plans | ❌ | A data contribution, not a code change — the loader is generic |

## Export and integration

| Feature | Status | Notes |
|---|---|---|
| ADIF import | ✅ | |
| ADIF export | ✅ | The logbook writes plain ADIF; it is the same file |
| Prometheus / InfluxDB export | ❌ | Planned as an optional feature of this project rather than a separate one. It would be the first outbound *write* the collector ever makes, so it belongs in the same opt-in category as the logbook. |
| Grafana dashboard | ❌ | After the exporter |
| VA3HDL `config.js` importer | ❌ | |

## Deployment

| Feature | Status | Notes |
|---|---|---|
| Loopback by default | ✅ | Binding wider is a deliberate act that prints a warning every time |
| systemd unit | ✅ | Documented in [INSTALL.md](INSTALL.md) |
| Kiosk / wall display notes | ✅ | |
| Docker image | ❌ | |
| `pip install` alone | ❌ | The wheel carries the CLI, not `web/`. A clone is the supported install and the CLI now says so instead of serving 404s. |
| Hosted / multi-user mode | ⛔ | Not until there is a real authn/authz model, TLS, rate limiting and a threat model this version deliberately does not have. Reach it over ZTNA or a VPN instead — see [SECURITY.md](SECURITY.md). |

---

## Roadmap order

What is actually being worked on, in order:

1. **GPS** (gpsd and direct NMEA) for portable auto-grid and disciplined time.
2. **RBN**, which is the cluster client pointed somewhere else plus aggregation.
3. **CW / Morse reference tools** — tier 0, self-contained.
4. **Satellites**, which needs real orbital mechanics.
5. **The metrics exporter**, after parity.

Smaller items are listed in [PARITY.md](PARITY.md).

## If you want to help

The things that need no Python:

- **International band plans.** `web/bandplans/` takes one JSON file per
  country and the loader is already generic. See [README](../README.md#band-plans).
- **Imagery tiles that work.** Upstream image URLs rot constantly. A tile that
  is confirmed working in your region is a one-line contribution.
- **Telling us when a source breaks.** Three different spellings of the SWPC
  F10.7 endpoint exist across sibling projects, which means at least two are
  silently failing somewhere. Running `hamhill check` on real hardware and
  reporting what fails is genuinely useful.

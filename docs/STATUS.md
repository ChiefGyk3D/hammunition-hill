# Status: what works, what doesn't

Complete feature inventory. Every subsystem, honestly marked.

**Version 1.0.0.** It runs, it is useful, and every endpoint it ships with has
been fetched and parsed on real hardware rather than assumed. The distinction
this page cares about is between *working*, *partial*, and *not written*,
because "planned" in a README has a habit of reading like "present". 1.0 does
not mean finished — it means the US-first scope is complete, installable, and
honest about its edges.

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
| Panels | ✅ 30 across 7 dashboards |
| Source kinds | ✅ 13 polled, 6 stream, 1 file |
| Space weather dials | ✅ 8 scales |
| Your log driving spot colouring | ✅ working |
| Rig and WSJT-X integration | ✅ working |
| Logbook | ✅ working, off by default |
| Callsign lookup | ✅ 4 providers, chained, offline-capable |
| Band plans | 🟡 US only |
| Propagation | 🟡 MUF/LUF/absorption indicator; **no VOACAP** |
| Weather outside the US | 🟡 feeds and images, no structured severity |
| Callsign query endpoint | ✅ `GET /lookup/<callsign>`, local index only, off by default |
| GPS / portable auto-grid | ✅ working |
| Satellites | ✅ passes, look angles, Doppler |
| RBN | ✅ working |
| CW / Morse tools | ✅ working |
| Licence exam practice | ✅ all three US pools, five study modes |
| Prometheus metrics endpoint | ✅ working, off by default |
| Opaque image mode | ✅ per-tile: the collector fetches, the browser never does |
| Packaging | ✅ Debian `.deb`, Docker image, and a bare `pip install` — all three serve the dashboard |
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
| `hamhill serve` / `check` / `setup` / `fcc-import` | ✅ | `setup` is the guided config: every question that would send the callsign says so first |
| Config validation with actionable errors | ✅ | |
| Tests | ✅ | Suite green with warnings as errors across 3.11–3.13; ruff clean. No count here on purpose — a hand-edited total rots by design, and this one did. |
| CI | ✅ | Eleven jobs, plus CodeQL in its own workflow: lint, pytest across 3.11–3.13 on x86, ARM and macOS, example-config validation, an end-to-end smoke test, a real-browser render of every dashboard, dependency audit, wheel build, a weekly upstream-liveness check, a container build that must serve the dashboard, and a Debian package that must install into a trixie container and serve from /usr/bin. |
| CodeQL | ✅ | Python and JavaScript, weekly and per-PR. |
| Every control clicked in a browser | ✅ | The render check sweeps every button on every panel of every dashboard — 124 controls — and fails on an exception, a panel error, or a control that empties its own panel. A panel added later is swept the day it lands. |
| Accessibility floor | ✅ | Every control has an accessible name, every input a label, and the tab bar is reachable and activatable from the keyboard. Not a full audit; these are the two failures that lock a mouse-free operator out entirely. |
| Dependabot | ✅ | Actions and pip, weekly. |
| Tests cannot reach the network | ✅ | Enforced by a conftest guard, not convention. |
| `make check` reproduces CI locally | ✅ | |
| Docker image | ✅ | Built and exercised in CI: the container must serve the dashboard before anything merges. |
| Distro packages | ✅ | A Debian `.deb`: distro dependencies, a hardened systemd unit, a conffile, and a service account. Built by `packaging/debian/build.sh`, installed and served in CI on trixie, and installed by hand on Debian 13, Kali and Parrot before 1.0 — first install enables and starts, an upgrade leaves a deliberately stopped service alone |

## Sources

**Polled** (13 kinds): `swpc`, `hamqsl`, `rss`, `pota`, `sota`, `ics`, `aurora`,
`noaa_scales`, `swpc_alerts`, `nws_alerts`, `tle`, `pskreporter`, `wspr`.
**Stream** (6): `dxcluster`, `rbn`, `wsjtx`, `rigctl`, `gpsd`, `nmea`.
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
| RBN | ✅ | Its own line parser, aggregated by band and mode. Bounded so a busy night cannot grow memory without limit |
| PSK Reporter | ✅ | Reception reports of *you*, polled from the retrieval API. Your callsign is the query and the config says so |
| WSPR (wspr.live) | ✅ | Who decoded your beacon, with SNR, power and distance. Same honesty note as PSK Reporter |
| Satellite passes | ✅ | Cached TLEs, SGP4 when the optional extra is installed, look angles and Doppler. Passes found by bisection, not by scanning |
| WWFF / WWBOTA | ❌ | Same shape as POTA/SOTA |
| Repeater directory | ❌ | RepeaterBook has a public API |
| GPS (gpsd / NMEA) | ✅ | Auto grid square and a clock check when portable. Published at Maidenhead precision, never a raw fix — see [GPS.md](GPS.md) |

## Panels

30 panels, 7 dashboards: **Home**, **Map**, **Space Weather**, **Operating**,
**Toolbox**, **Activity**, **Field & Weather**. Regroup them by editing
`web/panels/index.json`.

Ten are **tier 0** — they work with the internet unplugged: `bandplan`,
`beacons`, `callsign`, `clock`, `cw`, `exam`, `gps`, `logbook`, `reference`,
`tools`. Nineteen are tier 1. One is tier 2 (`imagery`).

| Feature | Status | Notes |
|---|---|---|
| Rotatable globe with greyline | ✅ | Orthographic projection on 2D canvas. No WebGL, no library. A 2D equirectangular mode shares the same projection dispatch |
| DXCC and WAS progress | ✅ | Log stats reads "147 of 340" with the active prefix table as the denominator, and WAS n/50 with confirmed count and the missing states named once ≤12 remain. STATE indexing rides on the log, not the prefix lookup; VE provinces do not count |
| Watch notifications | ✅ | A watch list in the spots panel; a system notification when a watched call is spotted (cluster, WSJT-X, POTA/SOTA) or the propagation indicator flips a band open. Browser-local, permission asked behind a click, checks only what the visible dashboard already fetches. Needs https or localhost, same as geolocation, and says so |
| Kiosk rotation | ✅ | "rotate" in the tab bar cycles dashboards (45s default, `hh.rotate.seconds` in localStorage to change); any touch pauses it for one interval. For the wall display |
| Browser-side callsign | ✅ | Click the header to set the callsign shown on that display; offered outright when config has none. Presentation only — what the collector sends stays config.toml, because there is no write endpoint |
| Toolbox dashboard | ✅ | The interactive tools on their own tab, above the fold — they were two screens deep on Operating |
| Path plotter with distance and bearings | ✅ | Grid square typed or clicked on the map; km and miles, short and long path, from the configured grid or a browser GPS fix. Selected spots answer "how far was that" the same way |
| Band globes | ✅ | One small sphere per band with activity, greyline on each, drawn from your own cluster spots and WSJT-X decodes. Appear and disappear with the bands — a fixed six would show dead spheres at 3 AM and hide a 6 m opening at noon |
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
| Custom layout per display | ✅ | Customize mode: reorder, hide, restore, reset — per browser, so the TV and the phone each keep their own. Dragging specifically is not built; buttons work everywhere dragging does not |
| "AT YOUR QTH" vs "OPEN ELSEWHERE" band pills | ❌ | Spotted in hamdash; outstanding |
| CW / Morse tools | ✅ | Reference charts, translator, timing, audio playback — see [CW.md](CW.md) |
| CW trainer | ✅ | Four drills: Koch lessons, callsign copy from real DXCC prefixes, a two-sided QSO simulator (contest and ragchew), and a phonetics/Q-signal/abbreviation quiz. Generated in the browser from a seeded PRNG the Python side mirrors, so a test proves the two never diverge. |
| Shack tools | ✅ | Antenna cut chart (dipole, vertical, EFHW, 5/8, loop), feedline loss for ten cable types, what an SWR reading costs through a given line, and distance/bearing between any two grid squares — see [TOOLS.md](TOOLS.md) |
| Licence exam practice | ✅ | Study mode and full practice exams from the official pools for all three US elements, which ship with the project. Built the way a real exam is — one question from each group. Expiry is checked, and a test fails when a shipped pool runs out — see [EXAM.md](EXAM.md) |
| Part 97 beside the answer | ✅ | 47 CFR Part 97 ships too, so a rules question shows the section it comes from, in full, as the FCC published it. 192 questions cite one. Nothing is paraphrased |
| Satellite passes | ✅ | Amateur TLEs fetched daily; passes, look angles and Doppler computed here from cached elements, so the panel survives a WAN outage for days. Needs the optional `sgp4` extra — see [SATELLITES.md](SATELLITES.md) |
| Reverse Beacon Network | ✅ | Who is hearing your callsign, with SNR and speed, plus a rolling per-band tally of everything else. Several thousand spots a minute collapse into a table bounded by the band plan — see [RBN.md](RBN.md) |
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
| Query endpoint (`/lookup/<callsign>`) | ✅ | Off by default. Local index only — no code path from the route to a socket, so a request still cannot cause a fetch. Rate limited, strictly validated, 404 when off. See [CALLSIGN-LOOKUP.md](CALLSIGN-LOOKUP.md) |

## Propagation

| Feature | Status | Notes |
|---|---|---|
| Band conditions | ✅ | From HamQSL |
| MUF / LUF / D-layer absorption | ✅ | Computed locally from SFI, K and solar zenith at your station. Tier 1 (its inputs are fetched); the arithmetic never leaves the machine. |
| Solar terminator / greyline | ✅ | Computed offline from the solar subpoint |
| MUF predictor | ✅ | Derived from SFI, K and the sun's height over *your* station. An indicator, not a prediction — see [PROPAGATION.md](PROPAGATION.md) |
| D-layer absorption | ✅ | Real solar zenith at your grid square, not a UTC-hour proxy |
| Point-to-point MUF chart (MINIMUF 3.5) | ✅ | Pick a target grid, get the 24-hour band-by-band opening chart, computed in the browser. The honest substitute: F2 only, RMS ≈ 3.8 MHz, and the panel says so |
| VOACAP point-to-point | ❌ | Still the genuinely hard one: reliability, signal level, antennas, power. MINIMUF answers "when does the band open"; VOACAP answers "how well will this circuit work". Bundling the public-domain ITSHFBC binaries remains the only honest route to the second question |
| FT8 propagation globes | ✅ | One sphere per active band, lit by cluster spots, WSJT-X decodes, and PSK Reporter / WSPR reception reports |

## Weather

| Feature | Status | Notes |
|---|---|---|
| US alerts (`api.weather.gov`) | ✅ | Tier 1, so it survives the WAN dropping |
| Radar, satellite, lightning imagery | ✅ | Tier 2 tiles |
| Solar imagery (SDO) | ✅ | A tile like any other |
| EU alerts (MeteoAlarm) | 🟡 | Atom feeds and their map work; structured CAP severity needs a `meteoalarm` source |
| Met Office warnings | 🟡 | Warning map as a tile; no structured feed parsed |
| Field weather conditions | ❌ | Needs the `/points` → gridpoint chain done properly rather than letting a source build URLs from a response |
| Opaque image mode | ✅ | `mode = "opaque"` per tile: collector-fetched on `refresh`, raster-only by magic bytes (SVG refused by name), 10 MB streaming cap, served same-origin — the host leaves the CSP. See [IMAGERY.md](IMAGERY.md) |

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
| Prometheus endpoint | ✅ | `/metrics` on the dashboard's own port, off by default. A *read* path — Prometheus pulls, so nothing originates a connection and the egress allowlist is untouched. Nothing is labelled by callsign; see [METRICS.md](METRICS.md) |
| InfluxDB push | ❌ | The remaining half, and the one that really would be the first outbound *write* the collector makes. Same opt-in category as the logbook when it lands. |
| Grafana dashboard | ❌ | After the exporter |
| VA3HDL `config.js` importer | ❌ | |

## Deployment

| Feature | Status | Notes |
|---|---|---|
| Loopback by default | ✅ | Binding wider is a deliberate act that prints a warning every time |
| systemd unit | ✅ | Documented in [INSTALL.md](INSTALL.md) |
| Kiosk / wall display notes | ✅ | |
| Docker image | ✅ | Built and served in CI before anything merges — see the CI row above. |
| `pip install` alone | ✅ | The wheel carries `web/` and the question pools; with no checkout the server falls back to the packaged copy. CI installs the bare wheel and curls the dashboard. |
| Hosted / multi-user mode | ⛔ | Not until there is a real authn/authz model, TLS, rate limiting and a threat model this version deliberately does not have. Reach it over ZTNA or a VPN instead — see [SECURITY.md](SECURITY.md). |

---

## Roadmap order

1.0 shipped, which empties this list. What went into it, in the order it was
done: the live endpoint check (`hamhill check --fetch`, run against every
configured upstream on real hardware), release machinery with a tag that
refuses to disagree with the tree behind it, and the **Debian package** — the
last thing this section listed.

What comes after 1.0 is not decided. The candidate list below is the pool,
and an operator running it on real hardware and reporting what breaks is
worth more to 1.1 than any of it.

**Decided 2026-08-29: 1.0 is US-first.** International band plans and exam
pools come off the roadmap and into the contributions column: the US plan,
the three US pools and Part 97 already ship and are the default, the loaders
are generic, and a maintainer transcribing another regulator's allocations
he does not operate under is how a wrong band edge ships with a straight
face. A contributor who transmits under IARU Region 1 or RAC rules is the
right author for that JSON file, and `tests/test_bandplan.py` will hold the
schema for them either way.

The honest VOACAP substitute shipped as MINIMUF 3.5 (the DX Path panel);
VOACAP itself — reliability and signal level, not just the MUF — stays in
the candidate list below until someone bundles ITSHFBC.

Everything the roadmap has ever listed — the query endpoint, packaging in all
three forms, opaque image mode, Part 97 beside the exam answers, RBN,
satellites, the Prometheus exporter, distro packages — has shipped; the tables
above are the record of what each actually does.

Smaller items are listed in [PARITY.md](PARITY.md).

## Candidate features

The stated goal is for this to cover most of what an operator needs in one
place. These are the gaps between here and that, grouped by what they would
actually change. Nothing here is committed — they are written down so the
argument for each can be had before the code is.

The ones marked **strong fit** need no new architecture: an existing source
shape, a tier 0 computation, or the log we already read.

One came out of the 1.0 soak rather than a wish list. Running the packaged
service against real upstreams from three machines at once, SWPC answered 200
with a body that ended in trailing bytes after a complete JSON document, and
`services.swpc.noaa.gov` and `celestrak.org` both returned transient errors
under that load. The collector did exactly what it promises — logged the
reason, kept the last good snapshot, carried on, and recovered on the next
cycle — so this is not a defect. But a single transient failure currently
leaves a panel flagged as failing for up to a whole interval, and **one
bounded retry before giving up on a cycle** would shorten that. It is a
candidate rather than a fix because a retry also doubles the load a
misbehaving upstream sees, and that argument should be had before the code
is written.

### Operating, day to day

| Idea | Fit | Notes |
|---|---|---|
| **Contest logging mode** | strong | The logbook already writes ADIF. A contest needs a serial number, a duplicate check against this contest only, and a rate meter. That is three fields and a filter over data already in memory. |
| **Rate meter and session stats** | strong | QSOs per hour, best hour, band and mode breakdown for the current session. Pure computation over the log. |
| **Dupe check while logging** | strong | The needed-slot index already answers a harder question. Same lookup, different predicate. |
| **Split / VFO awareness** | medium | `rigctld` reports it; the rig panel does not show it. Small, and the sort of thing that costs a contact when it is wrong. |
| **Antenna rotator control** | medium | `rotctld` is the sibling of `rigctld`, same protocol shape, and the bearing is already computed for every spot. This would be the project's **first outbound command to hardware**, which is a genuine change in posture and needs its own opt-in and its own document. |
| **Memory channels / frequency list** | strong | A tier 0 table of your own frequencies with click-to-tune via rigctld. |

### Reference, all tier 0

| Idea | Fit | Notes |
|---|---|---|
| **Head-copy drills: words and numbers** | strong | The trainer sends characters and callsigns. Copying *whole words* without writing is the skill that gets you past 20 WPM, and it needs a word list and nothing else. |
| **Send practice via a straight-key input** | medium | Copy the space bar or a serial/GPIO key, decode the timing, and score it against what was asked for. Everything to decode it exists; capturing key-down timing accurately in a browser is the hard part. |
| **Contest exchange drills at speed** | strong | The QSO simulator has the scripts; a pile-up mode that sends several stations at once, at settable speed, is the thing contest operators actually practise. |
| **Farnsworth ramp / speed ladder** | strong | Hold character speed, close the gaps as you improve. The timing model already separates the two, so this is a UI and a stored setting. |
| **Smith chart** | medium | The one antenna tool the shack-tools panel does not have, and the only one that is real interactive drawing rather than arithmetic. |
| **NanoVNA / analyser sweep input** | medium | A sweep read off a VNA would make the SWR tab far more useful than a typed number. Needs a serial or USB path into the collector, which is a posture change like `rigctld` was. |
| **Coax length by measurement** | strong | Velocity factor and a known resonant frequency give cable length from a VNA null; the arithmetic is already here. |

| **Exam pools for other countries** | medium | The parser is written for the NCVEC layout. Another syllabus is a data contribution and probably a second parser. |
| **Repeater directory** | medium | RepeaterBook has a public API. Tier 1, one source, but the useful version is filtered by *your* location, which GPS now gives us. |
| **Band plan by region** | strong | The loader is generic; this is data. IARU Region 1 and 3 files would cover most of the world. |

### Signals and propagation

| Idea | Fit | Notes |
|---|---|---|
| **Grayline DX prediction** | strong | We compute the terminator already; the useful version is "which entities are on the greyline with me right now", which is the terminator crossed with the prefix table. |
| **VOACAP point-to-point** | hard | MINIMUF now answers the when-does-it-open half in the DX Path panel. What VOACAP would add is reliability and signal level per circuit; that still means bundling the public-domain ITSHFBC binaries and shelling out. |
| **Sporadic-E and aurora alerting** | medium | We have the aurora oval and the band data. "Tell me when 6m opens" is a threshold and a notification, and notification is a whole capability this project does not have yet. |

### Station and shack

| Idea | Fit | Notes |
|---|---|---|
| **SWR / power meter ingest** | medium | Many meters speak serial. Same shape as the NMEA reader, and the same question about which protocol. |
| **Station equipment inventory** | strong | Tier 0. What you own, serial numbers, purchase dates — the thing everyone keeps in a spreadsheet and cannot find after a theft or a fire. |
| **Maintenance log** | strong | Antenna inspections, coax replacement, tower climbs. Dates and notes, same shape as the logbook. |
| **Power budget for portable** | strong | Battery capacity against transmit duty cycle. Arithmetic, and genuinely useful at a POTA site. |

### Integration and export

| Idea | Fit | Notes |
|---|---|---|
| **Metrics exporter** | committed | Already on the roadmap. Prometheus or InfluxDB, the first outbound *write* the collector makes. |
| **LoTW / eQSL / Club Log upload** | medium | Real value, and each is an account plus credentials plus an outbound write. Belongs in the same opt-in category as the logbook and needs the same care. |
| **QSL card queue** | strong | Which contacts want a card, printed or not. Tier 0, over the log. |
| **Import from N1MM, Log4OM, WSJT-X logs** | strong | We already parse ADIF. Mostly a question of which dialects to accept. |

### Deliberately not planned

| Idea | Why |
|---|---|
| **Built-in SDR receiver** | WebUSB needs a secure context, forcing TLS onto a LAN appliance for one panel. Point a tier 2 panel at your own OpenWebRX+ or KiwiSDR. |
| **Digital mode decoding in the browser** | WSJT-X and fldigi do this properly and are already on the operator's machine. We read their output instead. |
| **A hosted multi-user version** | Not until there is a real authn/authz model, TLS, rate limiting, and a threat model this version deliberately does not have. |
| **Becoming a logging program** | The logbook is deliberately not Log4OM. Contest mode is the boundary; award tracking and QSL management beyond a queue are not. |

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

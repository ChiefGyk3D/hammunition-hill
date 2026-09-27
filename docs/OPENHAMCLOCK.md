# Parity with OpenHamClock

Walked panel by panel against [OpenHamClock](https://github.com/accius/openhamclock)'s
own registry rather than against its README — `src/panelDefs.js` lists 68
built-in panels, and that list is the honest surface to compare against.
OpenHamClock is the community successor to Elwood Downey WB0OEW's HamClock,
MIT-licensed, React and Express, ~40 contributors.

This page answers *what does OpenHamClock do that we do not, and what do we do
that it does not*. [STATUS.md](STATUS.md) answers *what can I use today* and is
the page kept current where the two overlap. [PARITY.md](PARITY.md) does the
same job against hamdash.com, which is a different kind of product again.

**Read the trade-off first.** It decides most of the rows below, and a row that
looks like a gap is often a decision.

---

## Where we deliberately differ

OpenHamClock and Hammunition Hill are both "a ham radio dashboard", and they are
built on opposite answers to one question: *may the dashboard reach out?*

|  | OpenHamClock | Hammunition Hill |
|---|---|---|
| Primary deployment | hosted at openhamclock.com; self-hosting is supported | self-hosted only; there is no hosted version and there will not be |
| Backend | Express API proxy — the browser asks it, it fetches upstream | a collector on a fixed schedule; the server only reads bytes off disk |
| Can a page load cause an outbound fetch? | yes, that is the design (cached server-side) | **no** — architectural invariant 1, and there is no code path from the HTTP server into the collector |
| Egress | whatever a service module asks for | a closed allowlist, every resolved address checked, URLs come from `config.toml` and never from a response |
| Third-party hosts in the browser | Leaflet basemaps, tile servers, NASA, adsb.lol, 3D models | tier 2, opt-in, one config line each, and the CSP is generated from that list |
| Companion services | 7 (rig bridge, cluster node, DX Spider proxy, P.533 service, WASM build, WSJT-X relay, TLE proxy) | none; one process |
| Node modules | ~1 000 through npm | zero — the browser gets hand-written ES modules and a 60 KB coastline |
| Works with the WAN unplugged | PWA cache of what it last saw | 13 panels compute from scratch; everything else keeps its last good snapshot with the failure reason attached |
| Licence | MIT | MPL-2.0 |

Neither answer is wrong. OpenHamClock's is the better one for "I want a rich
dashboard on any device, now, without installing anything" — and it is *much*
richer. Ours is the better one for "I want a box on my own network that keeps
telling the truth when the internet is gone, and that never talks to anyone I
did not name."

That difference is why some rows below say **not planned** with a reason rather
than **planned**. A feature that requires the browser to fetch from a third
party, or the server to fetch on request, is not a small piece of work here —
it is a different product.

Legend: **done** · **partial** · **planned** · **not planned** (with the reason)

---

## Map

OpenHamClock's map is its centrepiece: Leaflet, a dozen basemaps, three
projections and around 28 toggleable overlays.

| Feature | Status | Notes |
|---|---|---|
| Azimuthal equidistant projection | **done** | Added for this comparison. Centred on your station, every bearing is a straight line out of the middle and distance along it is linear to the antipode on the rim — which is the projection's entire reason for existing on a ham radio map. `tests/test_globe_projection.py` asserts exactly that against `geo.py`'s bearings and distances, because a projection that is subtly wrong still draws a convincing coastline |
| 3D globe | **done** | Orthographic on a 2D canvas, no WebGL and no library. Theirs is a real 3D scene with satellite models; ours is an instrument, and it runs on a Pi Zero |
| Flat / Mercator | **partial** | Equirectangular, not Mercator. Same dispatch point as the other two |
| Basemap styles | **not planned** | A basemap is somebody else's tile server in your browser on every pan. The vector coastline ships with the dashboard and costs nothing |
| Greyline / terminator | **done** | Computed from the clock in all three projections. The azimuthal and flat terminators are both solved analytically rather than traced — see the comments in `web/lib/globe.js` |
| Aurora overlay | **done** | SWPC OVATION, reduced to an oval boundary plus cells before publishing |
| Satellites on the map | **partial** | We have passes, look angles and Doppler in their own panel; they are not drawn on the globe |
| DX spots with great-circle arcs | **done** | Coloured by band, and by what you still need from your own log |
| RBN / WSPR / PSK overlays | **partial** | All three are panels here; the band globes visualise them spatially, but they are not map layers |
| Maidenhead grid overlay | **planned** | Tier 0, and the graticule machinery is already there |
| CQ / ITU zone overlays | **planned** | Tier 0 given the boundary data; the prefix table already carries the zone numbers |
| MUF map / D-RAP overlay | **planned** | We compute MUF at a point and along a path; a world grid of it is the same function over a mesh |
| Lightning overlay | **done** | Any lightning map is one `[[imagery]]` line |
| Aircraft (ADS-B) | **not planned** | A third-party feed of other people's movements, polled continuously. Point a tier 2 panel at your own receiver if you run one |
| Click to tune | **not planned** — see [Rig control](#rig-control-and-hardware) | |
| Click to listen (KiwiSDR) | **partial** | A tier 2 panel pointed at your own receiver does this; there is no directory lookup, because the lookup is the outbound part |

## Propagation

The one place OpenHamClock is straightforwardly ahead, and says so honestly.

| Feature | Status | Notes |
|---|---|---|
| ITU-R P.533-14 predictions | **not written** | Theirs runs the real recommendation in WebAssembly, and it is the right answer. Ours is MINIMUF 3.5 — F2 only, RMS ≈ 3.8 MHz, and the panel says so on its face |
| Point-to-point chart | **done** | The DX Path panel: pick a grid, get a 24-hour band-by-band opening chart computed in the browser. It answers *when does the band open*; P.533 also answers *how well will the circuit work* |
| Reliability / signal level | **not written** | The genuinely hard half. Bundling the public-domain ITSHFBC binaries remains the only honest route — see [PROPAGATION.md](PROPAGATION.md) |
| World heatmap / MUF map | **planned** | Same model, evaluated over a grid |
| Band conditions | **done** | From HamQSL, same source as theirs |
| MUF / LUF / D-layer absorption | **done** | Computed locally from SFI, K and the real solar zenith at *your* grid square |
| Ionosonde-corrected real-time data | **planned** | KC2G/GIRO is a single URL and fits the source model exactly. This is the strongest unclaimed row on the page |
| IBP beacons | **done** | Computed offline from the 180-second cycle, with bearing and distance to each |
| Sked planner | **partial** | The DX Path chart answers the same question for one path; a two-station "when are we both in the window" view is not built |
| Prediction check (predicted vs actual) | **planned** | Clever, and we have both halves already: the MUF model and the RBN/PSK reports of your own signal |

## Space weather and astronomy

| Feature | Status | Notes |
|---|---|---|
| SFI / Kp / SSN with history | **partial** | Current values as dials with the number alongside; no history charts |
| GOES X-ray flux | **done** | Dial, with the R-scale in the label |
| NOAA SWPC alerts | **done** | Watches, warnings and summaries as issued |
| Aurora forecast | **done** | |
| Solar imagery | **done** | SDO as an `[[imagery]]` tile, or collector-fetched in opaque mode |
| Solar cycle chart | **planned** | SSN history; a chart rather than a dial |
| Space weather trends | **planned** | Same shape as the above |
| Lunar phase | **done** | Added for this comparison, in the Sun & Moon panel |
| Sun and moon rise/set | **done** | Added for this comparison. Sunrise, sunset, transit and the civil-twilight greyline window; moonrise, moonset, phase, illumination, distance, and live look angles with how much of the EME window is left. Tier 0 — computed from the clock and your grid, drift-tested against the Python twin |
| Meteor showers | **done** | Added for this comparison, and done differently: theirs is a calendar, ours computes the radiant's azimuth and elevation in *your* sky now, which is what decides whether meteor scatter is worth trying. The panel is explicit that ZHR is a visual rate and not what you will hear |
| NOAA R/S/G scales | **done** | From NOAA's own product, alongside our dials |

## Spots, activations and digital modes

| Feature | Status | Notes |
|---|---|---|
| DX cluster spots | **done** | Straight telnet to a cluster you name. Theirs aggregates through their own node, which is better coverage and one more party in the path |
| Worked-before / dupe badges | **done** | From your ADIF on disk, which a hosted dashboard cannot read |
| Band / mode / zone filtering | **done** | Client-side |
| Watchlist and alerts | **done** | Plus a notification when the propagation indicator flips a band open |
| POTA | **done** | |
| SOTA | **done** | |
| WWFF | **planned** | Same source shape as POTA/SOTA; a source class and a config block |
| WWBOTA | **planned** | As above |
| CANParks / regional programmes | **planned** | As above |
| DXpeditions (NG3K) | **planned** | Reads as a feed |
| DX news | **done** | Any RSS/Atom feed through the `rss` source, parsed here and stripped to text |
| Contest calendar | **done** | Generic iCalendar, so any calendar works |
| PSK Reporter | **done** | Reception reports *of you*. Theirs also streams third-party traffic over MQTT; deliberately not here |
| RBN | **done** | Own line parser, bounded per-band tally — see [RBN.md](RBN.md) |
| WSPR | **done** | Who decoded your beacon, with SNR, power and distance |
| WSJT-X / JTDX decodes | **done** | Over UDP, your own decodes, live |
| JS8Call / MSHV control | **not planned** | Outbound control of other software; see below |
| N1MM+ / DXLog live QSOs | **planned** | Another UDP listener, same shape as the WSJT-X one |

## Logging and awards

| Feature | Status | Notes |
|---|---|---|
| Logbook | **done** | Multiple books, plain ADIF, append-only, off by default — see [LOGBOOK.md](LOGBOOK.md). Theirs is IndexedDB in the browser; ours is a file on your disk that other software can read |
| ADIF import / export | **done** | The logbook writes plain ADIF; it is the same file |
| Log from a spot | **partial** | The logbook and the spot list are both there; one-click prefill is not wired |
| Log statistics | **done** | |
| DXCC / WAS progress | **done** | "147 of 340" with a real denominator, WAS n/50 with the missing states named |
| Awards panel (WAZ, VUCC, IOTA…) | **planned** | The log is already indexed by entity, band, mode and state; each award is a predicate over it |
| LoTW / eQSL / Club Log upload | **planned** | Real value, and each is an account plus credentials plus the first outbound *write*. Same opt-in category as the logbook |
| Contest logging mode | **planned** | Serial number, per-contest dupe check, rate meter — see the candidate list in [STATUS.md](STATUS.md) |

## Rig control and hardware

| Feature | Status | Notes |
|---|---|---|
| Read frequency and mode | **done** | `rigctld`, live, scoping what you see to the band you are on |
| Set frequency (click to tune) | **not planned yet, and not for the usual reason** | Reading a rig and commanding one are different postures. Today nothing this project does sends a command to hardware; the first one needs its own opt-in and its own document, and the argument should be had before the code is. It is in the candidate list, not the deliberately-excluded list |
| Rotator control | **planned** | `rotctld` is the sibling of `rigctld` and the bearings are already computed. Same posture change as above |
| Rig Bridge (20+ radio plugins) | **not planned** | `rigctld` and `flrig` already speak to those radios and are already installed on the operator's machine. Re-implementing their plugin layer is work someone else has done better |
| Frequency memories | **done** | Added for this comparison, and checked against the band plan for your licence class — a memory is a frequency you are about to key up on, and a list that silently contains one you may not transmit on is worse than no list |
| Winlink gateways | **not planned** | Needs their API key server-side |
| APRS | **planned** | Read-only APRS-IS is a plain stream and fits the model. The RF side via a local TNC fits it even better and is genuinely tier 0 |
| Meshtastic / MeshCom | **planned** | A local MQTT broker or a serial node is the same shape as the GPS reader |

## Reference and training — where we are ahead

Nothing in this section exists in OpenHamClock. All of it is tier 0.

| Feature | Notes |
|---|---|
| **Licence exam practice** | All three US NCVEC pools ship with the project. Five study modes, and exams built the way a real one is — one question from each group. Expiry is checked, and a test fails when a pool runs out — see [EXAM.md](EXAM.md) |
| **47 CFR Part 97, quoted** | The regulation ships too, so a rules question shows the section it comes from, in full, as the FCC published it. 192 questions cite one. Nothing is paraphrased |
| **CW and Morse tools** | Reference charts, translator, timing, audio playback — see [CW.md](CW.md) |
| **CW trainer** | Koch lessons, callsign copy from real DXCC prefixes, a two-sided QSO simulator, a phonetics/Q-signal quiz. Generated from a seeded PRNG the Python side mirrors, so a test proves the two never diverge |
| **Shack tools** | Antenna cut chart, feedline loss for ten cable types, what an SWR reading costs through a given line, Ohm's law, dB, voltage drop, battery runtime, grid-to-grid paths — see [TOOLS.md](TOOLS.md) |
| **Band plan by licence class** | Including grandfathered Novice and Advanced. OpenHamClock draws a band plan bar on the rig display; it does not tell you what *you* may use |
| **Pocket reference** | Q signals, RST, phonetics, number codes, calling frequencies — see [REFERENCE.md](REFERENCE.md) |
| **Offline FCC ULS index** | US callsigns resolved from a local SQLite index with no per-lookup network at all |
| **GPS auto-grid** | gpsd or raw NMEA, published at Maidenhead precision and never as a raw fix — see [GPS.md](GPS.md) |

## Architecture and operations — where we are ahead

| Feature | Notes |
|---|---|
| **No request causes a fetch** | Not a policy, a shape. There is no code path from the HTTP server into the collector, so nothing an attacker sends can steer an outbound request |
| **Closed egress allowlist** | Every resolved address checked, not just the first. Private, loopback and reserved addresses refused unless a source opts in |
| **Sources never construct URLs** | The full URL including query string lives in `config.toml`. A source that assembled a query from a response would turn an architectural property into a per-source audit |
| **Tiers, declared and shown** | Every panel says whether it reaches outside the house, and a test enforces that a tier 0 panel declares no external hosts |
| **CSP derived from config** | Never hand-maintained, so it cannot drift from what is enabled |
| **Degrade honestly** | Last good snapshot kept with `fetched_at` and the failure reason. A stale panel and a blank panel look different, which is the whole point with the WAN down |
| **No `innerHTML`, no `eval`, no hardcoded external URLs** | Enforced by `tests/test_frontend.py` |
| **Tests cannot reach the network** | A conftest guard blocks every socket to anything but loopback |
| **The docs are tested** | Panel counts, source counts, tier lists, module lists and cross-page contradictions all fail a test when they drift |
| **Every control clicked in a browser** | CI sweeps every button on every panel of every dashboard and fails on an exception, a panel error, or a control that empties its own panel |
| **Debian package** | A `.deb` with a hardened systemd unit and a service account, installed into a container in CI before anything merges |

## Presentation

| Feature | Status | Notes |
|---|---|---|
| Custom layout per display | **done** | Reorder, hide, restore, reset — kept per browser, so the shack TV and the field phone each keep their own |
| Dockable drag-anywhere layout | **not planned** | Buttons rather than drag, deliberately: they work on a TV remote d-pad and a touchscreen alike |
| Named layout presets / profiles | **planned** | The per-browser layout store would take a name |
| Kiosk rotation | **done** | And theirs does not have it — "rotate" cycles dashboards on a wall display, pausing on any touch |
| Themes | **partial** | One theme, validated for colour-blind separation. A custom theme editor is not planned; the ramp carries meaning and an operator recolouring it silently breaks that |
| Multiple languages | **not written** | Theirs has 16. Ours has none, and that is a real gap, not a decision |
| PWA / offline mode | **partial** | The dashboard is already local; a service worker would let a phone keep the last view after leaving the LAN |
| Command palette / keyboard shortcuts | **planned** | The accessibility floor already requires every control to be keyboard-reachable |
| EmComm layout (ARES/RACES, FEMA, nets) | **partial** | NWS alerts are in and are tier 1, so they survive the WAN dropping. FEMA shelters and disaster declarations are two more sources of the same shape; the net roster and messaging are a different product |
| Plugin system | **not planned** | Panels are already the extension point: a directory with two files, no build step, no registry |

---

## What this comparison changed

Shipped in the same change as this page, all tier 0:

1. **Azimuthal equidistant projection** — the HamClock signature view, and the
   projection a beam operator actually wants. `AZ` in the map's view row.
2. **Sun & Moon panel** — sunrise, sunset, transit, the civil-twilight greyline
   window, moonrise, moonset, phase, illumination, distance, live look angles
   and how much of the EME window is left.
3. **Meteor Showers panel** — which showers are running, when they peak, and
   where each radiant is in your sky right now.
4. **Frequencies panel** — memory channels, checked against the band plan for
   your licence class.

The new astronomy lives in `src/hammunition_hill/ephemeris.py` and
`web/lib/ephemeris.js`, pinned to each other by
`tests/test_ephemeris_drift.py` and to published values by
`tests/test_ephemeris.py`.

## Next, in order of value per unit of work

Everything here is **planned** above, and grouped by what it would actually
cost.

**No new architecture — an existing source shape or a tier 0 computation:**

1. **Ionosondes (KC2G/GIRO).** One URL, one source class. Real measured foF2
   and MUF beats any model we can compute, and it closes the "ionospheric map"
   row that has been open on [STATUS.md](STATUS.md) since the beginning.
2. **WWFF and WWBOTA.** Same shape as POTA and SOTA, which are already built.
3. **Maidenhead grid and CQ/ITU zone map overlays.** Tier 0, and the graticule
   already knows how to draw a mesh on all three projections.
4. **Awards beyond DXCC and WAS.** The log index already answers harder
   questions than WAZ and VUCC ask of it.
5. **Space weather history charts.** SWPC publishes the series; we already
   fetch the current value from it.

**Needs a decision before it needs code:**

6. **Rotator control**, then **click to tune.** Both are the project's first
   outbound command to hardware. That is a genuine change in posture and wants
   its own opt-in and its own document — see the candidate list in
   [STATUS.md](STATUS.md).
7. **APRS.** Read-only APRS-IS is one more stream; the local-TNC path is
   better still and is tier 0.

**Real work, no way around it:**

8. **VOACAP / P.533.** Still the honest hard one. OpenHamClock compiled the
   ITU's own implementation to WebAssembly, which is the right answer and a
   large piece of work.
9. **Translations.** Sixteen languages is sixteen communities; we have none.

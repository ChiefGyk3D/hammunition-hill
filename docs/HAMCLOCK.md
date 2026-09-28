# Parity with HamClock

How this compares to HamClock, feature by feature, against HamClock's own 4.24
user guide and the release notes of the open continuation. Written 2026-09-13;
every upstream endpoint named here was fetched that day, and the one prediction
engine that mattered was run, not read about.

[PARITY.md](PARITY.md) asks the same question of hamdash.com. This page exists
because the field target is different: hamdash is a browser tab, HamClock is
the appliance on the shack wall and in the go-box, and "MUF" means something
specific there. [STATUS.md](STATUS.md) stays the page kept current where the
two overlap.

## What HamClock is in 2026

Two facts change the shape of this comparison.

**The client is open now.** Clear Sky Institute's final release was 4.22; the
code continues at [openhamclock/hamclock](https://github.com/openhamclock/hamclock)
under the MIT licence, with a written client-to-backend standard alongside it.
MIT is compatible with MPL-2.0, so an algorithm can be ported from it with
attribution where that beats writing it fresh. Nothing has been yet.

**Almost nothing in HamClock is computed on the HamClock.** The VOACAP
reliability table, both MUF maps, the DRAP map, the aurora, cloud and weather
maps, the satellite elements, the spot feeds — all of it comes from a backend
server the client polls. The original backend was one host in Arizona. Its
open replacement, the
[Open HamClock Backend](https://github.com/openhamclock/open-hamclock-backend)
(AGPL-3.0, Python), regenerates every one of those files on a cron schedule and
serves them to any client on the LAN.

That is the fork in the road, and it is worth saying plainly which way this
project goes: **Hammunition Hill is the backend and the frontend in one
process, and it computes on the machine it runs on.** A HamClock-compatible
backend is a different product with a different threat model (it serves
anything that asks, to a client that fetches on its own schedule), and its
code is AGPL, which cannot be copied into this tree. What *can* be borrowed is
the list of public data products it found and the order it found them worth
doing in, and both are used below.

## Where we deliberately differ

| | HamClock | Hammunition Hill |
|---|---|---|
| Form | one fixed 800×480-style screen, kiosk-first, touch | any browser, any size, several dashboards |
| Where the work happens | a backend server, client polls it | this machine, collector to disk to browser |
| Layout | up to four rotating panes plus the map | thirty panels regrouped by editing one JSON file |
| Hardware | Raspberry Pi GPIO, I2C sensors, light sensor, KX3 serial | none; a laptop or a Pi behind a browser |
| Your log | ADIF pane, plots QSOs, watch keywords | drives spot colouring, DXCC/WAS progress, a logbook |
| Your rig | tunes VFO A on a spot click, polls PTT | read-only: frequency and mode only, by design |
| Egress | whatever the backend does | closed allowlist, every address checked |

Neither is wrong. HamClock's single screen is a genuinely good appliance
design and its pane set is the reference this page measures against.

## Status

Legend: **done** · **partial** · **planned** · **not planned** (with the reason)

### The map

| HamClock | Status | Notes |
|---|---|---|
| Mercator, click to set DE/DX, pan, zoom | **done** | The 2D mode; zoom chips, click sets the path plotter's target |
| Azimuthal, two hemispheres centred on DE | **partial** | The globe is orthographic, centred anywhere. Orthographic is not azimuthal-equidistant: bearings from the centre are right, distances along a radius are not. An azimuthal-equidistant projection is one more case in the same dispatch |
| Azim One (whole world, antipode at the rim) | **planned** | Same projection, different clip |
| Robinson | **not planned** | A publishing projection. Nothing an operator reads off it beats the other two |
| Countries / Terrain styles | **partial** | Coastlines ship; there is no terrain raster and shipping one is a size decision |
| Night shading, greyline | **done** | |
| DRAP map style | **planned** | SWPC publishes the whole model as a text grid, 4° cells — see [Propagation](#propagation-the-part-this-page-is-really-about) |
| MUF-RT map style (KC2G real-time ionosondes) | **planned** | The `ionosonde` source ships and the Ionosondes panel reads it; what is left is the map style -- interpolating ~100 stations onto the globe. See [the real-time MUF map](#the-real-time-muf-map) |
| MUF-VCAP map style (VOACAP median MUF from DE) | **planned** | An area run of the same engine as below |
| /REL and /TOA maps per band | **planned** | Same area run; reliability and take-off angle are two columns of one output |
| Aurora map style | **done** | OVATION as a globe layer |
| Weather map (isobars, wind), Clouds | **partial** | Any such image is an `[[imagery]]` tile; nothing draws them onto *our* globe |
| Tropics, Lat/Long overlays | **done** | The graticule |
| Maidenhead field overlay | **planned** | Eighteen by eighteen lines and labels; tier 0 |
| Azimuthal rings and radials from DE | **planned** | Tier 0, and the thing a beam operator actually wants |
| CQ / ITU zone boundaries | **planned** | The prefix table already knows a call's zone; drawing the boundaries needs a boundary file with a licence we can ship |
| Cities on hover | **not planned** | |
| Lightning strikes on the map | **partial** | Lightning as an imagery tile works. HamClock's backend runs a Blitzortung daemon; a live strike layer on our globe is a stream source with a terms-of-use question |
| Sub-earth moon marker, sun marker, DE antipode | **planned** | Sun is trivial from the subsolar point we already have; moon needs the lunar position code below |
| Satellite ground track and footprint rings | **planned** | The passes are computed here already; the track is the same propagator sampled forward |
| NCDXF beacon marks | **planned** | The schedule panel knows the eighteen locations; the map does not draw them yet |
| Info table on hover: grid, LMT, zones, prefix, bearing, weather | **partial** | Selected spots show distance and bearing; there is no hover table |
| RSS ticker over the map | **partial** | A feed panel, not a ticker |

### DE and DX panels

| HamClock | Status | Notes |
|---|---|---|
| Local time and date at DE | **done** | Clock panel |
| Sunrise / sunset at DE, "at" or "in" | **planned** | Not built. `solar.js` has elevation and the terminator but no rise/set solver. Tier 0 and small |
| DX panel: a second location with its own time, rise/set, prefix, SP/LP | **partial** | The path plotter and DX Path panel take a target grid; nothing shows the target's local time or its sunrise |
| Time zone handling for DE and DX | **partial** | The browser's zone for DE; nothing for DX |
| Satellite pass sky plot in the DX panel | **planned** | Passes are listed with times, azimuths and peak elevation; there is no sky dome drawing |
| Up to two satellites tracked at once | **partial** | All passes for every amateur satellite are listed; there is no "track this one" selection |

### Data panes

| HamClock pane | Status | Notes |
|---|---|---|
| DX Cluster, with cluster commands and watch list | **done** | Filtered in the browser; the watch list is callsigns, see below |
| UDP spots from WSJT-X, N1MM, DXLog, Logger32, Log4OM | **partial** | WSJT-X only. N1MM's UDP is XML on a different port; the others vary. Each is a small stream parser |
| On The Air: POTA, SOTA | **done** | |
| On The Air: WWFF | **planned** | `spots.wwff.co/static/spots.json` is live, same shape as POTA. Listed in STATUS.md since 1.0 |
| On The Air: IOTA, GMA, LLOTA (backend additions) | **not planned** | Until an operator asks. Each is a source kind |
| Live Spots: WSPR, PSK Reporter, RBN, of you or by you, by call or grid | **partial** | All three sources exist. "Spots *by* my grid, so I can see propagation from here without transmitting" is not built, and it is the best idea on this page for a portable station that has not keyed up yet |
| VOACAP DE–DX reliability, 24 h × band, power / mode / TOA / SP-LP | **planned** | See below. Measured feasible today |
| Contests (WA7BNM) | **partial** | Generic iCalendar. WA7BNM publishes no aggregate feed we could find; HamClock carries it by permission |
| DXpeditions (NG3K) | **planned** | `ng3k.com/adxo.xml` is a live RSS feed; the generic `rss` source reads it today with no code change. A dedicated parser would put them on the map |
| Solar Flux with 30-day history and 3-day prediction | **partial** | Value and history are in the snapshot; the panel draws a dial, not the series. The 3-day forecast is in SWPC's `3-day-forecast.txt` |
| Sunspot Number with 30-day history | **planned** | Not fetched. SIDC's `EISN_current.txt` is the daily estimate; SWPC's `sunspots.json` is monthly back to 1749. MINIMUF and VOACAP both *take* SSN and we currently derive it from flux |
| Planetary K, 7 days past + 2 days forecast | **partial** | 24 readings of history, no forecast. `noaa-planetary-k-index-forecast.json` is live and carries both |
| X-Ray with 24 h history, GOES | **partial** | Current and today's peak; no series drawn |
| Solar wind, 24 h | **planned** | Not fetched. SWPC `json/rtsw/rtsw_wind_1m.json`; the old `products/solar-wind/*` paths are gone |
| Bz / Bt | **planned** | `json/rtsw/rtsw_mag_1m.json`; the one-line summary is `products/summary/solar-wind-mag-field.json` |
| Disturbance (DST, Kyoto) | **planned** | SWPC mirrors it as `products/kyoto-dst.json`, hourly, so no Kyoto scraping |
| DRAP plot, 24 h | **planned** | Same grid as the map, reduced to its maximum |
| NOAA SpaceWx, now + 3 days | **partial** | Current R/S/G tiles; the 3-day columns are in `3-day-forecast.txt` |
| Aurora | **done** | |
| SDO images, with grayline planner and movie | **partial** | SDO as a tile. No planner |
| Moon: phase, az/el, rise/set, radial velocity, EME planner | **planned** | Nothing lunar exists. A low-precision lunar ephemeris is ~80 lines and tier 0; EME mutual-window is the same bisection the satellite code does |
| DE Wx / DX Wx (OpenWeatherMap) | **planned** | Listed in STATUS.md as "field weather". Open-Meteo answers with no key; api.weather.gov needs the two-step `/points` chain. See the field section |
| ENV sensors (BME280 ×2) | **not planned** | I2C on a Pi header. A field laptop has none; if an operator wires one, it is a local stream source like NMEA |
| Rotator (rotctld) with Auto track of DX or satellite | **planned** | STATUS.md: the first outbound command to hardware; needs its own opt-in and document |
| Countdown, Stopwatch, daily and once-only alarms, Big Clock | **partial** | A clock. No stopwatch, no alarms, no big mode. Tier 0 and cheap; a contest operator wants the countdown |
| ADIF pane: map every QSO, watch by NADXCC / NAPREF / NAGRID / NABAND | **partial** | The log colours spots by what is still needed, which is the same predicate as NADXCC and NABAND applied the other way round. QSOs are not drawn on the map |
| Band activity (counts per band and continent) | **partial** | RBN's per-band tally is this, from one source |
| APRS monitoring | **planned** | New in the open client. APRS-IS is a telnet stream with a login line, the same shape as the cluster client; a local Direwolf KISS/AGW port is the tier 0 version. Both belong here for field work |
| HAB and pico balloon tracking | **not planned** | Until asked; it is a source kind over public tracker APIs |
| HamAlert | **not planned** | An account and a push service |
| Space launches, active nets, tropical storms, fires, fire weather, marine warnings, earthquakes, tropo ducting maps | **not planned** | Backend additions of 2026. Each is one source kind; none is propagation or operating. Marine warnings and fire weather are `nws_alerts` with a different URL filter and work today |

### Time

| HamClock | Status | Notes |
|---|---|---|
| UTC, big, always | **done** | |
| Time travel: show the greyline, a pass or a prediction at another moment | **planned** | Tier 0, pure UI: every drawing function already takes a date. The safety detail HamClock gets right — a red OFF that will not let you forget — is the part to copy |
| gpsd / NMEA time check | **done** | |
| NTP | **not applicable** | The OS does that |

### Control and integration

| HamClock | Status | Notes |
|---|---|---|
| rigctld / flrig: click a spot, tune VFO A | **not planned as-is** | Reading the rig is one posture; writing to it is another. STATUS.md carries "memory channels with click-to-tune" as a candidate; if it lands, spot click-to-tune is the same call |
| PTT poll → ON THE AIR | **planned** | `rigctld` answers `t`; one more read-only query |
| GPIO switches and LEDs, light sensor, on/off dimming | **not planned** | Pi-header hardware; a browser cannot dim a monitor |
| RESTful set_/get_ API for external programs | **partial** | Snapshots are `GET /data/<id>.json`, which covers every `get_`. There is deliberately no `set_` surface: the logbook's write route is the one exception, and adding one is an authn decision — see [SECURITY.md](SECURITY.md) |
| Live web mirror, screen capture | **not applicable** | It is a web page |
| Magnetic bearings (WMM) | **planned** | Everything here is true north. A WMM evaluation is ~150 lines plus a coefficient file NOAA publishes; a compass in a field is magnetic |
| Bio lookup on spot click (QRZ, HamQTH) | **done** | The lookup chain |
| Units: metric / imperial | **partial** | Distances show both; nothing else has units yet |

### Watch lists

HamClock's watch grammar — `20-10M NAGRID`, `VK/ 30M`, `7.0-7.01MHZ` — with
Off / Red / Only / Not modes is better than ours, which is a list of callsigns
plus a "tell me when a band opens" switch. Ours is **partial**. The band and
frequency terms are a parser; the `NA*` terms are the needed-slot index we
already keep, exposed as predicates. Worth doing as a unit, with the grammar
tested against HamClock's own examples so an operator can bring a list across.

## Propagation: the part this page is really about

"Calculate the MUF" means four different things in HamClock, and this project
has one and a half of them.

| What | HamClock | Here | Route |
|---|---|---|---|
| **MUF over your own station**, now | not shown as such (the MUF-RT map covers it) | **done** — the indicator panel | — |
| **Point-to-point MUF by hour** | the VOACAP DE-DX pane, top edge | **done** — MINIMUF 3.5 in the DX Path panel, RMS ≈ 3.8 MHz | — |
| **Point-to-point reliability**, SNR, mode, power, take-off angle | VOACAP DE-DX pane, from the backend | **not built** | `voacapl`, measured below |
| **Global MUF map**, real-time | MUF-RT, from KC2G's ionosonde assimilation | **partial** -- the Ionosondes panel lists the measured stations, nearest first; no map | Interpolate the same feed onto the globe; or the VOACAP area run for the climatological version |
| **D-region absorption**, map and history | DRAP style and DRAP pane | **partial** — our own D-layer estimate at your station | SWPC's DRAP grid, verified |

### VOACAP is packaged. The record needs correcting.

STATUS.md and PROPAGATION.md have said since the DX Path panel landed that
bundling the public-domain ITSHFBC binaries "remains the only honest route" to
a real prediction. That was true of the Windows distribution and is not true
of Debian. Checked 2026-09-13:

```
$ apt-cache policy voacapl
voacapl:
  Installed: 0.7.6-3
```

`voacapl` and `voacapl-data` are in Debian (and therefore Kali, Parrot, Ubuntu
and Raspberry Pi OS), along with `pythonprop`, the GPL-2 GUI whose deck writer
documents the input format. The Debian package installs the ITSHFBC data tree
read-only under `/usr/share/voacapl/itshfbc/` and a `makeitshfbc` script that
copies the writable parts into a home directory.

It was run here, not merely found. A method-30 point-to-point deck for a
10 800 km circuit (FN31 to PM95, September, SSN 80, 100 W, isotropic antennas,
eight bands, 24 hours):

```
$ time voacapl ~/itshfbc hh_test.dat hh_test.out
real    0m0.017s
```

Seventeen milliseconds for the whole table. The output carries, per hour and
per band, the mode (`F2F2`, `EF2`), take-off and arrival angles, delay,
virtual height, MUFday, loss, signal, noise, **SNR**, **REL** (the reliability
HamClock colours its squares by), and the signal and SNR distributions. At
12:00 UTC on that circuit it gives 3.6 MHz a 0.76 reliability and 14.1 MHz
0.71 — plausible for a transpolar path in the evening at DE, and exactly the
row the HamClock pane draws.

What integrating it would mean, honestly:

- **A system dependency, not a bundle.** `Recommends: voacapl` in the Debian
  package; detected at runtime; the panel says "install voacapl" when absent,
  the way the satellite panel says "install the sgp4 extra". The pip and
  Docker paths get the same message or a second engine (below).
- **It is a subprocess, and it can hang.** Given an antenna file that does
  not exist, `voacapl` sat silently for the full two-minute timeout of the
  first attempt here. The wrapper needs a hard timeout, a private copy of the
  run directory under the service's state directory (the systemd unit mounts
  the filesystem read-only), and a test that feeds it a bad deck and asserts
  the timeout fires.
- **It is a derived source.** No network: it reads the station, a target, the
  SSN snapshot and the clock, and writes a snapshot, exactly like the
  propagation and satellite loops in `collector.py`. The target list is the
  one the DX Path panel already takes, and the browser stays a renderer.
- **The area run is the map.** `voacapl <root> AREA CALC <file>` produces the
  grid behind MUF-VCAP, /REL and /TOA. It is slower — seconds, not
  milliseconds — and it is a per-band, per-hour product, so it is generated
  on the collector's schedule for the current hour, not on demand.
- **SSN becomes a first-class input.** VOACAP wants a smoothed sunspot
  number, and today we infer one from flux for MINIMUF. Fetching SIDC's daily
  estimate is a prerequisite and a pane in its own right.

The alternative engine for the paths that cannot apt-install anything is
[dvoacap-python](https://github.com/skyelaird/dvoacap-python) (MIT, pure
Python plus NumPy), a port of VE3NEA's DVOACAP. It claims 86.6 % agreement
with reference VOACAP over eleven test paths and 4 ms per prediction. Both
numbers are the author's, not measured here; NumPy is a dependency this
project does not have and would not take lightly. Second engine, not first.

### The real-time MUF map

KC2G's `api/stations.json` is what HamClock's MUF-RT is built from: about a
hundred ionosondes, each with `fof2`, `mufd` (MUF(3000)), `hmf2`, TEC and a
confidence score, updated as GIRO publishes. The open backend interpolates
them on the sphere with inverse-distance weighting and draws a heat map; that
is ~300 lines and there is nothing hard in it.

**Correcting the record: the gate written here was wrong.** An earlier
revision of this page said, in bold, to write to KC2G before shipping a source
kind that polls his API. That conflated two different things, and since this
page is where the mistake was made, this is where it gets fixed rather than
quietly deleted.

The backend's attribution file states the data is "used by permission from
KC2G" and may not be used commercially. That is a statement about *what the
backend does*: it fetches once and serves the assimilated result to every
HamClock in the world. Redistribution is exactly the case where asking is the
right instinct. This project has no such server and never will -- invariant 1
is that no request causes a fetch. Each install's collector reads the same
public, unauthenticated JSON for the one operator whose machine it runs on,
which is what a browser pointed at prop.kc2g.com does, on a timer.
prop.kc2g.com publishes no terms restricting that, this project is
non-commercial, and a rule that ordinary client reads need written permission
would, applied consistently, gate every source on this dashboard.

So the `ionosonde` source ships, and it is on by default in
`config.example.toml`. What is owed is not permission but courtesy: a 900 s
interval rather than a tight one, and KC2G and GIRO named where an operator
reads the numbers -- the panel's own description, `config.example.toml` and
[CONFIGURATION.md](CONFIGURATION.md#ionosonde--measured-fof2-and-muf-via-kc2g).
His rendered `renders/current/mufd-normal-now.svg` remains available as a
tier 2 `[[imagery]]` tile for operators who would rather see his map than our
table.

### DRAP

`services.swpc.noaa.gov/text/drap_global_frequencies.txt` is the complete
D-Region Absorption Prediction: a header with the X-ray and proton status,
then a 4°-cell grid of "highest frequency attenuated by at least 1 dB" over
the whole globe, refreshed every minute or so. It is public-domain US
Government work, ~40 KB, and needs a fifty-line parser. The map style is a
filled-cell layer on the globe with HamClock's colour ramp (grey through the
spectrum); the pane is the grid's maximum, kept as a 24-hour series. This is
the highest-value propagation item on the page per hour of work, and it
replaces our own D-layer *estimate* with NOAA's *model* wherever both exist —
the estimate stays for the LUF arithmetic, labelled as such.

## The field lens

The stated purpose is a dashboard for portable and field work as much as the
shack wall. Ranked by what a portable operator on a rugged laptop with a GPS
and a modem actually reaches for:

1. **Current weather and a short forecast at the site.** The one HamClock
   pane we have no answer to, and the one a field operator checks first.
   Open-Meteo (`api.open-meteo.com/v1/forecast?latitude=…&longitude=…`) is
   key-free and returned 410 bytes of current conditions on a plain GET.
   api.weather.gov needs `/points/<lat>,<lon>` first, then the forecast URL
   *it* names — which is the pattern this project refuses. The open question
   for the maintainer: **the station moves.** A field fix from gpsd changes
   the coordinates the URL needs. Letting the collector substitute the
   configured or GPS-derived station position into a URL template is a
   controlled exception to "sources never construct URLs" — the position is
   local input, not a response — and it should be decided as such, in
   ARCHITECTURE.md, before the source is written.
2. **Sunrise, sunset, and the greyline times at DE.** Not built. Tier 0.
3. **APRS.** A tier 1 stream (APRS-IS, filter by range from your grid) and a
   tier 0 stream (Direwolf/KISS on the LAN). Stations, objects and weather
   beacons on the map. Nothing here yet.
4. **Repeater directory.** RepeaterBook's export API answered **401** on
   2026-09-13 — it now wants an application key and an account. The plan in
   STATUS.md predates that. Route: an offline import, the way `fcc-import`
   builds the ULS index, so the field machine has repeaters with the WAN down
   and nothing is fetched at query time.
5. **NVIS window.** foF2 is already computed at your station; the NVIS
   band is roughly 0.85 × foF2 down to the absorption limit. One line in the
   indicator panel, and an emcomm operator's whole question.
6. **Power budget.** Already a strong-fit candidate in STATUS.md.
7. **Magnetic bearing** beside the true one, for pointing an antenna with a
   compass.
8. **Watch by grid** in Live Spots, so a station that has not transmitted
   sees what its neighbours are being heard on.

## Endpoints, verified 2026-09-13

Fetched with a ranged GET from this machine. "206" is a partial-content
success. Everything HamClock reads that we do not, and the paths that turned
out to be dead.

| Endpoint | Result | Product |
|---|---|---|
| `prop.kc2g.com/api/stations.json` | 200, 42 KB | ~100 ionosondes: foF2, MUF(3000), hmF2, TEC, confidence |
| `prop.kc2g.com/renders/current/mufd-normal-now.svg` | 206 | Rendered MUF map |
| `prop.kc2g.com/api/essn.json` | 200 | Effective SSN |
| `services.swpc.noaa.gov/text/drap_global_frequencies.txt` | 206 | DRAP grid |
| `services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json` | 206 | Kp observed + 3-day forecast |
| `services.swpc.noaa.gov/json/rtsw/rtsw_mag_1m.json` | 206 | Bz, Bt, 1-minute |
| `services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json` | 206 | Solar wind speed, density |
| `services.swpc.noaa.gov/products/summary/solar-wind-mag-field.json` | 200 | Bz/Bt one-liner |
| `services.swpc.noaa.gov/products/kyoto-dst.json` | 206 | DST, hourly |
| `services.swpc.noaa.gov/text/3-day-forecast.txt` | 206 | R/S/G and Kp, three days |
| `services.swpc.noaa.gov/text/27-day-outlook.txt` | 206 | Flux, A, Kp outlook |
| `services.swpc.noaa.gov/json/solar-cycle/sunspots.json` | 206 | Monthly SSN, 1749– |
| `www.sidc.be/SILSO/DATA/EISN/EISN_current.txt` | 206 | Daily estimated SSN |
| `spots.wwff.co/static/spots.json` | 206 | WWFF spots |
| `www.ng3k.com/adxo.xml` | 206 | DXpeditions, RSS |
| `api.open-meteo.com/v1/forecast?…` | 200 | Current conditions, no key |
| `api.weather.gov/points/41.0,-73.0` | 200 | Step one of the NWS chain |
| `www.repeaterbook.com/api/export.php?…` | **401** | Needs a key now |
| `services.swpc.noaa.gov/products/solar-wind/mag-1-day.json` | **404** | Old path, gone; use `json/rtsw/` |
| `www.contestcalendar.com/weeklycont.php` | 200, HTML | No feed; HamClock carries it by permission |

## Next

In order of value per unit of work, subject to the maintainer's call:

1. **SSN source and the SWPC series** — sunspot number (SIDC), Kp forecast,
   solar wind, Bz/Bt, DST: five small source kinds on one parser style, and
   the inputs everything below wants. Panels draw series, not just dials.
2. **DRAP** — source, globe layer, 24-hour pane.
3. **VOACAP point-to-point via `voacapl`** — the DE-DX reliability table,
   with the hang-guarded wrapper and the "install voacapl" honest state.
4. **Sun and moon** — rise/set at DE and DX, lunar az/el and phase, EME
   window, sun and moon markers on the map. All tier 0.
5. **Time travel** and **stopwatch / countdown / alarms**. Tier 0 UI.
6. **Map overlays** — azimuthal-equidistant projection, Maidenhead fields,
   range rings, beacon marks, satellite tracks.
7. **Field weather**, after the URL-template decision is written down.
8. **APRS**, WWFF, DXpeditions on the map, watch-list grammar, PTT.
9. **VOACAP area maps** and the **MUF-RT** map style over the ionosonde feed
   that now ships.

Nothing above is committed. The list is the argument, written so it can be
disagreed with before the code is.

# Parity with hamdash.com

Derived from hamdash.com's own published guide, walked feature by feature. This
is the working list for closing the gap, and an honest record of where we
deliberately do something else.

**Local and LAN is priority one.** Parity is the gate on everything after it.

## Where we deliberately differ

Their guide is explicit that a browser-delivered hosted dashboard is the modern
approach and that locally-installed shack dashboards descend from an older
philosophy. That is a fair description of a real trade-off, and we are on the
other side of it on purpose:

| | hamdash.com | Hammunition Hill |
|---|---|---|
| Delivery | open a URL, nothing to install | install and run it yourself |
| Works offline | no | yes — tier 0 panels and last-known data |
| Your log | not available to it | read from your disk, drives spot colouring |
| Your rig | not available to it | rigctld, WSJT-X UDP |
| Who sees your callsigns | their infrastructure | nobody, unless you enable a provider |
| Setup cost | none | real |

Neither is wrong. Theirs is the better answer for "I want a dashboard now on any
device"; ours is the better answer for "I want the dashboard to know my station
and I want it to work when the internet doesn't." The features below are worth
having either way.

## Status

Legend: **done** · **partial** · **planned** · **not planned** (with the reason)

### Monitor — what is on the air now

| Feature | Status | Notes |
|---|---|---|
| Live map | **done** | Rotatable globe, greyline, spots, great-circle arcs |
| DX spots | **done** | Telnet cluster, filtered client-side, coloured by what you need |
| Beacons | **done** | NCDXF/IARU schedule, computed offline |
| RBN spots | **planned** | Same telnet shape as the cluster; largely a config away |
| RBN band SNR / path matrix | **planned** | Needs aggregation over the RBN feed |
| HF signals | **partial** | Covered by spots; a dedicated view is not obviously additive |
| FT8 digimodes | **partial** | We show *your* decodes from WSJT-X, which they cannot. A PSK Reporter view of everyone else's is separate work. |
| FT8 propagation globes | **planned** | PSK Reporter paths on the globe we already have |

### Activate

| Feature | Status | Notes |
|---|---|---|
| POTA | **done** | |
| SOTA | **done** | |
| WWFF / WWBOTA | **planned** | Same source shape as POTA/SOTA |
| Contests | **done** | Generic iCalendar, so any calendar works |
| Satellites | **planned** | Needs cached TLEs and SGP4; v0.4 |
| QSO log | **done** | Reversed an earlier decision. A write endpoint does not need authentication here, because the network is already the access control — see [LOGBOOK.md](LOGBOOK.md) for the three defences that do the work instead. Multiple logbooks, plain ADIF, append-only, off by default. |

### Weather

| Feature | Status | Notes |
|---|---|---|
| Weather warnings (US) | **done** | `nws_alerts` from api.weather.gov. Tier 1, so it survives the WAN going down. Sorted on NWS severity, not our colour ramp — see [IMAGERY.md](IMAGERY.md) for why that distinction cost a bug. |
| Weather warnings (EU) | **partial** | MeteoAlarm's Atom feeds read today through the generic `rss` source, and their awareness map works as an imagery tile. Structured CAP severity needs a `meteoalarm` source. |
| Weather warnings (Met Office) | **partial** | Their warning map is an imagery tile; no structured feed parsed. |
| Field weather | **partial** | Alerts are in; current conditions are not. A gridpoint forecast needs a two-step `/points` → forecast lookup, which means fetching a URL an upstream named — doable behind the egress guard, deliberately not rushed. |
| Lightning | **done** | Any lightning map is one `[[imagery]]` entry. |
| Regional radars (NOAA, Met Office, Japan, MENA, Asia-Pacific) | **done** | All tier 2 images, one config line each. |

### Listen

| Feature | Status | Notes |
|---|---|---|
| WebSDR / shortwave streams / directory | **partial** | Reachable as tier 2 embeds; no dedicated panel |
| Built-in SDR receiver | **not planned** | WebUSB needs a secure context, so it would force TLS onto a LAN appliance for one panel. You are already on the network with the radio — point a tier 2 panel at your own OpenWebRX+ or KiwiSDR and get a better receiver. |

### Tools

| Feature | Status | Notes |
|---|---|---|
| Callsign lookup | **done** | Local-first, with optional providers |
| Bearing calculator | **done** | Inside callsign lookup and on every spot |
| Band plan | **done** | By licence class, which theirs does not do |
| Solar terminator | **done** | The greyline layer on the map |
| Contest calendar | **done** | |
| Repeater finder | **planned** | RepeaterBook has a public API |
| MUF predictor | **planned** | The solarstorm_scout propagation model — see REUSE.md |
| Propagation prediction | **partial** | Band conditions from HamQSL; VOACAP still deferred |
| Education | **not planned** | Better served by the ARRL and existing study sites than by a dashboard |

### Space weather

| Feature | Status | Notes |
|---|---|---|
| Solar overview / output / activity | **done** | As dials with numbers |
| X-ray flux | **done** | Dial, with the R-scale in the label |
| Geomagnetic K / solar wind | **done** | Dials |
| Noise / protons | **done** | Dials |
| NOAA scales | **done** | R/S/G tiles from NOAA's own product, alongside our dials |
| Aurora oval | **done** | SWPC OVATION, reduced to an oval boundary and drawn as a globe layer |
| D-layer absorption | **planned** | solarstorm_scout has a model; needs the solar-zenith fix |
| Ionospheric map | **planned** | |
| Solar imagery | **done** | SDO is an `[[imagery]]` tile like any other |
| SWPC alerts | **done** | Watches, warnings and summaries as SWPC issues them |
| Space weather guide | **partial** | Our dial labels explain severity inline, which arguably does this job better than a separate explainer |

### Community and account

| Feature | Status | Notes |
|---|---|---|
| Callsign / grid settings | **done** | Config file, plus browser geolocation to find your grid |
| Custom layout, reset layout | **partial** | Dashboards are configurable; drag-to-reorder is not built |
| Accounts | **not planned** | There is nothing to have an account with |
| YouTube / Facebook / about | **not planned** | Not a dashboard feature |

## What we have that they do not

Worth keeping in view, because these are the reasons for the trade-off:

- **Spot colouring by what you still need**, from your own ADIF on disk.
- **Live rig frequency and mode** from rigctld, scoping what you see to the band
  you are on.
- **Your own WSJT-X decodes**, live over UDP.
- **Band plan by licence class**, including the grandfathered ones.
- **Works with the WAN down** — clocks, band plan, greyline, callsign lookup,
  and the last good reading of everything else.
- **Nothing leaves the machine** unless you switch a provider on.

## Next

In order of value per unit of work:

1. ~~Aurora, NOAA scales, SWPC alerts.~~ Done.
2. ~~Weather alerts and the regional radars.~~ Done. The tier 2 image path did
   turn out to unlock the radars, lightning and solar imagery at a config line
   each, as expected.
3. The MUF / D-layer model from solarstorm_scout, with the solar-zenith fix.
4. RBN, which is the cluster client pointed somewhere else.
5. Satellites, which needs real orbital mechanics.

Smaller, now unblocked by the work above:

- A `meteoalarm` source, for structured EU severity rather than headlines.
- Field weather conditions, once the `/points` → gridpoint chain is done
  properly rather than by letting a source build URLs from a response.
- "AT YOUR QTH" vs "OPEN ELSEWHERE" band pills, spotted in the hamdash
  screenshots and still outstanding.
- CW/Morse reference tools — tier 0, self-contained, promised and not yet built.

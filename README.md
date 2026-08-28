<p align="center">
  <img src="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/logo.png"
       alt="Hammunition Hill" width="360">
</p>

# Hammunition Hill

A ham radio dashboard that runs on your own machine, on your own network, and
talks to nobody you did not name.

Companion to [Hammunition](https://github.com/ChiefGyk3D/Hammunition), which
turns a Debian-family install into an amateur radio, SDR, and RF workstation.
Hammunition builds the shack computer; Hammunition Hill is what you put on the
monitor above it — the high ground you watch the bands from.

![The Home dashboard](https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/home.png)

Six dashboards, twenty-six panels, one machine. Nothing above was fetched by
your browser from anyone else's server — the screenshots are taken by CI, from a
real Chromium, against a real collector, so they are what the code renders
rather than what a designer drew.

<table>
<tr>
<td width="33%"><a href="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/map.png"><img src="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/map.png" alt="Map"></a><br><b>Map</b> — rotatable globe, greyline, spots coloured by your log</td>
<td width="33%"><a href="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/space-weather.png"><img src="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/space-weather.png" alt="Space Weather"></a><br><b>Space Weather</b> — eight scales, MUF and D-layer absorption</td>
<td width="33%"><a href="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/operating.png"><img src="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/operating.png" alt="Operating"></a><br><b>Operating</b> — band plan, NCDXF beacons, logbook, CW trainer</td>
</tr>
<tr>
<td><a href="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/activity.png"><img src="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/activity.png" alt="Activity"></a><br><b>Activity</b> — POTA and SOTA spots, contest calendar, news feed</td>
<td><a href="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/field-weather.png"><img src="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/field-weather.png" alt="Field &amp; Weather"></a><br><b>Field &amp; Weather</b> — NWS alerts, GPS grid, radar and satellite imagery</td>
<td><a href="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/home.png"><img src="https://raw.githubusercontent.com/ChiefGyk3D/hammunition-hill/main/docs/images/home.png" alt="Home"></a><br><b>Home</b> — the summary you leave up on the wall</td>
</tr>
</table>

Regenerate them with `make screenshots` after any change to how the dashboard
looks; they are written by the same script the `frontend` CI job runs. They are
linked by absolute URL rather than by relative path because this file is also
the package long description, and PyPI has no repository to resolve
`docs/images/` against.

---

## ⚠️ Alpha — it works, and it is not finished

**Status: alpha. It runs, it is useful today, and config will break between
versions.** Being honest about where the edges are matters more than looking
finished, so here is exactly where things stand:

| | Status |
|---|---|
| Collector, snapshot architecture, static server | ✅ working |
| Egress allowlist, CSP, path handling | ✅ working |
| Panels | ✅ 26 across 6 dashboards |
| Source kinds | ✅ 11 polled, 6 stream, 1 file |
| Space weather dials | ✅ 8 scales |
| Map — rotatable globe, greyline, spots, aurora | ✅ working |
| Your log driving spot colouring | ✅ working |
| DX cluster, WSJT-X, `rigctld` | ✅ working |
| Logbook | ✅ working, off by default |
| Callsign lookup — 4 providers, chained, offline-capable | ✅ working |
| Weather alerts and tier 2 imagery | ✅ working |
| Band plans | 🟡 US only — international is a data contribution, not code |
| Propagation — MUF, LUF, D-layer absorption | ✅ working |
| VOACAP point-to-point | ❌ **not written** |
| Weather outside the US | 🟡 feeds and maps; no structured severity |
| Callsign query endpoint | ❌ **not written** — the config flag parses and does nothing |
| GPS — portable auto-grid and clock check | ✅ working |
| CW / Morse tools — reference, translator, audio | ✅ working |
| CW trainer — Koch, callsigns, QSO simulator, quiz | ✅ working |
| Shack tools — antenna, feedline, SWR, Ohm's law, dB, wire, battery | ✅ working |
| Satellites — cached TLEs, SGP4 passes, Doppler | ✅ working, optional extra |
| RBN — who is hearing you, and band activity | ✅ working, off by default |
| Metrics — Prometheus endpoint | ✅ working, off by default |
| Metrics — InfluxDB push | ❌ **not written** |
| Licence exam practice — all three US pools included | ✅ working |
| Part 97 quoted beside a rules answer | ✅ working |
| CI — 9 jobs plus CodeQL, 3 Python versions, x86 + ARM + macOS | ✅ working |
| Docker image, distro packages, `pip install` without a clone | ❌ **not written** |

**Full inventory, every subsystem: [docs/STATUS.md](docs/STATUS.md).** That page
is the one kept current; anything here is a summary of it. It also carries the
**candidate feature list** — the gap between this and covering most of what an
operator needs in one place, with an honest fit assessment for each.

You can run this today on a Pi or a laptop and get a genuinely useful shack
display. What you should not do is expose it to the internet — see below, it has
no authentication by design — or expect the config file you write this week to
load unchanged next month.

**Two things you can help with that need no Python:** an international band plan
(one JSON file, the loader is already generic), and telling us when an upstream
source breaks. Upstream endpoints rot constantly, and `hamhill check` on real
hardware finds it faster than we can.

### Documentation

| | |
|---|---|
| **[Install](docs/INSTALL.md)** | Get it running, on a Pi or anywhere else. Start here. |
| **[Configuration](docs/CONFIGURATION.md)** | Every option, every source kind. |
| **[Security](docs/SECURITY.md)** | The threat model, and why there is no login. **Read before exposing it to anything.** |
| **[Architecture](docs/ARCHITECTURE.md)** | How it works and why it is shaped this way. |
| **[Writing panels](docs/PANELS.md)** | The panel contract. |
| **[Callsign lookup](docs/CALLSIGN-LOOKUP.md)** | Provider options, trade-offs, and the architectural line. |
| **[CW & Morse](docs/CW.md)** | Reference, translator, timing, audio, and a four-drill trainer. |
| **[Shack tools](docs/TOOLS.md)** | Antenna cut chart, feedline loss, SWR, Ohm's law, dB, voltage drop, battery runtime, grid paths. |
| **[Logbook](docs/LOGBOOK.md)** | Logging contacts, the ADIF file it writes, and why it is off by default. |
| **[Satellites](docs/SATELLITES.md)** | Pass prediction computed here from cached elements, and why the propagator is the one borrowed thing. |
| **[Reverse Beacon](docs/RBN.md)** | Who is hearing you with an SNR, band activity, and how a few thousand spots a minute stay bounded. |
| **[Metrics](docs/METRICS.md)** | The Prometheus endpoint, what it exports, and why nothing is labelled by callsign. |
| **[Licence exam](docs/EXAM.md)** | Practising from the official pools, how they are kept honest, and the rule that makes a practice exam real. |
| **[GPS](docs/GPS.md)** | Automatic grid square when portable, and why it publishes a locator rather than a fix. |
| **[Propagation](docs/PROPAGATION.md)** | The MUF/LUF indicator, what it is worth, and what it is not. |
| **[Imagery & weather](docs/IMAGERY.md)** | Weather alerts, radar and satellite tiles, and what a tier 2 tile costs you. |
| **[Branding](docs/BRANDING.md)** | The logo, the mark, the palette, and what you may do with them. |
| **[Contributing](CONTRIBUTING.md)** | `make check` before you push, and what CI enforces. |
| **[CLAUDE.md](CLAUDE.md)** | Architecture invariants and standing conventions, for humans and agents alike. |
| **[Status](docs/STATUS.md)** | **Complete feature inventory — what works, what is partial, what is not written.** |
| **[Parity](docs/PARITY.md)** | Feature-by-feature against hamdash.com, including where we deliberately differ. |
| **[Reuse audit](docs/REUSE.md)** | What is worth borrowing from the sibling projects. |

---

## Do not expose this to the internet

**Hammunition Hill has no authentication and no authorization model, by
design.** That absence is exactly what keeps its attack surface at "static file
server" — there is no login to bypass, no session to steal, and no request that
can change what the collector does, because there is no endpoint that accepts
one.

The cost of that design is simple and non-negotiable: **the network is the only
access control there is.** Anyone who can reach the port sees your dashboard,
your QTH, your rig state, and anything derived from your log.

It binds to `127.0.0.1` by default. If you want to reach it from elsewhere, put
a real access layer in front and come in through that:

**Zero Trust Network Access — preferred**

| | |
|---|---|
| [Twingate](https://www.twingate.com/) | What this project's author uses |
| [NetBird](https://netbird.io/) | Open source, self-hostable |
| [Tailscale](https://tailscale.com/) | Easiest to stand up |
| [Headscale](https://github.com/juanfont/headscale) | Self-hosted control plane |
| [Zscaler Private Access](https://www.zscaler.com/) | If you already have it at work |
| Cloudflare Tunnel | **Only** with Access policies in front of it |

**Conventional VPN — acceptable:** WireGuard, OpenVPN.

**Not acceptable, ever:** port forwarding to the shack, a public VPS with the
port open, a bare tunnel with no identity check, or "nobody knows the URL."

A reverse proxy with basic auth is better than nothing, but it is not the same
thing — it authenticates a *request*, where ZTNA authenticates a *device and an
identity* before a packet reaches the host. Full detail in
[docs/SECURITY.md](docs/SECURITY.md).

---

## How it works

The hard part of a local-first dashboard is that DX cluster is telnet, most ham
APIs send no CORS headers, and none of it can be reached from a `file://` page.
The usual answer is a web app with an API. This project takes a different one:

**The server does its work on a timer, not on a request.**

A collector polls upstream sources on a fixed schedule, normalizes what it gets,
and writes plain JSON snapshots to disk. A static file server hands those files
to the browser. That is the entire HTTP surface — *read bytes from disk, send
bytes.*

```
  upstream            hamdashd (one process)              browser
  ─────────    ┌────────────────────────────────┐    ────────────
  DX cluster   │  collector  →  data/*.json  →  │    same-origin
  NOAA SWPC ──►│  fixed schedule    atomic      │──► filters spots
  HamQSL       │  host allowlist    writes      │    draws greyline
  POTA/SOTA    │                  static server │    layout in
               └────────────────────────────────┘    localStorage
```

What follows from it:

- **No query parsing, no user input reaching server code.** Band, mode, and
  continent filtering happen client-side, over the spot array the browser
  already holds. The server is never asked what you filtered for.
- **Nothing an attacker sends can steer an outbound fetch.** The schedule and
  the host allowlist are fixed when the config file loads.
- **No third-party JavaScript, ever.** Fonts, styles, and scripts are served
  from your host. Feeds are parsed by the collector, not by a feed-proxy service
  that would otherwise receive your entire reading list.
- **It degrades honestly.** With the WAN down, tier 0 panels keep computing and
  tier 1 panels show their last good reading with its true age, rather than
  going blank or quietly showing yesterday's numbers as current.

More in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Dashboards

Twenty-two panels in one grid is unusable, so they are grouped into tabs:

| | |
|---|---|
| **Home** | clocks, rig, solar, band conditions, spots, WSJT-X |
| **Map** | the globe, with the spot list beside it |
| **Space Weather** | solar and geomagnetic dials, NOAA scales, alerts, band conditions |
| **Operating** | beacons, logbook, callsign lookup, log stats, band plan |
| **Activity** | POTA/SOTA, contests, news |
| **Field & Weather** | active NWS alerts, radar and satellite tiles |

Edit `web/panels/index.json` to regroup them — a dashboard is an id, a name, and
a list of panel ids. Your last tab is remembered per browser. A flat `enabled`
list still works and becomes a single unnamed dashboard.

## Beacons

Eighteen NCDXF/IARU beacons share five frequencies on a fixed three-minute cycle
synchronised to UTC. Because the schedule is fixed, which beacon is transmitting
where is **arithmetic on the clock** — this panel needs no network at all.

That makes it the most directly useful thing here when the internet is down and
the antenna is still up. Tune 14.100, see which beacon should be on, and whether
you hear it tells you more about whether the band is open to that part of the
world than any prediction does. Each beacon sends its callsign then four dashes
at 100 W, 10 W, 1 W and 100 mW; how far down that ladder you can still hear is a
signal report you take by ear.

The schedule is the schedule — individual beacons go off the air, which is part
of what makes listening informative.

## Dials, and numbers

A bare figure does not tell you whether it is good. "A-index 4" means nothing
until you know 7 is the quiet threshold, and "C2.1" means nothing until you know
where C sits between B and X. So every space weather metric is shown as a dial
*and* a number: the needle and the coloured band give you severity at a glance,
the figure gives you the precision, and a text label says which is which.

**The classification lives in Python, not in the panel.** Whether K=5 is a storm
is a fact about geomagnetism, not a drawing decision — so it sits in
`severity.py` where it is tested, and the renderer only draws what it is handed.
Thresholds follow NOAA's published scales where they exist (G for geomagnetic,
R for radio blackout, S for radiation) and operating convention where they do
not.

Two things about this were measured rather than chosen:

**Three severity levels, not four.** Four status colours cannot be told apart
reliably — an amber-versus-orange pair measures below the normal-vision
separation floor before you even consider colour blindness. Three separate
cleanly (ΔE 27.6 normal, 11.3 protan). The palette this replaced measured 14.5,
which is below the floor for telling two colours apart *at all*, and it was
already shipping in Band Conditions.

**Every dial carries a text label.** Colour never carries the meaning alone, so
the dials work in greyscale, in print, and for a colour-blind reader. Each one
also has an `aria-label` reading the value and its severity.

One scale is deliberately not its full theoretical range: A-index tops out at 50
rather than 400, because a 0–100 dial squeezed the quiet zone into an invisible
sliver — the dial looked alarming while its label said "Quiet", which is the
worst thing a severity display can do. Above 50 the needle pins, which is the
right message for a major storm.

## The map

A globe rather than a flat projection, because the thing operators most want to
see is a great-circle path, and great circles look wrong on Mercator —
Connecticut to Japan goes over the pole, and only a sphere shows that honestly.

Drag to rotate, scroll or the buttons to zoom, **QTH** to recentre on your
station, and click a station to select it. Layers toggle independently:
greyline, aurora, spots, arcs, parks, graticule, label.

The **aurora** layer is NOAA's OVATION forecast. The raw product is a
quarter-million-point grid several megabytes wide, so the collector reduces it
before publishing: the equatorward edge of the oval in each hemisphere — the
line that matters, since HF paths crossing it degrade and VHF sometimes opens
along it — plus a coarse cell grid for shading. Reducing on the collector rather
than in the browser is the same principle as everywhere else: do the work once,
on a schedule, and hand every viewer a small file.

It is drawn on a 2D canvas with **no WebGL and no library** — the whole thing is
a projection function and some paths, which keeps the read-the-source promise
intact. Coastlines are a 60 KB [Natural Earth](https://www.naturalearthdata.com/)
outline (public domain) that ships with the dashboard, and the greyline is
computed from the clock, so **the map works with the WAN unplugged**. Regenerate
the outline with `tools/build_world.py` if you ever need to.

### Finding your grid square

**FIND MY GRID** on the map asks the browser where you are and converts it to a
Maidenhead locator. The coordinates never leave the browser — the grid is
computed locally and stored locally, and the panel nudges you to paste it into
`config.toml` so the collector uses it too.

It needs a secure context, so it works at `http://localhost` and is disabled
with an explanation on a plain LAN address. That is a browser rule, not
something this project can opt out of.

## Three tiers of trust

Every panel declares a tier, and the tier is visible in the UI. You should be
able to see at a glance which parts of your wall reach outside the house.

| Tier | What it is | Examples |
|---|---|---|
| **0 — offline** | Nothing originated off this machine: computed in the browser, or read from local config, your log, or data shipped with the dashboard. Works with the internet unplugged. | clocks, band plan, callsign lookup, greyline, bearing + distance |
| **1 — your host** | Fetched by the collector from upstream, served to the browser as same-origin JSON. No third-party code, no CORS, no leaked referrers. | DX spots, solar and space weather, POTA, SOTA, contests, weather alerts, RSS |
| **2 — foreign** | Content your browser loads from someone else. Off by default, allowlisted per host. | radar loops, lightning maps — and local gear like Pi-Star or OpenWebRX+ |

Two rules do most of the work inside tier 2. **Prefer `<img>` over `<iframe>`**:
a radar loop is a GIF, and an image element cannot run script, reach storage, or
navigate. That preference is enforced rather than advised — `[[imagery]]` tiles
reach `img-src` and nothing else, so a host you added for a picture never gains
the right to be framed. `[embeds] allow_hosts` is the separate, bigger decision
for when you actually want a frame.

**Opaque mode** (planned) has the collector fetch and cache remote images
itself, so the browser never contacts a third party and the CSP tightens to
`img-src 'self'`. That is not a departure from the architecture — it is a source
that writes a file, like every other one. It needs content-type discipline
before it ships: an upstream serving SVG where we expected PNG would put a
scriptable document on our own origin. See
**[docs/IMAGERY.md](docs/IMAGERY.md)**.

## Quick start

Requires Python 3.11 or newer.

```bash
git clone https://github.com/ChiefGyk3D/hammunition-hill
cd hammunition-hill
python3 -m venv .venv && .venv/bin/pip install -e .

cp config.example.toml config.toml
$EDITOR config.toml          # set your callsign and grid

.venv/bin/hamhill check      # validate config and egress policy, fetch nothing
.venv/bin/hamhill serve      # http://127.0.0.1:8073
```

`hamhill check` is worth running after any config edit. It prints the bind
address, the generated Content-Security-Policy, and every source with the
egress verdict for its host — without making a single outbound request.

To reach the dashboard from a tablet on the LAN, **read
[docs/SECURITY.md](docs/SECURITY.md) first**, then:

```bash
.venv/bin/hamhill --listen 0.0.0.0:8073 serve
```

Anything other than loopback prints the network warning at startup, every time.
That is deliberate.

### One thing that will confuse you later

`http://localhost` is a *secure context*; `http://192.168.1.50` is not. Browser
features gated on secure contexts — WebUSB, geolocation, service workers — work
on the shack machine and silently fail on the tablet. This is a browser rule, not
something this project can opt out of. It is also why an in-browser SDR receiver
is not on the roadmap: chasing one would force TLS onto a LAN appliance for a
single panel, when you are already on the same network as a real
[OpenWebRX+](https://www.openwebrx.de/) or KiwiSDR that you can point a panel at.

## Band plans

Pick Novice, Technician, General, Advanced, or Amateur Extra and the panel
shows what that class may actually use — segment by segment, with modes and the power limits that
apply. Bands with no privileges for the selected class are greyed out rather
than hidden, so the shape of what you gain by upgrading is visible.

It is tier 0: the plan ships with the dashboard as a static JSON file, so it
works with the WAN down, which is exactly when you might be checking a band
edge.

**It defaults to your own class.** Set a callsign in `[station]` and the panel
usually opens on the right one — US callsign format tells you a lot, and for a
Group A call (1x2, 2x1, or a 2x2 beginning with A) it tells you exactly, because
only an Amateur Extra may hold one. Every other format is a best guess with a
floor, since vanity lets you hold a call from any group at or below your own, so
the footer says what it inferred and why. To be exact:

```toml
[station]
license_class = "general"
```

A configured class always wins, and picking a class in the panel always wins
over both — it is a reference for classes you do not hold as much as for the one
you do. Non-US callsigns get no guess at all rather than a wrong one.

**It is reference material, not authority.** The footer names the regulation and
the revision date the file was written against. Part 97 is what governs; check
it before transmitting near an edge.

### Correcting or adding one

Band plans live in `web/bandplans/` — `index.json` plus one file per country.
Correcting a band edge is a one-line JSON change, no Python involved, and
`tests/test_bandplan.py` validates every file: segments inside their band,
classes that actually exist, bands ascending in frequency, and band names that
match `bands.py`. That last check catches drift that would otherwise put spots
and privileges in different buckets invisibly.

Adding another country is a new file plus a line in `index.json`; the panel
grows a country selector automatically once there is more than one to choose
from. **US only for now** — the structure is already country-agnostic, so an
IARU Region 1 or Region 3 plan is a data contribution rather than a code change.

Novice and Advanced are included — both are closed to new issue, but existing
holders keep their privileges, so both appear with a dashed chip marking them as
grandfathered.

## The logbook

Log a contact from the dashboard, into plain ADIF files on your disk. Several
logbooks if you want them — a home station, a portable rig, a club callsign —
each its own file.

It belongs here for one reason: **the dashboard already knows almost the whole
QSO.** `rigctld` gives the frequency, band and mode as they are right now; a
selected spot gives the callsign and entity; the lookup gives the name. Logging
is a confirmation, not a form-filling exercise.

And it closes a loop. The needed-slot colouring reads these same files, so
working a new entity here makes the spot list stop calling it new on the next
cycle — no synchronisation step, because both halves are reading the same bytes.

It is **not** Log4OM, and should not try to be. No contest mode, no award
tracking, no QSL management.

**Off by default**, because it is the one place the server accepts input. It is
append-only — no edit, no delete, here or over HTTP — and defended against
cross-site posting and DNS rebinding. Full reasoning, including the position I
revised to get here, in **[docs/LOGBOOK.md](docs/LOGBOOK.md)**.

## Callsign lookup

Type a callsign and get its DXCC entity, continent, CQ zone, short and long path
headings, distance, and — if your log is loaded — whether you have worked that
entity and whether it is confirmed.

It resolves **instantly and entirely on your machine.** The collector publishes
its prefix table as a snapshot; the browser does the lookup itself. The callsign
you typed never leaves the machine, and no request is made per lookup.

### Adding name and licence detail

Name, grid, and licence class need a data source that knows about people rather
than prefixes. That is opt-in, because every option costs something and which
cost is acceptable is your call:

| Provider | Cost | Coverage |
|---|---|---|
| *(default: none)* | nothing leaves the machine | entity, heading, distance, worked status |
| `fcc_uls` | ~160 MB download, ~100 MB on disk | US — **no per-lookup network at all** |
| `callook` | one request per callsign | US, free, no account |
| `hamqth` | account + a request per callsign | worldwide, free |
| `qrz` | paid subscription + a request per callsign | worldwide, best data |

Providers are an **ordered chain**, not one choice:

```toml
[lookup]
providers = ["fcc_uls", "qrz"]
```

Each callsign walks the list: one that answers wins, one that says *not on file*
falls through. Local-first is usually the right order, and not because the local
one is a fallback — it is the fast path. It answers US calls instantly from
disk, declines everything else for free so QRZ only sees the calls it is
actually needed for, and it is the only free source that is authoritative for
operator class. Put QRZ first instead if you want its data preferred for US
calls too; both orders work.

`provider = "callook"` still works and means a chain of one.

### Away from the internet

For a portable station, no signal is the normal condition rather than an
exception, so it is handled without a mode to switch on:

- **Network providers stop being waited on.** After two consecutive failures the
  collector concludes the WAN is gone and skips them for five minutes. Without
  that, twenty new callsigns means twenty connect timeouts in sequence and a
  dashboard that should have answered from a local index does nothing for
  minutes. Offline providers carry on untouched.
- **The cache keeps answering, honestly.** Expired entries are still published,
  flagged `stale` with their age. A licence record from five weeks ago is almost
  certainly still right and is unarguably better than a blank panel — so a night
  of resolution at home still answers in a field a month later. Turn it off with
  `serve_stale = false`.

`fcc_uls` needs a one-off `hamhill fcc-import` before it can answer. The import
streams rather than buffering, so it needs about 4 MB of RAM regardless of
database size and runs fine on a Pi.

**Resolution is scheduled, not on demand.** The collector works through
callsigns that already appear in your spots and decodes, capped and cached, so
no request causes a fetch and the architecture holds. That answers "who is this
station I am seeing", which is what a dashboard is actually asked.

Looking up *arbitrary* callsigns needs an endpoint that accepts input — the one
thing this design avoids. That endpoint is **designed but not built**: the
`query_endpoint` flag parses and does nothing today. The intended shape is the
narrowest thing that can do the job — GET only, local index only, strictly
validated, rate limited, and unable to cause an outbound request — and it will
stay opt-in when it lands. See [docs/STATUS.md](docs/STATUS.md).

With a network provider, **the callsigns you are watching go to that provider.**
That is inherent. `fcc_uls` is the option where nothing leaves the machine — and
putting it first in a chain means the network provider only ever sees what the
local index could not answer.

Full analysis, including why there is no fourth way:
**[docs/CALLSIGN-LOOKUP.md](docs/CALLSIGN-LOOKUP.md)**.

## Callsign resolution

Spots and log entries both resolve through the same prefix table, so "needed" is
always comparing like with like. Two sources, in order:

1. **cty.dat**, if you point `[log] cty_dat` at one. AD1C's country file is the
   reference every logging program uses, and any logger you already run probably
   ships a copy. We read it rather than vendoring a snapshot that would go stale.
2. **A compact built-in table** otherwise, covering the entities most operators
   actually see. Approximate by construction, and the Log panel says so when it
   is in use.

## Configuration

One TOML file. There is no settings API and no write endpoint — presentation
state (layout, filters, which panels are shown) lives in the browser's
localStorage, and everything that touches the network lives in the file. Nothing
reachable over HTTP can change any of it, which is why there is no CSRF surface
and nothing to authenticate.

```toml
[[sources]]
id = "hamqsl"                                   # becomes data/hamqsl.json
kind = "hamqsl"
url = "https://www.hamqsl.com/solarxml.php"
interval = 900                                  # seconds, floor 30
```

A source pointing at your own LAN has to say so:

```toml
[[sources]]
id = "pistar"
kind = "rss"
url = "http://pi-star.local/feed.xml"
local = true    # without this, the egress guard refuses any host that
                # resolves to a private or loopback address
```

That guard is what stops a mistyped or hijacked upstream URL from being turned
into a probe of the network the dashboard is sitting on.

## Panels

A panel is a directory under `web/panels/` with a `panel.json` manifest and a
`panel.js` module exporting `render(root, ctx)`. The manifest declares the
tier, the snapshots the panel reads, and any tier 2 hosts it needs — so a panel
cannot quietly widen the CSP or the egress allowlist. See
[docs/PANELS.md](docs/PANELS.md).

Shipping now:

| Panel | Tier | What it shows |
|---|---|---|
| **Time** | 0 | UTC and local, computed in the browser |
| **Rig** | 1 | Dial frequency and mode from rigctld |
| **Solar & Space Weather** | 1 | Solar flux, sunspots, X-ray and A-index as dials |
| **Geomag & Particles** | 1 | K-index, solar wind, band noise, proton flux as dials |
| **NOAA Scales & Alerts** | 1 | NOAA's own R/S/G storm scales and the alerts SWPC has issued |
| **Band Conditions** | 1 | HamQSL HF conditions, day and night |
| **World Map** | 1 | Rotatable globe: greyline, DX spots, great-circle paths from your QTH |
| **NCDXF Beacons** | 0 | Which international beacon is on each band right now, from the clock alone |
| **Logbook** | 0 | Log a QSO pre-filled from your rig and the selected station, straight to ADIF |
| **Band Plan** | 0 | Which frequencies your licence class may use, by band and mode |
| **Callsign Lookup** | 0 | Entity, beam heading, distance, and whether you have worked it |
| **DX Cluster** | 1 | Live spots, filtered by band/mode/continent, coloured by what you need |
| **POTA & SOTA** | 1 | Park and summit activations, merged and sorted by band |
| **WSJT-X** | 1 | Live decodes and status |
| **Contests** | 1 | Upcoming contests, with anything running now flagged |
| **Log** | 1 | What your ADIF contains and how it was resolved |
| **AMSAT News** | 1 | RSS, parsed server-side |

## Roadmap

| | | |
|---|---|---|
| **v0.1** | Skeleton ✅ | Collector, static server, tier 0 panels, solar and space weather, RSS. Proves the snapshot architecture end to end. |
| **v0.2** | Spots ✅ | DX cluster telnet client, client-side filtering, spot detail with bearing and distance. POTA, SOTA, contest calendar. |
| **v0.3** | The differentiator ✅ | ADIF log ingest and needed-slot spot colouring. `rigctld` and WSJT-X UDP. |
| **v0.4** | Parity | Satellite passes from cached TLEs. Weather alerts, aurora, greyline and the map are done. |
| **v0.5** | Other people's shacks | LAN mode hardening, opaque image proxy, tier 2 allowlisting, systemd + Docker + Pi install docs. |
| **v1.0** | Community | VA3HDL `config.js` importer, panel SDK, example dashboards. |
| later | Deferred on purpose | WebSocket spot push, VOACAP, [a Grafana version](#deferred-a-grafana-version). And only after all of that, any conversation about a hosted mode — which needs a real authn/authz model, TLS, rate limiting, and a threat model this version deliberately does not have. |

### What still stands between here and parity

Local and LAN is priority one, and parity with hamdash.com is the gate on
everything below it. What is left:

| | Where it goes | Notes |
|---|---|---|
| ~~Greyline / day-night map~~ | ✅ done | Solar subpoint maths plus a bundled world outline. Computes offline. |
| ~~Weather alerts~~ | ✅ done | `api.weather.gov` as a tier 1 source, so alerts survive the WAN dropping. Radar, lightning and satellite as tier 2 tiles. MeteoAlarm and Met Office read as feeds and maps; structured EU severity is still open. |
| ~~Aurora forecast~~ | ✅ done | SWPC OVATION, as a globe layer. |
| **VOACAP point-to-point** | later | The genuinely hard one. Either bundle the public-domain ITSHFBC binaries and shell out, or ship a simpler MUF/LUF indicator derived from SFI/K first and do the real thing when it earns the effort. |

Satellite passes are on the same milestone but are *past* parity — hamdash.com
does not have them.

The one panel we will not match is its browser SDR receiver, and that is a
choice rather than a gap: chasing WebUSB would force TLS onto a LAN appliance
for a single panel, when you are already on the same network as a real
OpenWebRX+ or KiwiSDR you can point a tier 2 panel at.

### Planned: an optional metrics exporter

Wanted eventually, explicitly **after** parity. Revised from an earlier plan to
build a whole separate project, which was over-scoped: the useful thing is not a
second dashboard, it is **an export path out of this one**.

The collector already holds every number worth trending — solar flux, K-index,
spot counts by band, decode rates, rig time-on-band. Emitting those to InfluxDB
or exposing a Prometheus endpoint is a small, additive feature, not a new
architecture. Grafana then does what Grafana is good at, and we do not have to
become a time-series stack to get there.

Two things to keep straight when it lands. It is **the first outbound write this
collector would ever make**, carrying data derived from your location and log, so
it wants the same allowlist treatment as everything else and a local-only
default. And a Prometheus endpoint is an *endpoint* — read-only and metrics-only,
but it belongs in the same opt-in category as the logbook's write path rather
than being switched on quietly.

A slice already works with no code at all: snapshots are JSON served over HTTP,
so Grafana's Infinity datasource can read `http://your-host:8073/data/solar.json`
directly. That covers current-state panels today.

What it does not cover is the thing Grafana is actually good at. **Snapshots have
no history** — each write replaces the last, deliberately, because the design is
"what is true now". SFI over six months, spots per band across a contest weekend,
decodes per hour: none of that is answerable from what is on disk, which is
exactly why the exporter is the right shape rather than a bigger dashboard.

Also worth keeping straight: Grafana itself is a full application with
authentication, users, plugins, and a database. "Safe to expose because it is
static files" stops being true of *that* deployment, and its network stance is a
separate decision from this one.

### What only a local dashboard can do

Parity with the hosted dashboards is the floor, not the goal. The argument for
local-first is not privacy — it is *access*. A cloud dashboard does not have
your logbook, your rig, or your antenna.

- **Spot colouring by new DXCC or needed band-slot** ✅, read from your ADIF log
  on disk. Every hosted dashboard has to ask you to upload it. This one just
  reads it. Three independent answers per spot, because operators chase
  different things: `NEW` (never worked), `BAND` (worked, not on this band),
  `MODE` (worked, not in this mode group).
- Live frequency and mode from the rig via Hamlib `rigctld` ✅. Read-only: the
  client sends two get commands and has no code path that could key a
  transmitter.
- Live FT8 decodes and QSO events from WSJT-X's UDP broadcast ✅. Listen-only.
- Rotator position and one-click beam headings via `rotctld`.
- Alerting when a needed entity appears on a band that is currently open —
  log, propagation, and spots joined locally.
- Shack telemetry: SWR, PA temperature, UPS via NUT, weather station via
  WeeWX or Ecowitt, anything `rtl_433` hears.
- Local digital infrastructure: Pi-Star, AllStar, SvxLink, an APRS igate,
  `dump1090`.
- **Degraded-mode operation.** Greyline, band plans, satellite passes, and the
  last known solar numbers keep working with the WAN down. That makes it an
  EmComm tool. A hosted dashboard is a blank page.

## Related projects

- **[Hammunition](https://github.com/ChiefGyk3D/Hammunition)** — provisions the
  workstation this runs on.
- **[SolarStorm Scout](https://github.com/ChiefGyk3D/solarstorm_scout)** — posts
  NOAA space weather to Bluesky and Mastodon. Its propagation model is the
  pre-VOACAP indicator this roadmap calls for.
- **[Penguin Overlord](https://github.com/ChiefGyk3D/penguin-overlord)** — a
  Discord bot whose `radiohead` cog carries a structured ARRL band plan and
  several SWPC products not yet wired up here.

See **[docs/REUSE.md](docs/REUSE.md)** for what is worth taking from each, what
needs fixing on the way in. The licence question is settled: this project is
MPL-2.0, matching both siblings, so logic ports by copy-paste.
- **[VA3HDL/hamdashboard](https://github.com/VA3HDL/hamdashboard)** — the
  tile-and-iframe dashboard a lot of hams already run. Excellent at what it
  does. Config compatibility is planned for v1.0.

## Contributing

Run the tests before opening a PR:

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/ruff check .
```

The security-critical modules are `egress.py`, `server.py`, and `snapshot.py`.
Changes there need tests. If a change would add an HTTP endpoint that accepts
input, it is almost certainly the wrong shape for this project — put the work in
the collector instead.

## Credits

- Coastlines: [Natural Earth](https://www.naturalearthdata.com/), public domain.
- Space weather: [NOAA SWPC](https://www.swpc.noaa.gov/) and
  [HamQSL](https://www.hamqsl.com/) (N0NBH).
- Activations: [POTA](https://pota.app/) and [SOTA](https://www.sota.org.uk/).
- Callsign data: [callook.info](https://callook.info/),
  [HamQTH](https://www.hamqth.com/), [QRZ](https://www.qrz.com/), and the FCC
  ULS, depending on what you enable.

These are free services run by volunteers and public agencies. The collector
polls on conservative intervals and caps how often it asks; please do not lower
those without a reason.

## License

**MPL-2.0.** See [LICENSE](LICENSE).

Mozilla Public License 2.0 is weak, file-level copyleft: you can use this
alongside proprietary code and consumers are not affected, but improvements to
these files come back. It also matches
[Hammunition](https://github.com/ChiefGyk3D/Hammunition),
[SolarStorm Scout](https://github.com/ChiefGyk3D/solarstorm_scout), and
[Penguin Overlord](https://github.com/ChiefGyk3D/penguin-overlord), so logic can
move between the four projects by copy-paste — no per-file licence bookkeeping,
no mixed-licence explanation.

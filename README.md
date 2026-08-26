# Hammunition Hill

A ham radio dashboard that runs on your own machine, on your own network, and
talks to nobody you did not name.

Companion to [Hammunition](https://github.com/ChiefGyk3D/Hammunition), which
turns a Debian-family install into an amateur radio, SDR, and RF workstation.
Hammunition builds the shack computer; Hammunition Hill is what you put on the
monitor above it — the high ground you watch the bands from.

> **Status: v0.3, early but real.** Collector, server, ten panels, DX cluster,
> POTA/SOTA, contests, rig control, WSJT-X, and log-driven needed-slot colouring
> all work end to end. VOACAP and satellite passes are still ahead. See
> [the roadmap](#roadmap).

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

## Three tiers of trust

Every panel declares a tier, and the tier is visible in the UI. You should be
able to see at a glance which parts of your wall reach outside the house.

| Tier | What it is | Examples |
|---|---|---|
| **0 — offline** | Computed in the browser from data you already have. Works with the internet unplugged. | clocks, greyline, Maidenhead, bearing + distance, satellite passes, band plan |
| **1 — your host** | Fetched by the collector on a timer, served as same-origin JSON. No third-party code, no CORS, no leaked referrers. | DX spots, solar and space weather, POTA, SOTA, contests, weather alerts, RSS |
| **2 — foreign** | Content your browser loads from someone else. Off by default, allowlisted per host. | radar loops, lightning maps — and local gear like Pi-Star or OpenWebRX+ |

Two rules do most of the work inside tier 2. **Prefer `<img>` over `<iframe>`**:
a radar loop is a GIF, and an image element cannot run script, reach storage, or
navigate. And **opaque mode** (planned) has the collector fetch and cache remote
images itself, so the browser never contacts a third party at all and the CSP
tightens to `img-src 'self'`.

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
| **Solar & Space Weather** | 1 | SFI, A, K, sunspots, GOES X-ray class |
| **Band Conditions** | 1 | HamQSL HF conditions, day and night |
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
| **v0.2** | Spots | DX cluster telnet client, client-side filtering, spot detail with bearing and distance. POTA, SOTA, contest calendar. |
| **v0.3** | The differentiator | ADIF log ingest and needed-slot spot colouring. `rigctld` and WSJT-X UDP. |
| **v0.4** | Sky and weather | Satellite passes from cached TLEs, greyline map, local weather and alerts. |
| **v0.5** | Other people's shacks | LAN mode hardening, opaque image proxy, tier 2 allowlisting, systemd + Docker + Pi install docs. |
| **v1.0** | Community | VA3HDL `config.js` importer, panel SDK, example dashboards. |
| later | Deferred on purpose | WebSocket spot push, VOACAP. And only after all of that, any conversation about a hosted mode — which needs a real authn/authz model, TLS, rate limiting, and a threat model this version deliberately does not have. |

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
  NOAA space weather to Bluesky and Mastodon. It already ingests several of the
  same SWPC products; where the parsing converges, that logic is worth
  extracting into a shared library rather than maintaining two readings of the
  same feed.
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

## License

MIT. See [LICENSE](LICENSE).

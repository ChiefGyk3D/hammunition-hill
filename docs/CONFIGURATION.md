# Configuration reference

One TOML file. There is no settings API and no write endpoint — presentation
state (layout, filters, which licence class you picked) lives in your browser's
localStorage, and everything that touches the network lives here.

That split is why there is no CSRF surface and nothing to authenticate: no
request reaching the server can change any of it.

Validate any edit with `hamhill check`, which makes no network requests.

---

## `[server]`

| Key | Default | Meaning |
|---|---|---|
| `host` | `127.0.0.1` | Bind address. Anything but loopback prints the network warning at startup. |
| `port` | `8073` | TCP port. |

```toml
[server]
host = "127.0.0.1"
port = 8073
```

Overridden by `--listen HOST[:PORT]` on the command line. IPv6 needs brackets:
`--listen "[::1]:8073"`.

## `[station]`

Used for beam headings, distances, and the callsign panel. Never transmitted
anywhere — these numbers are used on this machine and in your browser.

| Key | Default | Meaning |
|---|---|---|
| `callsign` | — | Yours. Shown in the header. |
| `grid` | — | Maidenhead locator, 2/4/6/8 characters. |
| `lat`, `lon` | derived from `grid` | Decimal degrees, if you want more precision than a grid square. |

```toml
[station]
callsign = "N0CALL"
grid = "FN31pr"
```

Without a grid or coordinates, bearings and distances are omitted rather than
guessed. A malformed grid logs a warning and degrades the same way.

## `[log]`

| Key | Default | Meaning |
|---|---|---|
| `cty_dat` | unset | Path to AD1C's `cty.dat`. Without it, a compact built-in prefix table is used and reported as approximate. |

```toml
[log]
cty_dat = "~/.local/share/hammunition-hill/cty.dat"
```

Your ADIF log itself is configured as a source — see `kind = "adif"` below.

## `[paths]`

| Key | Default | Meaning |
|---|---|---|
| `data_dir` | `./data` | Where snapshots are written. |
| `web_dir` | `./web` | Where the dashboard is served from. |

## `[embeds]`

| Key | Default | Meaning |
|---|---|---|
| `allow_hosts` | `[]` | Tier 2 hosts your browser may load content from. |

```toml
[embeds]
allow_hosts = ["radar.weather.gov"]
```

Every host here is added to the page's Content-Security-Policy, in `img-src` and
`frame-src` only — never `script-src` or `connect-src`. Prefer images over
iframes: an image cannot run script.

**For a plain image, use `[[imagery]]` below instead.** It opens `img-src` only,
keeps the host out of `frame-src`, and gives you a labelled tile with a refresh
interval. `[embeds]` is for the case where you actually want to frame something.

Run `hamhill check` to see the exact policy your config produces.

---

## `[[imagery]]`

Tier 2 image tiles — radar, satellite, lightning, solar. **Empty by default.**
Full trade-off, including why these are not proxied through the collector, in
[IMAGERY.md](IMAGERY.md).

| Key | Default | Meaning |
|---|---|---|
| `id` | required | Unique, filename-safe. |
| `url` | required | **https only.** |
| `name` | the id | Tile label. |
| `group` | `general` | Filter chip. One group draws no filter row. |
| `refresh` | `600` | Seconds between reloads. 60s floor. |
| `credit` | `""` | Shown on the tile. |
| `link` | `""` | Optional http(s) source link. |
| `cache_bust` | `true` | Appends `?_hh=<epoch>`. Set false for a strict host. |

```toml
[[imagery]]
id = "radar-local"
name = "Local radar"
url = "https://radar.weather.gov/ridge/standard/KFTG_loop.gif"
group = "radar"
refresh = 300
credit = "NOAA/NWS"
```

Three things to know:

- **Your browser fetches these, not the collector.** The upstream sees each
  viewer's IP, User-Agent, and any cookie it has already set in that browser.
- **The CSP follows the tiles.** Do not also list the host under `[embeds]`.
  Imagery hosts reach `img-src` and nothing else, and are deliberately kept out
  of the collector's egress allowlist.
- **Restart after editing.** The CSP is built at startup.

`refresh` has a higher floor than a source `interval` because a tile is
re-requested by *every open dashboard*, not once by one collector.

---

## `[[sources]]`

Every source needs an `id` and a `kind`, plus **exactly one** of `url` or
`path`. The `id` becomes the snapshot filename, so it must be filename-safe —
and panels name the ids they read, so renaming one blanks its panel.

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Snapshot name. Alphanumeric plus `-` and `_`. |
| `kind` | yes | Which source type. See below. |
| `url` | one of | What to fetch or connect to. |
| `path` | one of | A local file to read. No network involved. |
| `interval` | no | Seconds between reads. Default 300, floor 30. |
| `local` | no | Declares this URL points at your own LAN. See below. |
| `options` | no | Per-kind settings. |

### The `local` flag

The egress guard refuses any host that resolves to a private, loopback,
link-local, or reserved address. That is what stops a mistyped or hijacked
upstream URL from being turned into a probe of your network.

Sources that legitimately point at your own LAN — rigctld, WSJT-X, a Pi-Star box
— opt back in explicitly:

```toml
local = true
```

It is deliberately not a wildcard. You are naming one host as intentional.

---

## Polled sources

Fetch a URL on a timer.

### `swpc` — NOAA Space Weather Prediction Center

`options.product` selects the normalizer: `planetary_k_index`, `f107_flux`, or
`xray_flux`.

```toml
[[sources]]
id = "kindex"
kind = "swpc"
url = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
interval = 900
options = { product = "planetary_k_index" }
```

### `hamqsl` — N0NBH solar XML

Drives both the Solar and Band Conditions panels. We read the XML rather than
the banner image, so the numbers are readable and themeable and your browser
makes one fewer third-party request.

```toml
[[sources]]
id = "hamqsl"
kind = "hamqsl"
url = "https://www.hamqsl.com/solarxml.php"
interval = 900
```

### `pota` / `sota` — park and summit activations

```toml
[[sources]]
id = "pota"
kind = "pota"
url = "https://api.pota.app/spot/activator"
interval = 120
```

SOTA publishes frequencies in MHz; they are normalized to kHz so every spot in
the system speaks one unit.

### `rss` — feeds

Parsed and sanitized by the collector, not by a third-party feed proxy. Markup
is stripped and non-`http(s)` links are dropped before anything is written.

```toml
[[sources]]
id = "amsat"
kind = "rss"
url = "https://www.amsat.org/feed/"
interval = 3600
```

### `ics` — iCalendar, for contest calendars

| Option | Default | Meaning |
|---|---|---|
| `label` | `Calendar` | Shown on the panel. |
| `horizon_days` | `21` | How far ahead to look. |

```toml
[[sources]]
id = "contests"
kind = "ics"
url = "https://example.org/contests.ics"
interval = 21600
options = { label = "Contests", horizon_days = 21 }
```

Kept generic rather than hardcoding one publisher — contest calendars move, and
you may follow a regional or club one.

### `nws_alerts` — US weather warnings

No options. **The filter lives in the URL**, and that is the only place it
lives: `?area=CO`, `?point=39.74,-104.98`, or `?zone=COZ040`.

```toml
[[sources]]
id = "wxalerts"
kind = "nws_alerts"
url = "https://api.weather.gov/alerts/active?area=CO"
interval = 300
```

`?point=` is usually what you want. A state-wide query in a big state returns
alerts for counties hours away, and during an outbreak they crowd out the one
that is over your tower.

It would be friendlier to write `options = { area = "CO" }` and assemble the
query in the source. It would also mean a source constructs a URL, and once one
does, "nothing the collector reads can change what it fetches next" stops being
a property of the architecture and becomes something you check per-source. See
[IMAGERY.md](IMAGERY.md) for the rest, including what happens outside the US.

---

## Stream sources

Hold a connection open instead of polling. All three are one-directional: they
*emit*, and nothing they receive can change what the collector fetches.

### `dxcluster`

| Option | Default | Meaning |
|---|---|---|
| `callsign` | **required** | Login. Clusters do not accept anonymous connections. |
| `commands` | `[]` | Setup commands sent after login. |
| `flush_seconds` | `5` | How often to write a snapshot. |

```toml
[[sources]]
id = "cluster"
kind = "dxcluster"
url = "telnet://dxc.nc7j.com:7373"
options = { callsign = "N0CALL", commands = ["set/ft8"] }
```

Only your configured callsign and commands are ever sent. Nothing is built from
what the cluster sends back.

### `wsjtx`

Enable WSJT-X → Settings → Reporting → UDP Server first.

```toml
[[sources]]
id = "wsjtx"
kind = "wsjtx"
url = "udp://127.0.0.1:2237"
local = true
options = { flush_seconds = 5 }
```

Listen-only: the socket is bound and never written to. If the port is already
taken by GridTracker or JTAlert, this source retries with backoff and everything
else keeps running.

### `rigctl`

| Option | Default | Meaning |
|---|---|---|
| `poll_seconds` | `1.0` | How often to ask the rig. Floor 0.2. |

```toml
[[sources]]
id = "rig"
kind = "rigctl"
url = "tcp://127.0.0.1:4532"
local = true
options = { poll_seconds = 1.0 }
```

Read-only, structurally: two get commands, no set path, and a test that fails if
one is ever added.

---

## File sources

Read local disk. No URL, no network, no egress check — there is nothing to
check.

### `adif` — your log

```toml
[[sources]]
id = "log"
kind = "adif"
path = "~/logs/mylog.adi"
interval = 300
```

Re-read in full each cycle rather than tailed: logging programs rewrite,
reorder, and back-fill, and an incremental reader would drift out of sync in
ways invisible until a spot is coloured wrong. A 50,000-QSO log parses in well
under a second.

---

## Command line

```
hamhill [-c CONFIG] [-l HOST[:PORT]] [-v] [serve|check]
```

| | |
|---|---|
| `serve` | Run the collector and the server. The default. |
| `check` | Validate config and egress policy. Makes no network requests. |
| `-c`, `--config` | Config path. Default `config.toml`. |
| `-l`, `--listen` | Override the bind address. |
| `-v`, `--verbose` | Debug logging. |

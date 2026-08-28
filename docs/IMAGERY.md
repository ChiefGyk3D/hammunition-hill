# Imagery and weather

Two features that arrived together because they answer the same question — what
is happening at the antenna rather than in the ionosphere — but they sit on
opposite sides of the trust boundary, and the difference is the point.

| | Weather alerts | Imagery |
|---|---|---|
| Who fetches | the collector, on a timer | **each viewer's browser** |
| Upstream sees | this one machine | every viewer's IP |
| Works WAN-down | last snapshot stands | blank tiles |
| Tier | 1 | **2** |

---

## Weather alerts (tier 1)

Active NWS watches, warnings and advisories, fetched by the collector like every
other source and served to the browser as a local file.

```toml
[[sources]]
id = "wxalerts"
kind = "nws_alerts"
url = "https://api.weather.gov/alerts/active?area=CO"
interval = 300
```

No key, no account. The panel id `wxalerts` in `web/panels/index.json` expects
the snapshot id `wxalerts`, so keep that id unless you are editing both.

### Picking your filter

The filter goes in the URL, and that is the only place it lives. Choose one:

| Form | Example | Use when |
|---|---|---|
| `?area=XX` | `?area=CO` | You want a whole state or marine area. |
| `?point=lat,lon` | `?point=39.74,-104.98` | You want your QTH and nothing else. Most precise. |
| `?zone=ZZZNNN` | `?zone=COZ040` | You know your NWS forecast zone. |

`?point=` is usually what a station operator wants: a state-wide query in a big
state returns alerts for counties four hours away, and during an outbreak they
crowd out the one that is over your tower.

**Why the URL and not an option.** It would be friendlier to write
`options = { area = "CO" }` and let the source assemble the query. It would also
mean the source constructs a URL, and once one source does that the rule that
makes this whole design defensible — *nothing the collector reads can change
what it fetches next* — becomes a thing you have to check per-source instead of
a property of the architecture. The convenience is not worth the audit.

### How alerts are presented

Sorted worst-and-soonest-first, and **sorted on NWS's five severity levels, not
on the three colours**. Extreme and Severe both paint red, because the status
ramp has three steps and both of them mean red. Sorting on that collapsed value
put a Severe Thunderstorm Warning above a Tornado Warning — same colour, same
urgency, tie broken alphabetically. On a panel showing the first six of many
during an outbreak, that is the tornado warning below the fold. Colour
collapses; order does not.

An unrecognised severity — a category NWS adds after this was written — sorts as
if it were Severe and colours amber. Unknown means "we do not know", which
belongs near the top where somebody will notice it, not quietly at the bottom.

Minor and Unknown alerts colour green. That reads oddly for something called an
alert and it is deliberate: the ramp is about how much attention this needs
right now, and a small craft advisory is not a tornado warning. Painting them
alike would make the ramp mean nothing on the day it matters.

An empty result is a result. The panel says "No active alerts" with a
timestamp, because that is a different statement from a blank panel, and on a
summer afternoon it is worth making.

### Outside the US

`api.weather.gov` is US-only. For Europe, MeteoAlarm publishes per-country
Atom feeds that the generic `rss` source reads today, and an awareness map that
works as an imagery tile:

```toml
[[sources]]
id = "meteoalarm"
kind = "rss"
url = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-france"
interval = 900
```

That gives you headlines in the news feed panel, not structured severity in the
alerts panel — MeteoAlarm's severity lives in CAP fields the generic RSS parser
does not read. A proper `meteoalarm` source is open work, listed in
`docs/PARITY.md`.

---

## Imagery (tier 2)

Radar, satellite and lightning pictures, loaded by your browser directly from
the upstream. **Empty by default.** Read this section before filling it in.

### The cost

Every other panel is fed by the collector: one machine fetches on a schedule and
every viewer reads the same local file. Imagery is the exception. Your browser
fetches these, on every dashboard that shows them, which means the upstream
sees:

- **your IP address** — every viewer's, not the collector's. On a shared shack
  display that is each person who opens it;
- **your User-Agent**, and anything else your browser sends;
- **any cookie that host has already set in your browser.** An `<img>` is not a
  CORS request, so it carries credentials for that origin. If you have visited
  the site, the tile is not anonymous.

With the WAN down, tiles go blank while every tier 0 and tier 1 panel keeps
working from its last snapshot.

### Opaque mode: the collector fetches it instead

```toml
[[imagery]]
id = "goes-east"
name = "GOES East full disc"
url = "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/FD/GEOCOLOR/678x678.jpg"
mode = "opaque"
refresh = 600
credit = "NOAA/NESDIS"
```

`mode = "opaque"` folds a tile back into the architecture: the collector
fetches it on `refresh`, writes it atomically under `data/tiles/`, and the
browser loads it same-origin. The upstream sees one machine on a timer instead
of every viewer on every dashboard load — no viewer IPs, no cookies, no
User-Agents — and the host leaves the CSP entirely, joining the collector's
egress allowlist instead. One collector polling a tile every ten minutes is
also strictly *fewer* upstream requests than five wall displays fetching it
themselves, so it is kinder to the upstream too.

The discipline that let this ship, per the concern that kept it unshipped:

- **The payload is identified by its own bytes.** PNG, JPEG, GIF and WebP magic
  numbers — never the upstream's `Content-Type` header, which is exactly the
  thing an evil or broken upstream controls. An upstream that serves SVG — a
  document that can run script, which on our origin the CSP would trust — is
  refused by name, and the last good raster stays on disk with an honest error
  beside it.
- **A 10 MB cap, enforced while the body streams in** — a cap checked after
  the download is a description, not a limit.
- **A failure keeps the last good image.** A stale radar frame with an honest
  timestamp beats a broken-image icon; the same trade every JSON snapshot makes.

Which mode for which tile: a fast-moving radar loop that updates every two
minutes is a reasonable tier 2 tile — the collector cannot usefully cache it
faster than you watch it. A satellite disc that updates every ten minutes has
no business being fetched by every viewer. Opaque tiles cost collector
bandwidth whether or not a dashboard is open, which is why the mode is chosen
per tile rather than globally: a metered field link can leave the heavy tiles
direct, or absent.

### Configuring tiles

```toml
[[imagery]]
id = "radar-local"
name = "Local radar"
url = "https://radar.weather.gov/ridge/standard/KFTG_loop.gif"
group = "radar"
refresh = 300
credit = "NOAA/NWS"
```

| Key | Meaning |
|---|---|
| `id` | Unique, filename-safe. |
| `url` | **https only.** An `http` tile is blocked as mixed content and leaks in cleartext besides. |
| `name` | The tile's label. |
| `group` | Filter chip it appears under. One group means no filter row is drawn. |
| `refresh` | Seconds between reloads. 60s floor. |
| `credit` | Shown on the tile. Please fill this in. |
| `link` | Optional http(s) source link. |
| `cache_bust` | Adds `?_hh=<epoch>` so you get the new image rather than the cached one. Default true; set false for a host that rejects unknown parameters. |

`refresh` has a higher floor than a source `interval` for a reason: a source is
polled once by one collector, but a tile is re-requested by *every open
dashboard*. Five wall displays on a 60s tile is five requests a minute to a
government server that is giving you this for free. Be generous.

### The CSP follows the tiles

Imagery hosts are added to `img-src` automatically. You do **not** also list
them under `[embeds] allow_hosts`. Adding a radar used to mean editing two
places and forgetting the second gave you a blank square and a console message
nobody reads; now the tile is the single declaration and the policy is derived
from it.

Two things imagery hosts deliberately do *not* get:

- **`frame-src`.** An image cannot run script; a frame from the same host can.
  Granting a radar server the right to be framed because you wanted a picture
  from it would hand out a capability nobody asked for. If you genuinely want a
  frame, that is what `[embeds] allow_hosts` is for, and it is a bigger decision.
- **The collector's egress allowlist.** The collector has no business reaching
  these, so it cannot. The two lists look almost identical and the smaller one
  is smaller on purpose.

**Restart after editing.** The CSP is built at startup.

### When a tile does not load

The tile says so, in place of the image, and names the two things to check.
Upstream image endpoints get renamed without notice — the URLs in
`config.example.toml` were correct when written and will rot. Open the tile's
URL in a browser: that tells you in one step whether the problem is the URL or
your network. Find your local radar's four-letter site ID at
<https://radar.weather.gov>.

Clicking a tile reloads that one tile immediately, for watching a storm come in
without waiting out the interval.

# Writing a panel

A panel is a directory under `web/panels/` with two files.

```
web/panels/solar/
├── panel.json    manifest
└── panel.js      ES module exporting render()
```

Add its id to a dashboard's `panels` list in `web/panels/index.json` to enable
it. A dashboard is an id, a name, and a list of panel ids; a panel may appear on
more than one.

## Manifest

```json
{
  "id": "solar",
  "name": "Solar & Space Weather",
  "tier": 1,
  "sources": ["hamqsl", "kindex", "solarflux", "xray"],
  "embed_hosts": [],
  "description": "SFI, A, K, sunspots and GOES X-ray class from HamQSL and NOAA SWPC."
}
```

| Field | Meaning |
|---|---|
| `id` | Must match the directory name. |
| `name` | Shown in the panel header. |
| `tier` | 0, 1, or 2. Rendered as a badge — see below. |
| `sources` | Snapshot ids this panel reads. Drives the freshness indicator. |
| `embed_hosts` | Tier 2 hosts the panel needs. **Documentation, not policy** — see below. |
| `span` | Optional. Grid columns to occupy, capped at 3. Wide tables want 2. |

**The `sources` list names snapshot ids, which are source ids from
`config.toml`.** That is a real coupling: rename a source in your config and the
panel that reads it goes blank. Panels shipped with the project use the ids in
`config.example.toml`, so keep those unless you are prepared to edit both.

**Declare the tier honestly.** It is shown in the UI so an operator can see at a
glance which parts of their wall reach outside the house. A panel that loads a
remote image is tier 2 even if everything else about it is local.

**`embed_hosts` in a manifest grants nothing.** Nothing reads it — it documents
what the panel expects so somebody reading the directory can see it. The CSP is
built entirely from the operator's `config.toml`: `[embeds] allow_hosts` and the
hosts of `[[imagery]]` tiles. A panel cannot widen the policy by asking, which
is the right way round — a panel is code you may have copied from someone else.

If you are writing a panel that shows external images, prefer reading the
`imagery` snapshot over hardcoding URLs. The operator then controls the list,
the CSP follows from it automatically, and your panel needs no host of its own.

The test is **where the data came from**, not whether a file was involved.

- **Tier 0** — nothing in the panel originated off this machine. Computed in the
  browser, or read from something local: the station config, the prefix table,
  the operator's own log, a band plan shipped with the dashboard. Works with the
  internet unplugged.
- **Tier 1** — reads a snapshot the collector fetched from somewhere else.
  Same-origin by the time the browser sees it, but the data came from upstream.
- **Tier 2** — the browser loads content from another host. The operator has to
  allowlist those hosts in their own config; the manifest field does not do it.

So a panel reading `station.json` or `log.json` is still tier 0: those files are
written from this machine's own config and disk. A panel reading `hamqsl.json`
is tier 1, because NOAA and N0NBH are upstream. The badge answers "does this
panel depend on the outside world", which is what an operator wants to know when
the WAN drops.

## The module

```js
export function render(root, { data, station, el }) { }
```

| Argument | What it is |
|---|---|
| `root` | Your panel body element. Replace its children; do not touch anything outside it. |
| `data` | `{ sourceId: snapshot \| null }` for every id in your manifest. |
| `station` | `{ callsign, grid }` from config. Never leaves the browser. |
| `el` | `el(tag, className?, text?)` — sets `textContent`, never `innerHTML`. |

`render` is called on every poll, and once a second for tier 0 panels. Make it
idempotent and cheap: build your nodes and call `root.replaceChildren(...)`.

A snapshot looks like:

```js
{
  fetched_at: "2026-08-26T20:43:23Z",
  stale_after_seconds: 1800,
  error: null,        // a string if the last fetch failed
  data: { }           // whatever the source produced
}
```

`stale_after_seconds: 0` means **this does not age**, not "already stale". Some
snapshots are published config rather than fetched data — the tile list, the
prefix table, the station — and their timestamp is when the collector started,
which is not a freshness claim about anything. The host shows no age at all for
those, because there is nothing there to be stale.

The host computes the freshness badge from `fetched_at` and `error` across all
your declared sources. You do not need to render staleness yourself — but do
handle `data` being `null` before the first successful cycle:

```js
if (!data.hamqsl?.data) {
  root.replaceChildren(el("p", "empty", "waiting for the first collector cycle…"));
  return;
}
```

## Rules

**Never use `innerHTML`.** Use the `el` helper or `textContent`. Snapshot
content originates upstream; the collector sanitizes it, and this is the second
layer.

**Never fetch off-origin.** If your panel needs data from the network, it needs
a collector source. The CSP sets `connect-src 'self'`, so an off-origin fetch
fails anyway — but the reason it is a rule is that request-driven fetching is
exactly the property this architecture exists to avoid.

Fetching a **static asset that ships with the dashboard** is fine, and is how
the band plan panel loads `web/bandplans/*.json`. It is same-origin, it is on
disk before the collector ever runs, and it works with the WAN down. Load it
once and keep it — tier 0 panels re-render every second, and refetching on each
tick would be pointless churn.

**Prefer `<img>` to `<iframe>`.** An image cannot run script, reach storage, or
navigate. Most tier 2 content — radar loops, lightning maps, satellite imagery —
is an image already.

**Fail inside your own frame.** A throw from `render` is caught and shown in
your panel. Do not take the dashboard down over one bad field.

## Shared helpers

`web/lib/format.js` carries the pieces most panels need:

| | |
|---|---|
| `khz(value)` | Frequency with a thousands separator |
| `distance(path)` | km or miles, following the viewer's remembered preference |
| `relativeAge(iso)` | "4m", "2h" |
| `neededClass(needed)` | Which needed-badge a spot earns, if any |
| `filterRow(el, {...})` | A row of toggle chips that persists its own selection |
| `remember(key, value)` / `recall(key, fallback)` | Per-viewer state in localStorage |

`remember` and `recall` both swallow their own errors. Private windows and
browsers set to block site data throw on access, and a forgotten filter is not
worth breaking a panel over.

Needed-slot precedence is deliberate and worth keeping consistent: **new entity
outranks a band slot, which outranks a mode slot.** An operator chasing DXCC
drops everything for the first and merely notices the third.

## Reference data

Data that ships with the dashboard rather than arriving from a source lives in
its own directory under `web/`, not inside a panel. The band plans are the
worked example: `web/bandplans/` holds `index.json` plus one file per country,
and `tests/test_bandplan.py` validates every file's structure — segments inside
their band, classes that actually exist, band names that match `bands.py`.

That split is what makes the data safe to hand-edit. Correcting a band edge
should be a one-line change to JSON with a test that catches a mistake, not a
Python edit. Adding another country is a new file plus a line in `index.json`.

## Styling

Use the CSS custom properties in `web/style.css` — `--panel`, `--rule`,
`--accent`, `--good`, `--fair`, `--poor` — rather than literal colours, so
panels stay a consistent instrument panel rather than a collection of styles.

The shared classes `.readouts` / `.readout`, `table.bands`, and `ul.feed` cover
most of what a panel needs. Reach for them before writing new CSS.

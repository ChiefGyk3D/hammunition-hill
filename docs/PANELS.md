# Writing a panel

A panel is a directory under `web/panels/` with two files.

```
web/panels/solar/
├── panel.json    manifest
└── panel.js      ES module exporting render()
```

Add its id to `web/panels/index.json` to enable it.

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
| `embed_hosts` | Tier 2 hosts. These reach the CSP; nothing else does. |

**Declare the tier honestly.** It is shown in the UI so an operator can see at a
glance which parts of their wall reach outside the house. A panel that loads a
remote image is tier 2 even if everything else about it is local.

- **Tier 0** — computed in the browser. No snapshots, no network. Works with the
  internet unplugged.
- **Tier 1** — reads snapshots the collector wrote. Same-origin only.
- **Tier 2** — loads content from another host. Needs `embed_hosts`, and the
  operator has to allowlist those hosts in their config too.

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

**Never fetch anything yourself.** If your panel needs data, it needs a
collector source. The CSP sets `connect-src 'self'`, so an off-origin fetch will
fail anyway — but the reason it is a rule is that request-driven fetching is
exactly the property this architecture exists to avoid.

**Prefer `<img>` to `<iframe>`.** An image cannot run script, reach storage, or
navigate. Most tier 2 content — radar loops, lightning maps, satellite imagery —
is an image already.

**Fail inside your own frame.** A throw from `render` is caught and shown in
your panel. Do not take the dashboard down over one bad field.

## Styling

Use the CSS custom properties in `web/style.css` — `--panel`, `--rule`,
`--accent`, `--good`, `--fair`, `--poor` — rather than literal colours, so
panels stay a consistent instrument panel rather than a collection of styles.

The shared classes `.readouts` / `.readout`, `table.bands`, and `ul.feed` cover
most of what a panel needs. Reach for them before writing new CSS.

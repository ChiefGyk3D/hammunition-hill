# Architecture

## The problem

A ham dashboard wants DX cluster spots (telnet), propagation and space weather
(APIs with no CORS headers), POTA and SOTA activations, contest calendars, and
satellite passes. None of that is reachable from a static page. The usual answer
is a web application with an API in front of a database, which is a large,
long-lived attack surface to put on a shack computer for the sake of showing
somebody a K-index.

## The move

**The server does its work on a timer, not on a request.**

Two halves in one process, connected only by the filesystem:

```
                    hamdashd
  ┌───────────────────────────────────────────────┐
  │                                               │
  │   collector  ──writes──►  data/*.json         │
  │   fixed schedule            ▲                 │
  │   host allowlist            │ reads           │
  │   atomic writes             │                 │
  │                        static file server     │
  │                                               │
  └───────────────────────────────────────────────┘
        ▲                                  │
        │ polls, on a timer                │ GET, same-origin
        │                                  ▼
    upstream                            browser
```

The collector never sees an HTTP request. The server never makes an outbound
connection. There is no function call between them — only files.

### What that buys

**No request-driven fetching.** The schedule and the allowlist are fixed when
the config file loads, so nothing an attacker sends can influence what gets
fetched or from where. This is the property everything else rests on.

**No input parsing on the server.** No query strings, no request bodies, no
content negotiation beyond what a static file server does. Filtering that other
dashboards do server-side — band, mode, continent — happens in the browser, over
the array it already has.

**No third-party JavaScript.** Everything the page loads comes from your host.
Fonts and styles are vendored. Feeds are parsed by the collector rather than by
a feed-proxy service that would otherwise receive your entire reading list.

**Honest degradation.** Snapshots carry `fetched_at` and `stale_after_seconds`.
When a fetch fails, the collector rewrites the snapshot with the *last good
data*, the *original* timestamp, and an `error` field. A panel can then say "20
minutes old, last fetch failed" instead of going blank or showing yesterday's
numbers as if they were current. With the WAN down that is the difference
between a useful degraded dashboard and a misleading one.

### What it costs

**Latency floor.** A spot appears when the next poll runs, not the instant it
hits the cluster. For solar data on a fifteen-minute cycle nobody notices; for
DX spots it is the reason WebSocket push is on the roadmap. Note that push can
be added *without* giving up the property above — a WebSocket that only ever
emits, and never accepts a message that changes collector behaviour, keeps the
one-directional shape intact.

**No per-viewer state.** Two browsers pointed at the same instance see the same
snapshots. Layout and filters are per-browser via localStorage; anything that
would need shared server-side state is out of scope until there is a reason and
a threat model for it.

## Three kinds of source

Everything writes the same snapshot files. What differs is where the data comes
from and what drives the clock.

| | Driven by | Examples |
|---|---|---|
| **Polled** | An interval | SWPC, HamQSL, POTA, SOTA, RSS, iCalendar |
| **Stream** | A socket that stays open | DX cluster (telnet), WSJT-X (UDP), rigctld (TCP) |
| **File** | An interval, reading local disk | the ADIF log |

Streams flush a snapshot on a timer rather than per event. A busy cluster
produces several spots a second; rewriting a file that often would be churn when
the browser only polls every ten seconds.

File sources run in a thread. A large ADIF log is a blocking read and a blocking
parse, and blocking the event loop would stall every other source behind it.

Adding streams did not widen the security posture, because they are
one-directional: a stream emits, and nothing it receives can influence what the
collector fetches or from where. That is the same property the polled sources
have.

## Enrichment

A raw cluster line is a callsign and a frequency. What an operator wants to know
is *where is that, which way do I point, and do I need it?* Those three answers
are joined in `enrich.py`, at flush time:

```
cluster line ──┐
               ├─► prefix table  ──► entity, continent, coordinates
station grid ──┤
               ├─► geo           ──► short/long path bearing, distance
ADIF log ──────┤
               └─► log index     ──► new entity / new band / new mode
```

Enrichment happens at flush rather than at ingest, so a log reload is picked up
by the next flush without the stream knowing anything about the log. The index is
swapped in wholesale, so a reload never leaves half-updated state behind a
render.

**Entities are resolved by running the logged callsign through the same prefix
table the spots use** -- not the log's own DXCC or COUNTRY field. Those are often
absent and sometimes disagree between logging programs, and using them would give
"needed" a different notion of entity than the spot has. Consistency matters more
than authority: if the prefix table is wrong about an entity, it is wrong the
same way on both sides and the comparison still holds.

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Parse and validate TOML. Every error message says how to fix it. |
| `egress.py` | The allowlist and the private-address guard. Security core. |
| `snapshot.py` | The on-disk format and atomic writes. |
| `collector.py` | One async task per source: polled, stream, or file. |
| `server.py` | Static files over two directories, with the headers turned up. |
| `enrich.py` | Joins spots to entity, path, and the log index. |
| `geo.py` | Maidenhead, great-circle bearing, distance. |
| `bands.py` | Band plan and mode inference. |
| `prefix.py` | cty.dat, with a compact built-in fallback. |
| `adif.py` | Log parsing and the worked/needed index. |
| `sources/` | Polled and file sources, registered statically. |
| `streams/` | Long-lived connections, registered statically. |
| `cli.py` | `hamhill serve` and `hamhill check`. |

### Snapshot format

```json
{
  "schema": 1,
  "source": "hamqsl",
  "kind": "hamqsl",
  "fetched_at": "2026-08-26T20:43:23Z",
  "stale_after_seconds": 1800,
  "error": null,
  "data": { }
}
```

Writes go to a temp file in the same directory and are moved into place with
`os.replace`, which is atomic on POSIX and Windows. A browser polling every ten
seconds will never read a half-written file.

`data` is serialized with sorted keys so snapshots diff cleanly between runs.
**That has a consequence worth knowing:** anything whose order is meaningful must
be a list, not an object. HF band conditions are a list of
`{band, day, night}` for exactly this reason — as a mapping they came back out
alphabetically, putting 12m-10m above 80m-40m, which is not how anyone reads a
band table.

### Adding a source

1. Write a class in `sources/` with a `kind` attribute and an async `fetch`.
2. Register it in `sources/__init__.py`. The registry is static on purpose — a
   config file must not be able to make the collector import arbitrary code.
3. Normalize down to the fields a panel actually renders. Do not pass a
   multi-megabyte time series to the browser because it happened to be in the
   response.
4. Add tests with `httpx.MockTransport`. No test should touch the network.

## Frontend

No build step. ES modules, served as written. The whole claim is auditability —
an operator should be able to read the source their own machine is serving
without reconstructing a bundler pipeline first.

`app.js` loads the panel list, imports each panel module, polls the snapshots,
and hands each panel its data. Panels render into a container they do not own,
using `textContent` rather than `innerHTML`. A panel that throws is caught and
shows an error in its own frame instead of taking the dashboard down.

Tier 0 panels re-render on a one-second tick independent of any fetch, which is
why the clock keeps working when nothing else does.

## Why Python

The original sketch called for a single static Go binary, on the grounds that
"download one file and run it" is the difference between a project hams use and
one they bookmark.

Two things changed that. **Hammunition already solves deployment** — it
provisions the workstation this runs on, it is Python, and it can install this as
one more role. And **solarstorm_scout already ingests several of these SWPC
products**, which is a meaningful slice of the collector already written and
debugged.

Go comes back onto the table if Pi performance bites or if install friction for
non-Hammunition users turns out to matter more than expected. A Docker image
covers most of that gap first.

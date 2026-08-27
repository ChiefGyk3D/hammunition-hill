# Callsign lookup

Resolving a callsign to an entity and a beam heading is easy and already works
offline. Resolving one to a **name and address** is the hard part, and it runs
straight into the property the rest of this project is built on.

This is the analysis, the options, and what you can turn on.

## The architectural problem, stated plainly

The collector fetches on a fixed schedule. Nothing it does is triggered by a
request, which is why the HTTP server can be "read bytes from disk, send bytes"
with no input parsing, no authentication, and no CSRF surface.

An arbitrary on-demand lookup — you type `JA1XYZ`, something goes and finds out
who that is — breaks that by definition. There are exactly three ways to get it,
and there is no fourth:

| | What it costs |
|---|---|
| **An HTTP endpoint that takes a callsign** | The server starts parsing input. A request can now cause work. |
| **The browser calling a service directly** | Widens `connect-src`, leaks every callsign you look at to a third party, and most of these APIs send no CORS headers, so it does not even work. |
| **Resolving ahead of time, on a schedule** | Bounded and keeps the property. Covers "who is this station I am seeing". Does not cover "look up any call I can think of". |

The third is free. The first two are real trade-offs, so they are opt-in and off
by default — but they *are* available, because it is your machine.

## What you get with nothing enabled

The default, and it is more than nothing:

- DXCC entity, continent, CQ zone
- Short and long path beam headings, distance
- Whether you have worked that entity, and whether it is confirmed
- For US calls, a licence class guess from callsign format

All of it resolved in your browser against the prefix table, instantly, with no
network and no third party. The callsign never leaves the machine.

What it cannot give you is a name, an address, a grid square, or a licence
expiry. Those need a data source that knows about people rather than prefixes.

## The providers

### FCC ULS bulk download — the best fit

The FCC publishes the complete US amateur licence database as a download,
rebuilt early Sunday morning:

```
https://data.fcc.gov/download/pub/uls/complete/l_amat.zip
```

Roughly 160 MB zipped, pipe-delimited files inside. `HD.dat` carries the
licence status, `EN.dat` the name and address, `AM.dat` the operator class. All
three carry the callsign, so the importer keys on that directly rather than
joining on the system identifier — one less thing to get wrong, and a malformed
`AM` line costs one licence its operator class instead of breaking a join.

This is the one option with **no per-lookup network at all**. It is a scheduled
fetch of one known URL — exactly what the collector already does — and every
lookup afterwards reads a local index. No account, no rate limit, no third party
watching what you look up, authoritative, and it includes the operator class, so
the licence-class guess in the Band Plan panel becomes a fact for US calls.

The costs are honest ones: a 160 MB download and about 100 MB of database on
disk, which is real on a Raspberry Pi with an SD card, and it is **US only** —
which is why it belongs in a chain rather than on its own. See *Setting up the
offline index* below.

### Callook.info — free, no account, US only

`https://callook.info/{callsign}/json`. No registration, no key, clean JSON,
current FCC data including grid square. The simplest real provider there is.

Costs: one request per callsign to a third party, and US only.

### HamQTH — free, worldwide, needs an account

Session-based XML: authenticate with your HamQTH username and password, get a
session key, query with it. Worldwide coverage, free.

Costs: an account, credentials in your config file, and a request per lookup.

### QRZ.com — best data, paid

Session-based XML like HamQTH. Requires an XML Logbook Data subscription or QRZ
Premium. The most complete data of any option.

Costs: money, an account, credentials, and a request per lookup.

### QRZCQ — paid

Account plus premium subscription. Listed for completeness.

## How this project uses them

### Mode 1 — `none` (default)

Prefix table only. Everything in "what you get with nothing enabled" above.

### Mode 2 — scheduled resolution

The collector resolves callsigns **that already appear in your data** — cluster
spots, WSJT-X decodes — on its normal schedule, and publishes the results as a
snapshot. Lookups in the panel are served from that.

This keeps the architecture intact: the schedule is still fixed, the work is
still bounded, and no request causes a fetch. It covers the question people
actually ask a dashboard, which is "who is this station I am looking at" rather
than "tell me about an arbitrary callsign".

Be aware of what it means with a network provider: **the callsigns you are
watching go to that provider.** With a cluster feed running, that is a
continuous picture of what you can hear. With `fcc_uls` it stays on your
machine.

Resolution is capped and cached so a busy cluster cannot turn into thousands of
requests, and providers with rate limits are respected.

### Mode 3 — the query endpoint, opt-in

If you want to type any callsign and get an answer, that needs an endpoint. One
exists, and it is off by default:

```toml
[lookup]
query_endpoint = true
```

It is deliberately the narrowest endpoint that can do the job:

- **`GET /lookup/<callsign>` only.** No other method, no body, no query string.
- **Reads the local index only.** It cannot cause an outbound request, so a
  request still cannot make the collector fetch anything. That property survives.
- **Strict validation.** Callsign charset and length, nothing else accepted.
- **Rate limited**, so it cannot be used to hammer anything.
- **Read-only**, like the rest of the server.

It is still an endpoint that accepts input, and that is a genuine change to the
attack surface — which is why it is a choice you make rather than a default.
Combined with `fcc_uls` it is a good one: local data, local index, no third
party, and the endpoint cannot reach the network.

## Chains, and operating away from the internet

No single provider is right for every callsign, so `providers` is an **ordered
chain** rather than one choice:

```toml
[lookup]
providers = ["fcc_uls", "qrz"]
```

Each callsign walks the list. A provider that answers wins. A provider that says
*not on file* falls through to the next. A provider that *errors* also falls
through, and — importantly — a callsign that every provider errored on is **not**
cached as a miss, because "we could not ask" and "nobody has heard of them" are
different facts and only one is worth remembering.

The singular `provider = "callook"` still works and means a chain of one. Setting
both forms is refused rather than guessed at.

### Why local-first is usually the right order

Putting the offline FCC index first looks backwards if you think of it as a
fallback. It is not a fallback; it is the fast path:

- It answers US callsigns **instantly, from disk, with no network at all**.
- It **declines every non-US callsign for free**, so the paid provider behind it
  only ever sees the calls it is actually needed for — fewer requests against
  your QRZ subscription, and fewer callsigns handed to a third party.
- It is **authoritative for operator class**, which no other free source is.

QRZ behind it covers the rest of the world and the richer fields. That ordering
gets you the best of both without thinking about it.

If you would rather have QRZ's data preferred for US calls too, put it first —
`providers = ["qrz", "fcc_uls"]` — and the index becomes the reserve it sounds
like. Both orders are supported; the first is what the example config ships.

### When the network goes

At a park, on a summit, in a field — for a portable station, no internet is the
normal condition rather than an exception. Two things happen automatically:

**Network providers stop being waited on.** After two consecutive network
failures the collector concludes the WAN is gone and skips them for five
minutes, then tries again. Without this, a cycle with twenty new callsigns
spends the connect timeout on each one in sequence, and a dashboard that should
have answered instantly from a local index does nothing for minutes. Offline
providers are untouched.

**The cache keeps answering, honestly.** Cached results expire after 30 days for
the purpose of *refetching*, but an expired entry is still published — flagged
`stale` with its age, so the panel can show it as known-but-old. A licence record
from five weeks ago is almost certainly still correct and is unarguably better
than a blank panel. A night of resolution at home still answers for those
callsigns in a field a month later.

Set `serve_stale = false` if you would rather see nothing than something
possibly out of date.

## Setting up the offline index

`fcc_uls` needs a one-off import before it can answer anything:

```
hamhill fcc-import                      # downloads ~160 MB from the FCC
hamhill fcc-import --file l_amat.zip    # if you already have the file
```

It is a deliberate command, not a scheduled source: a 160 MB fetch should not
happen unattended on a metered hotspot, which is exactly the connection a
portable station tends to have. The FCC rebuilds the file weekly; re-running
monthly is plenty.

The importer prints what it read — records per file, callsigns indexed, lines
skipped — because it parses a positional format and a parser like that should
show its working. If the indexed count is zero it exits non-zero and says so
rather than leaving an empty database that silently resolves nothing.

`hamhill check` then reports the index:

```
lookup       : fcc_uls -> qrz
  fcc_uls    : 812441 callsigns, imported 2026-08-27T01:20:09Z  (offline, no network)
```

**Costs, honestly:** roughly 100 MB of database on disk, a minute of import, and
about 4 MB of RAM while it runs — the import streams rather than buffering, so
peak memory does not grow with the size of the database and a Pi can do this.
It is US only, which is why it belongs in a chain.

**What is deliberately not stored:** the ULS file carries a street address for
every licensee in the country. The index keeps city and state and discards the
rest. A wall display does not need somebody's house number, and anything that
reaches a snapshot is readable by everyone on your LAN.

## Choosing

| You want | Set |
|---|---|
| Nothing extra, maximum privacy | `providers = []` (default) |
| Full US data, nothing leaves the machine | `providers = ["fcc_uls"]` |
| US offline, worldwide when online | `providers = ["fcc_uls", "qrz"]` |
| US data, no account, no big download | `providers = ["callook"]` |
| Worldwide, free, willing to have an account | `providers = ["hamqth"]` |
| Worldwide, best data, willing to pay | `providers = ["qrz"]` |

Add `query_endpoint = true` to any of them to look up arbitrary callsigns rather
than only ones you have seen.

## Credentials

`hamqth` and `qrz` need a username and password. They go in the config file, so:

- Keep `config.toml` readable only by the user running the collector
  (`chmod 600`).
- Credentials are used to obtain a session key and are never written to a
  snapshot, never logged, and never sent to the browser.
- If you would rather not have them on disk at all, `fcc_uls` and `callook` need
  no account.

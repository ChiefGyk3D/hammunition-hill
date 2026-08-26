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

Roughly 160 MB zipped, pipe-delimited files inside. `EN.dat` carries name and
address, `AM.dat` the operator class, `HD.dat` the licence status, joined on a
system identifier.

This is the one option with **no per-lookup network at all**. It is a scheduled
fetch of one known URL — exactly what the collector already does — and every
lookup afterwards reads a local index. No account, no rate limit, no third party
watching what you look up, authoritative, and it includes the operator class, so
the licence-class guess in the Band Plan panel becomes a fact for US calls.

The costs are honest ones: a 160 MB weekly download and a few hundred MB on
disk, which is real on a Raspberry Pi with an SD card, and it is **US only**.

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

## Choosing

| You want | Set |
|---|---|
| Nothing extra, maximum privacy | `provider = "none"` (default) |
| Full US data, nothing leaves the machine | `provider = "fcc_uls"` |
| US data, no account, no big download | `provider = "callook"` |
| Worldwide, free, willing to have an account | `provider = "hamqth"` |
| Worldwide, best data, willing to pay | `provider = "qrz"` |

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

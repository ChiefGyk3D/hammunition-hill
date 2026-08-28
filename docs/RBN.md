# Reverse Beacon Network

A DX cluster tells you what other operators chose to spot. The Reverse Beacon
Network tells you what several hundred unattended receivers actually decoded,
with a signal-to-noise figure and a sending speed attached.

That is a different kind of information, and it supports two things a cluster
cannot.

## Who is hearing me

Call CQ and the skimmers report you — from where they are, with an SNR. It is
the only feedback loop in amateur radio that answers *is my signal getting out*
before anybody answers you.

That is the default view, and `watch` defaults to your login callsign because
that is the point. An operator running two calls, or curious how a friend is
doing, can name others.

The SNR carries the colour, on the scale a CW operator would recognise: under
6 dB is a struggle, over 20 dB is armchair copy.

## Where the bands are actually open

Several thousand automated decodes a minute is a propagation measurement, not an
opinion. The second view is a rolling tally per band and mode: how many decodes,
how many distinct callsigns, how many distinct skimmers, and the best signal
anyone heard.

"Forty skimmers decoded thirty different stations on 20 m in the last ten
minutes" is a fact about the band. "Nobody has heard anything on 10 m" is too.

## Setup

```toml
[[sources]]
id = "rbn"
kind = "rbn"
url = "telnet://telnet.reversebeacon.net:7000"
options = { callsign = "N0CALL", watch = ["N0CALL"], window_seconds = 600 }
```

Port 7000 is the CW and RTTY feed; 7001 is FT8/FT4. It needs a real callsign to
log in, the same as a cluster — the network does not accept anonymous
connections.

Off by default, like every other stream here.

| Option | Default | |
|---|---|---|
| `callsign` | *required* | The login. No command is ever built from anything the peer sends. |
| `watch` | `[callsign]` | Callsigns whose every spot is kept. |
| `window_seconds` | `600` | How far back the band tally reaches. |
| `flush_seconds` | `10` | How often a snapshot is written. Clamped to a tenth of a second. |

## Volume, and what happens to it

This is the part worth reading before pointing a Raspberry Pi at it. RBN emits
far more than a dashboard can hold or a person can read — several thousand spots
a minute across all bands. Keeping them would fill memory to no purpose.

So two things are kept and everything else is discarded **as it arrives**:

- every spot of a watched callsign, capped at 200;
- a rolling per-band, per-mode tally of everything else — counts, distinct
  callsigns, distinct skimmers, best SNR and who it was.

The tally is bounded by the number of bands times the number of modes: a few
dozen entries no matter how hard the network is working. The identifier sets
inside each bucket are capped too, so "seventy different stations" is available
without holding a contest log.

**Nothing here grows with traffic**, and that claim is measured rather than
asserted: `tests/test_rbn.py` pushes a hundred thousand spots through and checks
what is left. That test exists because of a lesson this project already learned
the hard way — the FCC ULS importer's first version had a docstring claiming
bounded memory while actually needing about 620 MB at real scale.

Expiry is coarse on purpose. A bucket is dropped when nothing has landed in it
for a whole window; a per-spot expiry would require keeping the spots, which is
the thing being avoided. The cost is that a band which goes quiet keeps its
counts for up to one window, so the panel shows the time of the last spot rather
than making anyone guess.

## Two things found writing this

Both are in the tests now.

**A zero flush interval was an infinite spin.** `asyncio.wait_for` with a
timeout of zero never lets the read start, so the loop turned forever without
consuming a byte — a config typo that costs a core. The interval is clamped to a
tenth of a second in this client and in the cluster client, which had the same
bug.

**Nothing tested a stream client above its line parser.** A refactor that pulled
a method out of the cluster class entirely left all seventeen of its tests
passing. `tests/test_rbn.py` now drives the read loop with a real
`StreamReader` fed from memory, which exercises the actual `readuntil`, the
timeouts and the flush timer rather than a stand-in for them.

## What it does not do

- **No spotting.** This listens. It never uploads anything, and it never tells
  the network what you heard.
- **No alerting.** A panel that made a noise when a rare prefix appeared would
  be useful and is a different feature; it is on the candidate list in
  [STATUS.md](STATUS.md).
- **No history.** The window is minutes, not days. Trend analysis over weeks is
  what the metrics exporter is for, when it exists.

The RBN answers "is my signal getting out" for CW and RTTY. For the digital
modes the same question is answered by the `pskreporter` source, and for WSPR
beacons by the `wspr` source — both documented in
[CONFIGURATION.md](CONFIGURATION.md), both feeding the **Heard You** panel
beside this one.

# Metrics

Snapshots have no history. Each write replaces the last, deliberately, because
the design is *what is true now* — which is exactly right for a wall display and
useless for "SFI over six months" or "spots per band across a contest weekend".

This is the export path out. Grafana then does what Grafana is good at, and this
project does not have to become a time-series stack to get there.

## This is a read path, not a write

An earlier version of the roadmap called an exporter "the first outbound write
the collector would ever make". A Prometheus endpoint is not one. **Prometheus
pulls.** Nothing here originates a connection, nothing leaves the machine unless
something on the network asks for it, and the egress allowlist is untouched.

That is a meaningfully smaller change than an InfluxDB push — which genuinely
would be a write — and it is why this half comes first. The push half is still
on the roadmap in [STATUS.md](STATUS.md).

It is off by default anyway. It is served from the dashboard's own port, so it
is reachable by exactly the audience that can already read the dashboard, and it
exposes the same numbers the dashboard already shows. "The same exposure" is a
claim worth making deliberately rather than inheriting.

## Setup

```toml
[metrics]
enabled = true
```

Then scrape `http://your-host:8073/metrics`.

```yaml
scrape_configs:
  - job_name: hammunition-hill
    scrape_interval: 60s
    static_configs:
      - targets: ["your-host:8073"]
```

Sixty seconds is plenty. The collector's own cycles are minutes long, so a
faster scrape samples the same number repeatedly.

When it is off the endpoint returns **404, not 403** — an endpoint that is
switched off should not announce that it exists.

## Cardinality, which is the part that matters

The classic way to ruin a Prometheus is a label whose values are unbounded. A
callsign label would do exactly that: every station heard becomes a new time
series, kept forever, and the database keeps growing after the operator has gone
to bed.

**Nothing here is labelled by callsign.** Labels are `band`, `mode` and `source`
— all bounded by the band plan and by the config file. A test walks the whole
output and fails if `call`, `callsign` or `station` appears as a label anywhere.

There is a hard cap of 2000 series as well, because a bound that is only argued
for is a bound a future source quietly breaks. Reaching it truncates the output
and says so in a comment line, rather than handing a database an unbounded
stream in silence.

The same reasoning applies to satellites: there is a "seconds until the next
pass" series, and deliberately **not** one series per satellite. A catalog is an
unbounded label in exactly the way a callsign is.

## What it exports

### Liveness — what you would actually alert on

| Metric | |
|---|---|
| `hamhill_up` | Always 1, so a scrape failure is distinguishable from a collector with nothing to say |
| `hamhill_snapshot_present{source}` | 1 if this source has ever written |
| `hamhill_snapshot_age_seconds{source}` | Seconds since it last wrote |
| `hamhill_snapshot_failed{source}` | 1 if the last cycle failed |
| `hamhill_snapshot_stale{source}` | 1 if older than its own staleness window. A window of 0 means the data does not age — the reference tables are written once at startup and never go stale |

### Space weather and propagation

`hamhill_solar_flux`, `hamhill_k_index`, `hamhill_a_index`,
`hamhill_xray_flux_wm2`, `hamhill_muf_mhz`, `hamhill_luf_mhz`,
`hamhill_absorption_db`, `hamhill_aurora_power_gw`.

### Band activity, from RBN

`hamhill_rbn_spots`, `hamhill_rbn_stations`, `hamhill_rbn_skimmers` and
`hamhill_rbn_best_snr_db`, each labelled `{band,mode}`.

Plus the two about you: `hamhill_rbn_reports_of_me` and
`hamhill_rbn_best_snr_of_me_db`. The second is the one worth alerting on — *the
best report of my signal fell off a cliff* means something happened to the
antenna, the feedline or the radio.

### Satellites

`hamhill_satellite_prediction_available`, `hamhill_satellite_passes`,
`hamhill_satellites_tracked`, `hamhill_next_satellite_pass_seconds`.

## Missing is not zero

A source that has never reported is not a source reporting zero, and a graph
that cannot tell them apart will be read wrongly. So a value that is absent, or
that arrived as something other than a number, produces **no series at all**
rather than a zero.

The same rule applies one level up: with no RBN source configured there are no
`hamhill_rbn_*` metrics, because "zero reports of your callsign" would be a
claim about the bands when it is really a claim about the config file. That one
was found by running the endpoint and reading the output — the unit tests were
happy.

`true` is explicitly excluded from being a number, because `bool` is a subclass
of `int` in Python and a flag would otherwise be exported as a solar flux of 1.

## The exposition format

Prometheus rejects a malformed exposition with an error that does not say what
was malformed, so the format is tested here rather than discovered in a scrape
log: `HELP` and `TYPE` before every family's samples, families never
interleaved, label values escaped backslash-first (escaping the quote first
would double its own backslash on the next pass), whole numbers not rendered in
scientific notation, and `NaN`/`+Inf`/`-Inf` spelled the way the format spells
them.

Families and labels come out sorted. That is not required by the format, and a
scrape you can diff is worth having.

## What it does not do

- **No InfluxDB push.** The other half, and the one that really is an outbound
  write. On the roadmap.
- **No histograms or counters.** Everything here is a gauge, because everything
  here is a current value read off a snapshot. A counter would need state this
  process deliberately does not keep.
- **No authentication.** Same as the dashboard, and the same answer: do not
  expose either to the internet. See the warning in the README.
- **No per-satellite or per-callsign series.** See cardinality, above.

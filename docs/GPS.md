# GPS

Automatic grid square when you are portable, and a check on your clock.

**Off by default.** Two ways to read a receiver, and one decision about what
gets published that is worth understanding before you turn it on.

---

## Is reading a GPS exposing too much of the system?

Reasonable question. The answer is no, with one condition — which turns out to
be the same thing as the feature.

Reading a receiver is **no more privileged than reading `rigctld`**: both are a
local socket or device file the operator opted into by naming it in config.
Neither needs root, neither reaches the network, and the collector's egress
guard is not involved because there is no egress to guard.

The risk was never the collector *reading* the position. It is the dashboard
**publishing** it. A snapshot is served to everyone who can reach the port, and
a raw fix is your house to within a few metres — a materially different
disclosure from the grid square you already print on a QSL card.

### The condition, and why it costs nothing

A dashboard does not need metres. Everything it does with location is
grid-square work:

| Uses location for | Needs |
|---|---|
| Beam headings and distances | a grid square |
| Greyline / day-night | a grid square |
| Band plan region | a grid square |
| Propagation model's solar zenith | a grid square |

So the collector **truncates to a Maidenhead locator before publishing**, and
that is also all the dashboard consumes. The privacy control and the useful
output are the same thing, which is why this is the default rather than an
option you have to know to find.

```toml
options = { precision = 6 }
```

| precision | Area | Notes |
|---|---|---|
| `4` | ~70 × 35 miles | Enough for band conditions and rough headings |
| `6` | ~3 × 1.5 miles | **Default.** What operators already exchange |
| `8` | ~500 × 250 m | Fine detail; think before publishing on a shared LAN |

An unrecognised value falls back to 6 rather than to something more precise. A
typo should not disclose more than you meant.

**Raw coordinates are off by default.** `publish_coordinates = true` adds
`lat`/`lon`, rounded to match the grid precision — publishing a 4-character
locator beside a six-decimal latitude would make the setting cosmetic.

The station is moved to the **truncated** grid too. Computing bearings from a
metre-accurate fix while publishing a coarse locator would leak the precision
back out through the numbers.

## What it is for

**Automatic grid square.** At a park or on a summit the grid changes, and
nobody wants to edit a config file to get correct bearings. This is the feature
that makes a grid-aware dashboard usable portable — and it feeds the
propagation model, whose accuracy depends entirely on knowing where the sun is
relative to *you*.

Opt out with `follow = false` to display the fix without moving the station —
for a fixed site with a receiver present for its clock rather than its position.

**A clock check.** GPS carries UTC from an atomic clock. FT8 stops decoding
somewhere around two seconds of error, and a laptop that has been off the
network for a day can drift further than that with nothing saying so. The panel
shows the offset and flags it past the threshold.

It **does not set the clock.** That needs privileges a dashboard has no
business holding, and `chrony` or gpsd's own PPS handling do it properly.

## gpsd — the recommended path

```toml
[[sources]]
id = "gps"
kind = "gpsd"
url = "tcp://127.0.0.1:2947"
local = true
options = { precision = 6 }
```

gpsd is already running on most Linux handhelds that have a receiver, it has
done the hard parsing, it handles receiver quirks, and — the reason to prefer
it — **it shares the device**. Reading the serial line directly takes it
exclusively, so your logging software would stop seeing it.

`local = true` is required: gpsd is on loopback, and the egress guard refuses
private addresses unless a source opts in.

## Serial NMEA — when there is no gpsd

```toml
[[sources]]
id = "gps"
kind = "nmea"
path = "/dev/ttyUSB0"
options = { baud = 9600, precision = 6 }
```

`path`, not `url` — this is a character device, not a network address, and it
makes no network connection at all.

Needs read access to the device, usually membership of `dialout`. That is not
root-equivalent, unlike the `docker` group trade the sibling project declined.

Baud is 4800 by default (the NMEA 0183 standard rate); USB pucks are commonly
9600. Supported: 4800, 9600, 19200, 38400, 57600, 115200.

**No new dependency.** pyserial is the usual answer, and it would be a third
package on a project whose short dependency list is part of its argument. A
serial port is a character device and the standard library's `termios`
configures one, so this is about forty lines instead.

## What it handles

- **GGA and RMC**, from any talker ID — `GP`, `GN`, `GL`, `GA`, `GB`. Modern
  multi-constellation receivers say `GN`, and a parser hardcoded to `GP` sees
  nothing from them.
- **Checksums**, validated. Serial lines drop bytes, and a corrupted fix is
  worse than no fix.
- **`ddmm.mmmm`, not decimal degrees.** Reading `3944.5000` as 39.445 rather
  than 39.7417 is the classic NMEA mistake and puts you a few hundred miles
  away. There is a test named after it.
- **No-fix and void sentences ignored.** A receiver reports coordinates before
  it has a lock; those are not a position.
- **Garbage tolerated.** Half-written sentences at startup and dropped bytes
  return nothing rather than raising.

## What it does not do

- **No altitude.** Parsed from GGA and not published; nothing here uses it.
- **No speed or heading.** This is a station dashboard, not a chartplotter.
- **No time discipline.** Reported, never set — see above.
- **No dead reckoning.** A fix older than two minutes is flagged stale rather
  than extrapolated.

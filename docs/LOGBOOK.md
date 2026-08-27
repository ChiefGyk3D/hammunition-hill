# The logbook

I argued against building one. I was too absolute, and this is the revised
analysis — what changed, what did not, and the design that follows.

## What I said before

> Logging needs a write endpoint, which needs authentication, which dissolves
> the security model this project is built around.

The middle step is wrong. A write endpoint does **not** need authentication here,
because the network is already the access control: anyone who can reach the port
can already read your dashboard, your QTH, and your log-derived data. Adding a
write path does not change *who* can act. It changes *what they can do*, which is
a real escalation but a different and smaller one than I claimed.

## What is actually new, and how it is handled

There are three genuine risks, and all three have standard, well-understood
defences. Being precise about them is more useful than refusing.

**Cross-site request forgery.** This is the real one, and it does not require the
attacker to be on your network at all: any web page you visit could try to POST
to `http://localhost:8073`. Three layers:

- The endpoint accepts **only** `Content-Type: application/json`. That makes any
  cross-origin attempt a *preflighted* request, and we send no CORS headers at
  all, so the browser refuses it before our code runs.
- `Sec-Fetch-Site` must be `same-origin`. Browsers set this header themselves and
  a page cannot forge it.
- No form-encoded, multipart, or plain-text bodies are accepted, which are the
  three content types that can be sent cross-origin without preflight.

**DNS rebinding.** An attacker's domain resolves to `127.0.0.1`, making their
page same-origin with us. Defended by validating the `Host` header against the
address we are actually bound to.

**Data loss.** Handled by shape rather than by permission: the endpoint is
**append-only**. There is no edit and no delete over HTTP. The worst a successful
attack could do is add junk QSOs to a text file you can open and fix — not
destroy a log.

The endpoint is off by default regardless.

## Why build it here at all

Because of one thing nothing else can do: **this dashboard already knows almost
the whole QSO.**

- `rigctld` gives the frequency, band, and mode as they are right now.
- A selected DX spot gives the callsign, band, mode, and entity.
- A WSJT-X decode gives the callsign, mode, and signal report.
- The callsign lookup gives the name, grid, and location.
- The station config gives your own callsign and grid.

So logging a contact is a confirmation, not a form-filling exercise. A standalone
logger has to ask you for all of it.

There is a second, better reason. The needed-slot colouring already reads your
ADIF. Log a new entity here and **the spot list stops calling it new on the next
cycle** — the loop closes on its own, with no synchronisation step, because both
halves are reading the same file.

## What it is not

It is not Log4OM, N3FJP, or CQRLOG, and it should not try to be. No contest
mode, no award tracking, no QSL management, no cluster-driven pile-up handling.
Those are deep, and the tools that do them are good.

## Storage: ADIF files, not a database

Each logbook is a plain ADIF file that we append to. No database, no proprietary
format, no lock-in.

That choice buys several things at once. Your log stays readable by every other
program in the hobby. You can back it up with `cp`. If you outgrow this, you open
the same file in a real logger and nothing needs exporting. And the ADIF reader
that already powers needed-slot colouring simply reads what we wrote.

Writes are appends of complete records, which is the operation ADIF is naturally
safe for.

## Multiple logbooks

Configured as a list, so a portable rig, a home station, and a club callsign can
each have their own file:

```toml
[[logbooks]]
id = "main"
name = "Home station"
path = "~/logs/main.adi"
primary = true

[[logbooks]]
id = "kx2"
name = "KX2 portable"
path = "~/logs/portable.adi"
station_callsign = "N0CALL/P"
```

The **primary** logbook is the one needed-slot colouring indexes. The others are
still logged to and read; they simply do not drive the colouring, because "have I
worked this" usually means "from my main station".

## Enabling it

```toml
[logging]
enabled = true
```

Off by default, because it is the one place the server accepts input and that
should be a decision rather than a surprise.

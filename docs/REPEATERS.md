# Repeaters

The repeater layers your [Hammunition](https://github.com/ChiefGyk3D/Hammunition)
install holds, with distance and bearing from your grid square, as a table and
as dots on the map.

**Tier 0.** Nothing is fetched to show it. The collector runs two read-only
Hammunition commands on this machine, stores what they print, and the page reads
that file like any other snapshot.

## Getting repeaters on the screen

Hill shows what the engine holds; it does not get repeaters for you. From a
terminal, with Hammunition installed:

```
hammunition maps repeaters import FILE
hammunition maps repeaters fetch-repeaterbook --state CODE
```

The first converts your own export (a RepeaterBook GPX or CSV with coordinates,
hearham JSON, a CSV of your own) offline. The second asks RepeaterBook's API with
your own token, and is the engine's to run, never Hill's. Either way the layer
appears here within ten minutes. With no engine, or no layers, the panel says
so and names those commands.

## What the panel shows

Callsign, output frequency in MHz, offset, tone, mode, place, **distance** in
kilometres and **bearing** in degrees from the centre of your grid square, and a
badge per source. A repeater two sources agree on carries a dashed badge for the
second. Rows are nearest first.

Filters are in your browser and nothing you filter for is sent anywhere: band,
mode, source, and "within N km". There is no "near X" search, because that would
be a way to ask someone where a place is, and this panel asks nobody anything.

The map's **RPTR** layer draws the same rows, filtered the same way, and is off
until you turn it on.

The grid square is the one Hammunition has saved (`hammunition station show`).
If it has none, Hill's own `[station]` is used, and if there is neither the rows
show without a distance, and say why.

## The RepeaterBook rule

RepeaterBook's terms keep its data on the machine that fetched it. Hammunition
marks those rows `personal_use`, and Hill honours it in three ways:

- **This machine's own page** shows them. "This machine" means a request from
  loopback, or from the machine reaching itself by its own LAN address.
- **Every other host** gets the snapshot with those rows removed, along with any
  layer, source name or credit that names RepeaterBook, and a count of how many
  were held back. A request carrying a reverse proxy's headers (`X-Forwarded-For`,
  `Forwarded`, `Via` and the like) is treated as another host, because behind a
  proxy the peer is the proxy and every client looks local.
- **Nothing exports them.** The panel has no download, copy or save button, the
  Prometheus endpoint carries no repeater, and `tests/test_repeaters.py` fails if
  that changes.

The page says once, next to the credits, that RepeaterBook data is for this
machine's own use. The credits themselves are the engine's (`credits` in the
document): one attribution or licence text per source present, printed where the
data is shown.

Binding Hill to a LAN address is still your choice and still warns. This rule
decides what a LAN viewer receives; it does not make exposing the dashboard to
the internet a good idea. See [SECURITY.md](SECURITY.md).

## What the collector runs

Exactly these, and nothing else:

```
hammunition maps repeaters list --json
hammunition station show --json
```

Both are read-only. Hill never runs a command that changes the machine
(`import`, `fetch-*`, `remove`, `station set`): those belong to your terminal.
The station document holds your callsign; Hill reads the grid square from it and
keeps nothing else, and an engine error is never quoted into a log.

It looks for `hammunition` on `PATH`, then at `~/.local/bin/hammunition`, where
the engine's bootstrap links it. Turn the loop off with `[repeaters] enabled =
false` ([CONFIGURATION.md](CONFIGURATION.md)).

## Limits, and what was and was not measured

- The nearest 6000 rows are kept; the panel says how many were left out. A
  country's worth of repeaters would otherwise make the file every browser polls
  several megabytes.
- Distance is great-circle from the grid square's **centre**. A four-character
  square is about 70 by 110 km, so a nearby repeater's distance is only as good
  as that.
- The numbers are checked against two paths worked out by hand with a different
  formula (`tests/test_repeaters.py`). The page was rendered in headless Chromium
  against fixture data. It has not been run against a real station's layers by
  the author of the panel, and no real station value is used anywhere in the
  tests.

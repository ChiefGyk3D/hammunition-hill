# Repeaters

The repeater layers your [Hammunition](https://github.com/Renegade-Penguin/Hammunition)
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
mode, source, and "within N km". Bands and modes are covered next.

## Filtering by mode and band, and what the details mean

There is one chip per band and one per mode **that is in your snapshot**, each
with its count. Bands run low to high; modes follow the engine's vocabulary:
`FM`, `DMR`, `D-STAR`, `YSF`, `P25`, `NXDN`, `M17`, `TETRA`, `ATV`. They are
multi-select: pick DMR and YSF and you get repeaters that speak either. A band
chip and a mode chip together narrow the list (70 cm **and** DMR), and both
compose with SOURCE and WITHIN. ALL clears a row. A repeater on two modes counts
under both, so the mode counts can add up to more than the number of repeaters.

**DIGITAL** selects every digital mode on offer (everything but FM and ATV);
**ANALOG** selects FM and ATV. They are shortcuts for those chips, so a repeater
that speaks FM and DMR appears under either. Press one again to clear it. A
repeater whose source did not say what it speaks (no modes) appears with no mode
chip selected and under none of them: guessing FM for it would be inventing data.

Under a row you will see the details an operator keys in, in plain words, and
only the ones the source supplied:

| shown | means |
|---|---|
| `DMR CC 1, Brandmeister, ID 3100` | colour code, network, repeater DMR ID |
| `D-STAR module B, gateway W1XYZ G` | module letter and gateway |
| `YSF DG-ID 00` | Yaesu System Fusion digital group ID |
| `P25 NAC 293` | network access code |
| `NXDN RAN 1` | radio access number |

A detail the source did not give is not shown: no dash, no zero. A RepeaterBook
row, for instance, often has a colour code and no network.

**Version floor.** The mode, band and digital fields arrived in Hammunition with
the `repeaters-list` mode vocabulary (PR #316, 2026-10-04). Against an older engine
the table, centre and every other filter still work; the MODE row says "update
the engine for mode filters" and the chips and details are absent. Hill tells the
two apart by the document: a document with `centre`, or rows with `modes`, is the
new one. The chips and the shortcuts are remembered in this browser with the other
filters, and the map's RPTR layer draws what they select.

**First paint.** The engine measures from your grid square by default and the
collector sorts nearest first itself, so the table is ordered before the page
does any arithmetic; Hill does not pass `--near`, which would only repeat the
station's own value. The engine's `--within`, `--band` and `--mode` are not used
either: the page filters in the browser, so nothing you filter for reaches a
command line.

## Areas: where you are, not everything you loaded

Hammunition (since its area-of-operations work, Hammunition #342) lets you load
several states ahead of an emergency and **activate** the ones you are in
(`hammunition maps activate OH`). Hill follows that:

- The collector puts the **active** areas' repeaters in the snapshot's `rows`,
  which is what the table and the map's RPTR layer read. A layer that belongs to
  no area (your own import, OpenStreetMap, ETCC) is always shown. Per-state
  layers are `repeaterbook-<AREA>`; the engine says which area a layer belongs to
  and whether it is active.
- The AREAS row has one chip per area on this machine, with its repeater count.
  Lit chips are shown. **A chip changes this browser only**, never the engine:
  press a lit chip to hide that area, an unlit one to show it, on the table **and
  on the map's RPTR layer**, which draw the same set (the engine's active areas
  plus the areas you added minus the ones you dropped), measured from the same
  centre. The choice is kept
  in `localStorage` (`hh.repeaters.areas`) as a difference from the engine's own
  list, so it follows the engine when you activate something else.
- The loaded-but-inactive areas' rows travel in the snapshot in a separate list
  (`other_rows`, at most 3000, nearest first) so a chip needs nothing from the
  engine to add them. When that cap cuts rows, the page says so in one line:
  `hammunition maps activate` is the full answer. The RepeaterBook rule applies to them exactly as to the
  rest: another host gets none of them, and no area whose layers are
  RepeaterBook's.
- **The centre follows the area when the station is far from it.** With no centre
  of your own, and the station more than **300 km** from the middle of the first
  area that is on (or no station set), distances are measured from the middle of
  that area and the page says so in a sentence. 300 km is about what a state
  spans, so a station farther than that is outside the area, not beside it, and
  its own position would rank the area's repeaters from somewhere you are not
  going. The middle is the mean of that area's repeaters' positions: the engine
  carries no boundary to take a centroid of. A centre you set yourself always
  wins, and STATION measures from the station instead (kept, until you press
  AREA).
- An engine that predates areas prints no `active` on a layer. Everything is then
  shown as before, the chips are absent and the AREAS row says "update the engine
  for areas".

Not measured: against a real engine with areas loaded; the fixtures are the
document's shape (three states, invented callsigns).

## Choosing the centre

Distance, bearing, the "within" filter and the sort order are measured from a
**centre**. It defaults to your station's grid square, using the numbers the
collector already computed, so the first paint needs no arithmetic. To look
somewhere else, in the panel's CENTRE row:

- type a **Maidenhead grid**, four or six characters (`FN42`, `FN42ab`), or a
  **latitude, longitude** pair (`42.36, -71.06`), then SET; or
- on the map, press **SET CENTRE** and click, or **press and hold** a point.

STATION puts it back. The map pans to the centre and draws a marker for it. Every
row's distance and bearing are recomputed in the browser from the rows already in
the snapshot (the same great-circle and Maidenhead maths as `geo.py`, held to the
same hand-computed paths by a test). The last centre is remembered in this
browser's `localStorage` and goes nowhere else: it is never sent to the
collector or any server.

**A place name is not supported.** Turning a name into a point is a lookup, and
nothing here asks anyone anything; use a grid, coordinates or the map.

**The data is what was imported.** Choosing a centre does not make the data
worldwide. When the nearest repeater is farther than the current "within" radius
(250 km when none is set), or there are none, the panel says so and names the
commands that fill the gap: `hammunition maps repeaters fetch-repeaterbook
--state CODE` and `hammunition maps repeaters import --from-osm`.

The obvious next centre source is the GPS tether's position stream
(`127.0.0.1:10111`, server-sent events). Hill does not read it yet, so there is
no "use GPS position" here; it is deliberately not added as a dependency now.

The map's **RPTR** layer draws the same rows, filtered and measured the same way,
and is off until you turn it on.

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
  formula (`tests/test_repeaters.py`), and the browser's recomputation against the
  same two (`tests/test_repeaters_js.py`). The map click and long press were not
  exercised with a pointer, only the logic behind them. The page was rendered in headless Chromium
  against fixture data, including the mode chips, both shortcuts and an engine
  that predates the vocabulary. The map's RPTR dots were not drawn with a mode
  chip selected; that path shares the table's filter code and its test, nothing
  more. It has not been run against a real station's layers by
  the author of the panel, and no real station value is used anywhere in the
  tests.

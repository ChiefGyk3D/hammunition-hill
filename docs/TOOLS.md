# Shack tools

The calculations an operator otherwise opens a browser tab for: how long to cut
a dipole, what a run of coax costs, what an SWR reading means in watts, and the
distance and bearing between any two grid squares.

All of it is tier 0 — arithmetic over small tables, computed in the browser,
with nothing fetched from anywhere. That is deliberate rather than incidental:
the person who needs to know how long to cut a 40 m dipole is usually standing
in a field holding wire cutters, which is exactly when a hosted calculator is no
help at all.

## Two things this is honest about

A calculator is trusted the moment it is on screen, which makes a wrong one
worse than no calculator — somebody cuts wire to it.

**Cut long.** Every length here is a starting point. Height above ground, nearby
metal, insulation on the wire and the shape of the feedpoint all move resonance,
and they move it by more than the difference between the formulas people argue
about. Cut long, measure, trim.

**The coax figures are nominal.** They are manufacturer headline numbers for new
cable on a bench. Real loss rises with age, water in the braid, every connector,
and the temperature of the run. Treat the number as a floor.

## antenna

A cut chart at one frequency, in metres and feet:

| | Length |
|---|---|
| Half-wave dipole | tip to tip; each leg is half of it |
| Quarter-wave vertical | over a ground plane or radials, which are the other half of the antenna |
| End-fed half wave | the same wire as a dipole, fed at the end through a transformer |
| 5/8-wave vertical | needs a loading coil at the base; gain over a quarter wave |
| Full-wave loop | runs slightly long, not short |

The wire antennas carry the conventional 0.95 end-effect factor, which is where
the `468/f` rule US handbooks have printed for a century comes from — it is
0.95 of a free-space half wave, expressed in feet. The loop carries its own
figure, because a loop runs long: that is the `1005/f` rule. The test suite
checks the panel against both, at eight frequencies, so the chart and the rule
of thumb cannot disagree.

## feedline

Pick a cable and a length, and get the matched loss, what reaches the antenna
out of 100 W, the velocity factor, and how much of that cable makes a quarter
wave — the last being the single most common way a home-made matching section
ends up the wrong length.

### Where the loss numbers come from

`COAX` in `src/hammunition_hill/antenna.py` holds **two published loss figures
per cable**, at 100 and 450 MHz, rather than fitted constants. The model

```
loss (dB per 100 ft) = k₁·√f + k₂·f
```

— conductor loss rising as the square root of frequency, dielectric loss rising
linearly — is then *defined* by those two numbers, and `k₁`/`k₂` are solved from
them.

That is the point of doing it this way round: the table holds numbers a reviewer
can check against a datasheet, rather than constants nobody can. The tests then
verify the curve reproduces both published points exactly, *and* lands where the
datasheets say at frequencies between and outside them — 100 ft of LMR-400 at
146 MHz, RG-213 at 20 m, RG-58 at 10 m — so the curve is checked, not just the
table. A further test asserts the cables rank in catalogue order at every band,
which catches a transposed digit that the individual anchors would not.

## SWR

What a reading means, in the units people care about: reflected power as a
percentage, return loss, and mismatch loss.

Then the part that is actually worth knowing — the same SWR through the cable
and length you set on the feedline tab, split into the matched loss and the
standing wave's share:

> A 3:1 SWR on 10 m of LMR-400 at 20 m costs under 0.15 dB. The same 3:1 on 30 m
> of RG-58 at 2 m costs most of a decibel on top of an already expensive line.

**High SWR is not by itself the problem — high SWR through a lossy line is.**
Change the cable and the length and watch the same reading cost almost nothing,
or almost everything. Both of those examples are tests, so the panel cannot stop
demonstrating it.

A perfect match has infinite return loss. The panel says `∞` rather than hiding
the row or printing a NaN, because that is what it is.

## grid path

Distance and bearing between **any two** Maidenhead squares, not just from your
station — which is the thing the map panel cannot do. Fields (`JO`), squares
(`JO65`) and subsquares (`JO65ma`) all work, at whatever precision you give.

Short path and long path, in degrees and as a compass point, plus the latitude
and longitude each square resolves to.

Great-circle over a spherical Earth. That is within a few kilometres of the
ellipsoidal answer at any distance a radio path covers, and both are far more
precise than a grid square is — a square is 1° by 2°.

## Two implementations, held together

The tables and the arithmetic live in `src/hammunition_hill/antenna.py`, where
they can be tested. The browser does the arithmetic itself, in
`web/lib/antenna.js`, because a calculator that asked a server for the length of
a dipole would be a calculator that stops working in a field.

That is two implementations of every formula, and two implementations drift. So
`tests/test_antenna.py` runs the JavaScript the panel loads under node, over the
same published tables, and demands the same answers to the decimal place the
panel displays — eight frequencies, ten cables, five lengths, seven SWRs.

The grid tools reuse the geo helpers the callsign panel already had, and those
had the same problem with nothing watching it: `web/lib/callsign.js` reimplements
Maidenhead conversion, haversine and bearing from `geo.py`, and nothing checked
they agreed. `tests/test_geo_drift.py` now does — seventeen squares chosen for
the corners rather than the middle (both poles, both sides of the antimeridian,
the origin, fields with no subsquare), seven paths, and the compass rose all the
way round.

## What it does not do

- **No modelling.** No NEC, no patterns, no ground systems. Lengths and losses
  are arithmetic; predicting what an antenna will actually do at a site is not,
  and a panel that implied otherwise would be lying.
- **No Smith chart.** Worth having, and a real piece of interactive drawing
  rather than a calculation. On the candidate list in
  [STATUS.md](STATUS.md).
- **No antenna analyser input.** Reading a sweep off a NanoVNA would make the
  SWR tab far more useful and needs a serial or USB path into the collector.
  Also on the candidate list.

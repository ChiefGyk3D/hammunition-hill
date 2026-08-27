# Satellite passes

When the birds are up, and where to point.

The elements are fetched. **The predictions are not** — they are computed on
this machine, from elements already on disk, every five minutes. That split is
the whole design, and it is worth being explicit about why.

## Why the pass list is derived rather than fetched

A pass list is a function of two things: the orbital elements, and the clock.
The elements change once a day at most. The clock changes constantly, and it is
the input that decides which satellite is above you *now*.

If the pass list came from an upstream service, the panel would go blank the
moment the WAN did. Computing it here means:

- **Elements stay usable for days.** A set a week old still predicts a pass to
  within a few seconds. A WAN outage costs nothing here for a long time, which
  matters, because the operator most likely to be chasing a satellite is the one
  in a field.
- **Nothing is asked of anyone to render the panel.** No request per view, no
  request per refresh. The collector fetches a text file once a day and that is
  the entirety of the network traffic.
- **Your location never leaves the machine.** A hosted pass predictor needs to
  be told where you are. This one already knows, and tells nobody.

This is the same shape as the propagation model: a derived source, reading
snapshots other sources wrote, adding no network of its own.

## Setup

Pass prediction needs an optional extra:

```
pip install 'hammunition-hill[satellites]'
```

Then a source for the elements, and a floor:

```toml
[[sources]]
id = "tle"
kind = "tle"
url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle"
interval = 86400

[satellites]
min_elevation = 5.0
```

Daily is generous. Anything more frequent is wasted traffic on somebody's
volunteer bandwidth.

Without the extra, the panel says so plainly rather than rendering an empty box.
Without a `[station]` grid it says that instead — a pass is a fact about a
place, not about a satellite.

### `min_elevation`

Zero is the geometric horizon and nobody has one: trees, buildings and hills all
sit above it. Five degrees is the conventional working floor. A station in a
valley may want fifteen; one on a hilltop with a clear view may want two.

## Why SGP4 is a dependency and not code in this repository

Everything else the dashboard computes — Morse timing, the propagation model,
antenna lengths, great-circle paths — is implemented here and tested here.
Orbit propagation is the exception, deliberately.

A two-line element set is **not a state vector**. It is a set of constants
fitted against one specific propagator, and the numbers only mean anything when
fed to that propagator. `sgp4` is the reference implementation of Spacetrack
Report #3 as revised in 2006 — the model the elements are defined against.

Reimplementing it would be five hundred lines of dense orbital mechanics that
could not be verified to the same standard offline, and the failure mode of
getting it subtly wrong is a pass list that looks entirely plausible and is not
there. That is the worst possible outcome for this panel.

It is an optional extra rather than a dependency so the core install stays at
two, and it has no dependencies of its own.

Everything *around* the propagator is here, and tested here: element parsing and
checksums, the sidereal rotation, the ellipsoid, look angles, the pass search
and Doppler.

## How the tests pin it down

There is no reference pass list to compare against offline, and a pass list is
the worst kind of thing to eyeball — entirely plausible whether or not it is
right. So `tests/test_satellites.py` leans on invariants that must hold for any
correct implementation:

| Check | What it catches |
|---|---|
| From directly beneath a satellite, it is straight up | A swapped axis, a wrong local-horizon rotation, a spherical Earth where an ellipsoid belongs |
| Range from beneath equals the altitude | An ellipsoid radius used where a geocentric one belongs |
| A geostationary satellite keeps its longitude | The sidereal rotation, in the only check that compares a direction across time |
| A sidereal day is 3.9426 minutes short of a solar one | The rotation *rate*, which nothing else can see |
| Doppler is zero at closest approach | The sign convention and the geometry agreeing with each other |
| The ISS makes five to seven passes a day from mid-latitudes | A search that misses passes, or finds them twice |
| Just inside a pass the satellite is up, just outside it is not | Bisection converging one step wrong |

Each was verified by breaking the thing it watches. That process corrected a
claim in this file: the "directly beneath" invariant reads like it tests the
sidereal rotation, and it does not — the sub-satellite point is computed
*through* the same rotation the observer is compared in, so a consistent error
cancels exactly. Flipping the sign of the rotation and watching that test still
pass is how the geostationary checks came to exist.

## What it does not do

- **No rotator control.** Pointing a mast is an outbound command to hardware, a
  posture this project does not have yet. `rotctld` is on the candidate list in
  [STATUS.md](STATUS.md) and would need its own opt-in and its own document.
- **No transponder plan or Doppler tuning.** The module computes Doppler, and
  nothing yet drives a radio with it. Wiring it to `rigctld` would be the same
  posture change.
- **No refraction.** Refraction lifts a satellite on the horizon by about half a
  degree at AOS and nothing at elevation — far below the error in elements that
  are hours or days old. Correcting for it would be precision this cannot
  support.
- **No polar motion** in the inertial-to-ground rotation, for the same reason:
  it is under an arcsecond.
- **No visual pass filtering.** Whether a satellite is sunlit and you are in
  darkness is a different calculation, and this panel is for working them, not
  watching them.

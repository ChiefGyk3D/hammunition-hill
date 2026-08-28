# The propagation indicator

**This is not a propagation prediction.** It is worth being blunt about that
before anything else, because the output has decimal points and decimal points
invite trust.

VOACAP is a propagation prediction. It models a *specific path* between two
points, at a specific hour, with antenna patterns, transmit power, and a
climatological ionosphere behind it, and it is the product of decades of work.
This is three numbers and some empirical arithmetic, answering a much smaller
question: **roughly which bands are worth trying right now, and why not the
others.**

That smaller question is still worth answering. The inputs are already on the
dashboard, the arithmetic is free, and "10m is probably shut, the MUF is under
20 MHz" is more use than an SFI of 92 and a mental model you have to apply
yourself.

## What it computes

| Output | Meaning |
|---|---|
| **foF2** | F2 critical frequency — the highest that comes straight back down at vertical incidence. Everything else derives from it. |
| **MUF** | foF2 × 3.0, the conventional obliquity factor for a 3000 km hop. An unqualified "MUF" usually means this. |
| **Absorption** | D-layer absorption at a 1 MHz reference, in dB. Daytime only. |
| **LUF** | The frequency below which absorption eats the signal. |
| **Per band** | `good` / `warn` / `critical`, each with a reason. |

The reasons are the useful part. "Above the MUF" and "below the LUF —
D-layer absorption" tell you *why* a band is dark, which a colour alone cannot.

## Why your grid square matters

The model this was ported from — `solarstorm_scout`, the same author's — used
the UTC hour as a stand-in for how high the sun is:

```python
hour_angle = abs(utc_hour - 12)     # 0 at "solar noon"
```

That is exactly right on the Greenwich meridian and wrong everywhere else. It
is a perfectly reasonable simplification for a bot posting global space-weather
summaries, which is what that project is. It is wrong for a station dashboard,
because a station has a location.

Measured, for Denver on 27 August:

```
  UTC   local   zenith   absorption      old abs(utc-12) proxy
  12:00  06:00    95.2     0.0 dB        proxy says: PEAK
  19:00  13:00    29.9    34.6 dB        actual peak
```

The proxy puts worst-case D-layer absorption at **05:00 local, before
sunrise** — an hour when this model correctly reports zero, because the sun is
not up. Nine hours out in Tokyo.

So the port computes the real solar zenith angle at the operator's own
coordinates, using the same solar-position algorithm the greyline already uses.
That one change is most of the value here.

## Two other things corrected in the port

**A docstring that disagreed with its code.** The original documented
`sqrt(SFI/150)` and implemented `sqrt(SFI/100)` — a difference of nearly a
megahertz at solar minimum. Neither produced the values the docstring itself
claimed. This implementation is calibrated against operating anchors instead,
and `tests/test_propagation.py` pins them:

| | foF2 |
|---|---|
| Solar minimum, after dark | 3–4.5 MHz |
| Solar minimum, midday | 6–8.5 MHz |
| Solar maximum, after dark | 5.5–8 MHz |
| Solar maximum, midday | 12–14.5 MHz |

Arguable numbers, deliberately: a future tweak has to argue with something an
operator can check on the air.

**Emoji baked into return values.** The original returned `"🟢 Low (Day)"` as
its absorption description. Presentation belongs to the panel — a snapshot
carrying a coloured circle cannot be restyled, cannot be made accessible, and
cannot be rendered by anything that is not a terminal. The collector publishes
a level and a reason; the browser decides what those look like. There is a test
that fails if a symbol character reaches the data.

## Known limitations

Read these before trusting a number.

- **No path, so no distance.** MUF here assumes a 3000 km hop. A short path has
  a lower MUF; a chordal one can exceed it. The model does not know where you
  are trying to work.
- **Therefore no DX/local distinction.** With the sun low, this will call 160m
  "open" — true for regional and NVIS work, misleading if you wanted DX. A
  path-free model cannot separate the two.
- **foF2 from flux is loose.** Two days at the same SFI can differ by several
  megahertz. Season, latitude and day-to-day ionospheric weather all matter and
  none are inputs here.
- **Storm effects are approximate.** K-index absorption is scaled by latitude,
  because precipitation lands near the auroral oval — a K of 7 over Tromsø is
  not a K of 7 over Quito. That is better than ignoring latitude, and still
  crude.
- **No sporadic E.** The 6m opening that makes a summer afternoon is invisible
  to this model, which will report 6m closed throughout.

## Configuration

None. It is a **derived** source: it reads the solar flux and K index that
other sources have already fetched, and adds no network of its own. Give it
either a `swpc` pair or a `hamqsl` source and a `[station]` grid, and it
appears.

```toml
[station]
grid = "DM79"           # required — without it the model has no sun angle

[[sources]]
id = "solarflux"        # or hamqsl, which carries both numbers
kind = "swpc"
url = "https://services.swpc.noaa.gov/json/f107_cm_radio_flux.json"
options = { product = "f107_flux" }
```

It recomputes every five minutes even when the inputs have not changed, because
its largest input **is** the clock: the same flux and K give different answers
at 09:00 and 14:00.

If it cannot run it says which input is missing rather than rendering zeroes
that look like a reading.

## The DX Path panel: MINIMUF 3.5

The indicator above has no path: it describes the sky over *your* station.
The **DX Path** panel answers the planning question — *when does 20 m open to
Japan from here* — with a real point-to-point model: **MINIMUF 3.5**, the
algorithm R. B. Rose and J. N. Martin published at the Naval Ocean Systems
Center in 1978-79 (NOSC TR 201 and its 3.5 revision; QST wrote it up in
December 1982). It is a United States Government work, public domain, and
`src/hammunition_hill/minimuf.py` is an original implementation of it —
mirrored in `web/lib/muf.js` so the panel can redraw the chart the moment you
type a grid square, with a drift test holding the two copies to the same
milli-MHz.

How it works: the great-circle path is sampled at its midpoint (short paths)
or at a control point near each end (long ones, where the rays actually
refract). Each control point gets an effective solar illumination that rises
after local sunrise and decays exponentially after sunset — that lag is why
20 m stays open into the evening — which maps to a critical frequency, gets
an obliquity factor for the hop geometry, and the *worst* control point sets
the path MUF.

What it is honestly worth:

- The report validated it against oblique-sounder measurements over 23 real
  circuits and claims an **RMS error of about 3.8 MHz**. It will call the
  right band nearly always and the right hour usually; it will sometimes be
  a band off.
- **F2 layer only.** No sporadic-E (so the panel draws no 6 m row — an Es
  opening will beat the chart, and that is normal), no D-layer absorption
  (bands far below the MUF render as "no opinion", not green), no antennas,
  no power, no signal-to-noise.
- Fitted for paths of roughly **250 to 12 000 km**. Outside that the panel
  refuses and says why, rather than extrapolating: closer is NVIS or ground
  wave, farther is long-path work that needs a real ray tracer.

## If you want a real prediction

Use VOACAP. It is the right tool, it is free, and it models what both of
these deliberately do not: reliability, signal level, antennas, power. The
indicator is for the glance at the wall on the way past the radio; MINIMUF
is for picking the hour to try a path; VOACAP is for engineering a circuit.

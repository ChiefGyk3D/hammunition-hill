# Borrowing from the sibling projects

Two of this author's existing repositories already solve pieces of what
Hammunition Hill needs. This is an audit of what is worth taking, what needs
changing on the way in, and the licence question that goes with it.

- **[solarstorm_scout](https://github.com/ChiefGyk3D/solarstorm_scout)** — a
  space-weather bot that posts NOAA data to Bluesky and Mastodon.
- **[penguin-overlord](https://github.com/ChiefGyk3D/penguin-overlord)** — a
  Discord bot whose `radiohead` cog is 2,600 lines of amateur radio features.

> **Settled:** Hammunition Hill is now MPL-2.0, matching both siblings. Logic
> ports by copy-paste with headers intact, and there is no per-file bookkeeping
> or mixed-licence explanation to maintain. The analysis below is kept for the
> record.

## Licence: not quite "no issues", but close

Both repositories are **MPL-2.0**, not MIT. MPL is *file-level* copyleft: copy an
MPL file into this MIT project and that file stays MPL, along with the obligation
to publish changes to it.

Authorship is clean. Across solarstorm_scout's full history the only committers
are ChiefGyk3D, GitHub Copilot, and dependabot — no third-party humans, so there
is no one else's permission to get.

That leaves two workable routes, and the choice is the author's:

1. **Relicense the borrowed logic MIT.** Simplest, and available because the
   copyright is entirely his. The project stays uniformly MIT.
2. **Keep ported files MPL-2.0 with their headers intact**, and note the mixed
   licensing in the README. MPL is per-file, so MPL and MIT coexist in one
   repository without infecting anything else. This is the lower-effort,
   lower-risk option and needs no relicensing decision at all.

Either way the file headers need to be deliberate rather than copied by accident.
**Nothing should be ported until this is settled**, because retrofitting a
licence decision across files is worse than making it once up front.

## Worth taking

### 1. The propagation model — solarstorm_scout `spaceweather.py`

This is the most valuable find, because it is exactly the pre-VOACAP indicator
the roadmap calls for. Four functions:

| | |
|---|---|
| `estimate_fof2_from_sfi` | Critical frequency from solar flux |
| `calculate_d_layer_absorption` | D-layer absorption by hour and activity |
| `calculate_band_conditions` | Per-band open/marginal/closed from foF2, MUF, absorption, K |
| `get_best_bands_now` | "What should I be on right now" |

Together these close the **propagation** parity gap without touching VOACAP.
Full VOACAP stays deferred; this ships something useful in the meantime.

**Three things to fix on the way in.** These are not criticisms of the original —
two of them are correct for a bot that posts to the whole world and wrong only
for a dashboard that knows where its operator is standing.

- **D-layer absorption assumes solar noon is 1200 UTC.** It uses
  `abs(utc_hour - 12)` as a zenith-angle proxy, which is right on the Greenwich
  meridian and progressively wrong elsewhere. For an operator at −75° longitude,
  real solar noon is around 1700 UTC, so peak absorption would be reported about
  five hours early. SolarStorm Scout has no location to work with and this is a
  reasonable global average; **Hammunition Hill has the operator's grid square**,
  so the port should compute an actual solar zenith angle from latitude,
  longitude, and day of year. That is a genuine improvement, not a translation.
- **A docstring and its code disagree.** `estimate_fof2_from_sfi` documents
  `sqrt(SFI/150)` and implements `sqrt(SFI/100)`. Decide which was intended
  before porting, rather than preserving the ambiguity.
- **Emoji are baked into the return values.** `🟢 Low (Night)` is right for a
  social post and wrong for a panel that has its own colour tokens and a dark
  theme. Split the model from its presentation: return a level, let the UI
  decide how to draw it.

### 2. The band plan — penguin-overlord `radiohead.py`

`ARRL_BAND_PLAN` is a structured US band plan: per band, a list of segments with
frequency range, mode, and notes. Two uses here.

- **A tier 0 band plan panel.** Pure reference data, no network, works with the
  WAN down. `HAM_LICENSE_CLASSES`, `POWER_LIMITS`, and `COMMON_SERVICES` from the
  same file round it out.
- **Better mode inference.** `bands.py` currently guesses mode from a hand-rolled
  CW-ceiling table. Real segment boundaries would be more accurate.

One caveat: it is the **US** band plan, and mode inference runs against spots from
everywhere. Region 1 and Region 3 differ enough that using US segments globally
would make inference *worse* for non-US spots, not better. Either scope it to a
configured region or keep it as display-only reference data. The current
inference is deliberately region-agnostic, which is why it is coarse.

### 3. SWPC products not yet wired up

penguin-overlord and solarstorm_scout between them already use several NOAA
products this project does not:

| Product | Use here |
|---|---|
| `aurora-nowcast-hemi-power.txt` | Closes the **aurora** parity gap |
| `noaa-scales.json` | R/S/G storm scales — a compact status line |
| D-RAP global image | Tier 2 image panel, HF absorption at a glance |
| OVATION aurora imagery | Tier 2 image panel |

The two images are the easy kind of tier 2: images, not iframes, so they cannot
run script — and the opaque-mode proxy would keep even those same-origin.

### 4. The contest calendar URL

penguin-overlord fetches `contestcalendar.com/weeklycont.php`, a URL that is
demonstrably in use. `config.example.toml` currently suggests a `.ics` URL that
was inferred rather than verified, with a note to check it. Worth reconciling —
though note the two need different parsers, and the existing `ics` source only
speaks iCalendar.

## Not worth taking

- **Grid maths.** penguin-overlord has a Maidenhead implementation, but `geo.py`
  already has one, tested against a JavaScript mirror of itself and covering
  round-trip, pole and dateline cases. No reason to swap. (Deliberately no test
  count here: a number that has to be edited every time somebody adds a test is
  a claim that rots by design.)
- **Satellite passes.** The `satellite` command turned out to be static
  reference text and AMSAT links, not orbital mechanics, so there was nothing
  to take. Pass prediction has since been written here against cached TLEs —
  see [SATELLITES.md](SATELLITES.md).
- **Everything transport-shaped.** Discord cogs, Mastodon and Bluesky posting,
  embed builders, chart rendering for social images. Different medium, no overlap.

## One thing to check on real hardware

The three codebases use **three different spellings of the NOAA F10.7 endpoint**:

| Project | Path under `services.swpc.noaa.gov/json/` |
|---|---|
| Hammunition Hill | `f107_cm_radio_flux.json` |
| solarstorm_scout | `f107_cm_flux.json` (commented "CORRECT endpoint") |
| penguin-overlord | `f10_7cm_flux.json` |

At most one of those is right, so at least two of these projects have a solar
flux source that is silently failing or falling back. This could not be verified
from the sandbox this audit was written in — outbound access to SWPC is blocked
there. Running `hamhill serve` on a machine with real internet answers it
immediately: a wrong path shows up as a `fetch failed` on the solarflux panel
within one cycle.

## Suggested order

1. ~~Settle the licence question.~~ Done — MPL-2.0 throughout.
2. Aurora and the NOAA scales — small, closes a parity gap.
3. The propagation model, with the solar-zenith fix. Closes the largest gap.
4. The band plan panel as tier 0 reference data.
5. Revisit mode inference only if the region question has a clean answer.

## Ported: the propagation model

`solarstorm_scout`'s `spaceweather.py` is now ported, with three
corrections rather than as a copy: the UTC-hour solar-noon proxy replaced
with a real solar zenith at the operator's grid square, a docstring that
disagreed with its own code reconciled against operating anchors, and
emoji split out of the return values into the panel where presentation
belongs. See [PROPAGATION.md](PROPAGATION.md).

Worth stating plainly: the proxy is not a bug in that project. It is a
global bot with no location, and `abs(utc_hour - 12)` is a reasonable
simplification when you do not have one. It becomes wrong only when
carried into a program that knows where its operator is standing.

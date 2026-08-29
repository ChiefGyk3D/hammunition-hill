# CW and Morse

Reference charts, a translator, timing, audio, and something to practise
against. **Tier 0 throughout** — reference data and arithmetic, no network, no
configuration. It appears on the Operating dashboard as soon as the collector
has started, and it works with the WAN unplugged.

That is the point rather than a side effect. The operator most likely to want a
prosign chart is the one sitting at a straight key in a field with no signal,
which is exactly when a hosted dashboard is no help.

## Where the tables live, and why

The canonical Morse tables are in `src/hammunition_hill/morse.py`, in Python,
not in the JavaScript that draws them. Two reasons:

- **They are testable there.** A Morse table is exactly the kind of data where
  one wrong character is invisible on inspection and obvious on the air. The
  tests check the standard's own structure — that every digit is five elements,
  that 1–5 add dahs from the right and 6–0 add dits, that nothing collides —
  rather than reading the table back to itself.
- **The browser receives them as data.** A panel cannot then disagree with a
  test about what `..-.` means.

The browser still implements translation and timing itself, because it has to
translate as you type and make a sound. That is a second implementation, and a
second implementation drifts — so a test runs `web/lib/morse.js` under node
against the same reference payload and compares every answer. Verified it
catches a 4% change to the dit length.

## What is in it

| View | |
|---|---|
| **translate** | Text ↔ Morse, direction detected from what you typed. Play at any speed. |
| **letters** | Letters, digits and punctuation. |
| **prosigns** | The ten that matter, with what they mean. |
| **practice** | Koch-order groups, sent as audio, revealed when you are ready. |

Q codes, operating abbreviations and cut numbers used to be views here too.
They moved to the **Pocket Reference** panel, which is where lookups belong —
this panel teaches, that one answers, and for a while both carried the same
two tables. The trainer still quizzes on all of them.

## The prosign collision, which is not a bug

Four prosigns are *the same sound* as a punctuation mark:

| Prosign | | Also |
|---|---|---|
| AR — end of message | `.-.-.` | `+` |
| AS — wait | `.-...` | `&` |
| BT — separator | `-...-` | `=` |
| KN — go ahead, named station only | `-.--.` | `(` |

Morse has no punctuation namespace; `+` and AR are one pattern and always were,
and context tells an operator which is meant. The decoder returns the
punctuation form because that is what a decoder should print, and the prosign
chart carries the other reading. There is a test pinning all four, so a future
"cleanup" that renamed one would fail rather than silently change what the
translator prints.

The same honesty applies to **Á and Å**, which genuinely share `.--.-` in
international Morse. A decoder cannot recover which was sent, and the tests say
so explicitly rather than skipping the case quietly — the round-trip test
excludes exactly that pair, and a separate test fails if any *other* collision
appears, so an accidental duplicate cannot hide in the exclusion.

## Timing

Speeds follow the standard definition: "PARIS" is 50 dit units, so one dit at
N words per minute is 1200/N milliseconds. At 20 WPM that is 60 ms, which is
the number worth remembering.

The test for this is the definition itself: sending "PARIS" N times at N WPM
must take 60 seconds, checked at 5, 13, 20, 25 and 35 WPM. If the arithmetic
drifts, the speed stops meaning what it says.

### Farnsworth

Set **effective** below **WPM** and the characters stay at full speed while the
gaps between them stretch. That is the whole idea: a learner hears the real
rhythm of a letter from the start instead of a slowed-down version they will
have to unlearn.

The extra time is distributed by the ARRL formula, which spreads it across the
character and word gaps in the same 3:7 ratio the standard gaps have — so the
result still sounds like Morse rather than like pauses. A test pins that ratio.

## Audio

A sine oscillator with a five-millisecond ramp either side of every element.

The ramp is not decoration. Keying an oscillator with a square edge produces
**key clicks** — audible as a tick either side of each dit, and on the air the
thing that earns a complaint from the next channel up. It is the same fix in
software as in hardware.

The audio context is created per playback and closed afterwards. Leaving one
open holds the audio device awake, which on a laptop in a field is battery
spent on nothing.

## The trainer

Four drills, all tier 0, all generated on your own machine. Load an item, send
it, copy what you hear, then reveal. Whatever is loaded stays hidden until you
reveal it, because that is the exercise.

### groups — the Koch method

Start with two characters at full speed, add one at a time, each chosen to be
maximally confusable with those already learned. K and M first is not arbitrary
— they are opposites, which is the point. You are always discriminating, never
merely recognising, which is why learning alphabetically does not work: A, B, C
sound nothing alike and give you no practice at the thing that is hard.

The lesson slider is the whole plan. Lesson 1 is `K M`; lesson 39 is the full
forty characters. How fast you move is between you and the key.

### callsigns — the thing you actually have to copy

A callsign goes past once. Everything else in a QSO you can ask for again.

The generator builds them from real DXCC prefixes — the same table the callsign
panel resolves against — so the shapes are real (`W1AW`, `DL1ABC`, `KH6XY`,
`9A2AA`, not five random letters) and revealing the answer also names the
entity. A prefix that already ends in a digit takes the suffix directly;
anything else takes a call area digit first. Suffix lengths are weighted so
two-letter calls dominate, because on the air they do.

### QSO — copying in context

A whole simulated contact, both sides. Only the other station is sent; your own
transmissions are shown, dimmed, so you can see where you are.

Two styles. A **contest** exchange is short and fast — `CQ TEST`, a report, a
serial, `TU`. A **ragchew** is the long form: name, QTH, RST, rig, antenna,
weather, `73 ES GL SK`. Set your own callsign and name and they appear where
they would on the air.

Context is most of what makes a real exchange readable above your cold-copy
speed. Knowing that a callsign comes next, or that `NAME` is followed by a name,
does more for your copy at 20 WPM than another week of random groups.

### quiz — the things you have to know rather than hear

Multiple choice over the phonetic alphabet, the Q-signals, and the
abbreviations. No audio: these are recall, not copy. It keeps a running score
for the session.

### Everything it can send, it can send

Every drill is checked against the encode table in the test suite — the whole
Koch order, two thousand generated callsigns, and both QSO scripts with every
field filled. A drill that emitted a character with no Morse code would send
silence where a character should be and the student would copy a gap, so the
suite walks the actual generated output rather than trusting the tables.

### The generators run twice

The curriculum lives in `src/hammunition_hill/cwpractice.py`; the generation
happens in `web/lib/cwpractice.js`, in the browser, because a trainer that asked
a server for the next callsign would stop working when the network did.

That is two implementations, and two implementations drift. Both use the same
seeded PRNG (mulberry32, written out in both languages), so a test can run the
JavaScript under node and demand the *identical* callsign, group, QSO and quiz
question for the same seed — not merely output of the right shape.

## What it does not do

- **No decoder from audio.** Decoding received CW off the air is a different
  and much harder problem than translating a string, and there are dedicated
  tools for it.
- **No keyer.** This does not key a transmitter and has no business doing so.
- **No speed learning schedule.** It gives you the Koch order and the lessons;
  how fast you add characters is between you and the key.
- **No progress tracking between sessions.** The lesson number and your settings
  are remembered; how you did is not. Storing a learning history would mean
  storing data about you, which this project does not do.

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
| **q codes** | The 21 you actually meet on the air, not the full ITU list. |
| **abbrev** | Operating shorthand, plus cut numbers. |
| **practice** | Koch-order groups, sent as audio, revealed when you are ready. |

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

## Practice

Koch method: start with two characters at full speed, add one at a time, each
chosen to be maximally confusable with those already learned. K and M first is
not arbitrary — they are opposites, which is the point.

Generate groups, send them, copy what you hear, then reveal. The groups are
hidden until you reveal them because that is the exercise.

## What it does not do

- **No decoder from audio.** Decoding received CW off the air is a different
  and much harder problem than translating a string, and there are dedicated
  tools for it.
- **No keyer.** This does not key a transmitter and has no business doing so.
- **No speed learning schedule.** It gives you the Koch order and the groups;
  how fast you add characters is between you and the key.

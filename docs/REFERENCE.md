# The pocket reference

The lookups. Q signals, CW abbreviations, the number codes, the phonetic
alphabet, RST, the calling frequencies, and a short directory of the sites
worth a bookmark — the things an operator reaches for mid-QSO and usually
reaches for a search engine to get.

Everything here is **tier 0**: static tables published by the collector at
startup, readable with the WAN unplugged, which is exactly when somebody in a
field needs to check what QSP means. The panel lives on the Operating
dashboard, with a filter box because "what was that code again" is the question
it exists to answer and scanning sixty rows is the failure it replaces.

## What it carries

| View | Contents |
|---|---|
| **q codes** | The thirty amateur Q signals, QRA through QTR. Canonical copy in `morse.py`, shared with the CW trainer's quiz. |
| **abbrev** | Prosigns (AR, SK, BT…) and the CW abbreviations — 73, ES, HI, OM, WX, FB and friends. |
| **numbers** | The number codes that survived from the wire-telegraph 92 Code of 1859: 73, 88, 55, 72, 33, 161, 30. Also why 73 takes no plural — it is a number, not a count. |
| **phonetic** | The ITU alphabet, Alfa through Zulu, digits included. |
| **RST** | Readability 1–5, Strength 1–9, Tone 1–9, each value spelled out — a 559 is not an insult, and a contest 599 is an exchange format, not a measurement. |
| **freqs** | US calling and centre-of-activity frequencies: 146.520, 446.000, the FT8 and QRP spots per band. Conventions, not regulation — Part 97 assigns no calling frequencies. |
| **links** | FCC ULS search, ARRL, RepeaterBook, PSK Reporter, the RBN, POTA, SOTA and the rest — each with what it is *for*. |

## The line between this and the CW panel

The CW panel **teaches**: Koch order, timing, drills, the quiz. This panel
**answers**. They share the same canonical tables — the Q codes and
abbreviations live in `morse.py`, tested there, published once — so the two
cannot disagree about what QRS means.

## Links are links

The links view navigates away, deliberately. A plain anchor costs nothing
under the CSP — only embedded resources need an allowance — and the dashboard
fetches nothing on anyone's behalf. Nothing in this panel causes a request to
any of the sites it lists.

## What is deliberately not here

- **Repeater listings.** They change, they are local, and RepeaterBook does it
  well — that is what the link is for. A repeater panel fed by their API is on
  the candidate list in [STATUS.md](STATUS.md).
- **Band edges.** The Band Plan panel is the reference for those, per licence
  class, and duplicating it here would give the two a chance to disagree.
- **The regulation.** Part 97 ships with the exam panel, quoted in full — see
  [EXAM.md](EXAM.md).

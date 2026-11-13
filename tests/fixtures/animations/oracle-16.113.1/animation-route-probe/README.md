# Why no animation value can be captured through the scripting dictionary

Run 2026-10-31 on PowerPoint for Mac 16.113.1 from a Terminal holding the
Automation grant. This probe exists so nobody spends another session trying to
make the oracle's animation half work.

`animation-routes.applescript` creates one scratch slide per route, each with
its own shape, attempts to create one Fade effect, counts the effects on that
slide, saves the package, and discards the working copy.

## Result: all four routes fail, nothing is created

| Route | Call | Error |
| --- | --- | --- |
| A | `add effect (main sequence of timeline of slide) for shape fx …` | `-1708` … doesn't understand the "add effect" message |
| B | `make new effect at end of (main sequence of timeline of slide)` | `-2710` Can't make class effect |
| C | `make new effect at end of (sequence 1 of timeline of slide)` | `-2710` Can't make class effect |
| D | `add effect (sequence 1 of timeline of slide) for shape fx …` | `-1728` The object you are trying to access does not exist |

`routes.jsonl` records `effectsOnSlide: 0` for every route, and `routes.pptx`
confirms it independently: four slides, one shape each, **no `p:timing` element
and no `p:cTn` anywhere in the package**.

## What this establishes

`PowerPoint.sdef` declares both routes — `add effect` with a `sequence` direct
parameter, and `effect` as an element of `sequence` with writable
`animation effect type` and `shape` properties. Neither is implemented. The
dictionary describes a capability this build does not have.

So the split is by mechanism, not by effort:

- **Transitions** are scriptable. The capture beside this directory closed
  every transition gap in one run.
- **Animations** are not scriptable at all. Every animation value — effects,
  directions, triggers, build levels, text units, behaviors, after-effects and
  motion paths — has to be applied through the GUI, following
  `scripts/animation_catalog/computer-use.md`.

Route D's `-1728` is worth noting separately: `sequence 1 of timeline` does not
exist until something has created a sequence, so an indexed sequence is not an
alternative address for `main sequence` — it is a reference to an object that
only exists once an effect does.

## Do not re-attempt

Correcting terminology, changing the addressed object, or fixing the constants
arrays cannot change this result. The constants fix landed for a different
reason (a bare enumerator name collided with a property name and aborted the
transition run); it does not make the animation probes viable.

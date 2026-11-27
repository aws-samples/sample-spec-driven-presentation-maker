---
description: "What every slide owes whatever its style and guides say — check these before calling a slide done"
tags: [composer]
always: true
---

# Verify

A style and a guide carry preferences. They can be replaced: another style wants a
different density, another guide names different forms, and any deck is free to swap both.
The rules below cannot be replaced. A slide that breaks one is wrong even when it follows
its style exactly, so check them against the slide you built rather than the slide you
meant to build.

Two families: what the drawing asserts, and whether the text is true.

## What the drawing asserts

Every visual decision makes a claim. The claim is readable in a second, before any text is,
which is why a wrong one is worse than no drawing at all: the audience believes the shape
and only later reads that the content says something else. Each element below asserts the
thing beside it. Use it when the content asserts that thing, and not otherwise.

| Element | What it asserts | Breaks when |
|---|---|---|
| An arrow | direction: this leads to, becomes, or feeds that | it points between items with no relationship, or both ways between items with one direction |
| A connector | a relationship exists between exactly these two | it ends inside a node, at a node's centre, or spans items that are merely adjacent |
| An axis, a scale, a gridline | the positions on it are measured | the positions are chosen for layout, or the axis carries no unit and no labelled ends |
| Order, left to right or top to bottom | sequence, rank, or time | the items have no order and the reading order invents one |
| Size | magnitude: this is bigger than that, by this much | sizes vary to fill space, or a 2x value is drawn 4x because both width and height grew |
| Colour | category, or one highlighted thing | every item gets its own colour and none of them means anything |
| Enclosure or shared background | these belong together and the others do not | the grouping follows the layout grid rather than the content |
| Alignment to the same line | these are the same kind of thing, comparable | items of different kinds are lined up because it looks tidy |
| An icon | the concept beside it | the icon is generic decoration, or the same icon stands for two different concepts in one deck |

Two consequences worth stating on their own:

- **A decoration that asserts nothing is noise.** Gridlines with no scale, a tick mark with
  no measurement, an arrow added for movement, a frame around something that needs no frame:
  each one costs the audience a moment of reading and returns nothing. Remove it.
- **An icon that stands for the subject is worth adding.** The opposite failure is a wall of
  unmarked text where every concept would have been recognisable at a glance. When a short
  label names a thing, give it its icon.

## Whether the text is true

The deck is read as a claim about the world, and the audience cannot check it. Nothing on a
slide may say more than the evidence behind it says.

- **Numbers come from the evidence, unchanged.** Same value, same unit, same period, same
  basis. A rounded figure says it is rounded. A number nobody can point to does not go on a
  slide.
- **Quotes are verbatim and attributed.** Trimming is allowed and marked; rewording is not.
- **No fact arrives from nowhere.** Every name, date, figure, ranking and causal claim traces
  to the brief's Sources, or to the user's own words in the brief. A plausible fact you
  supplied yourself is the one failure the audience cannot detect and the speaker cannot
  defend.
- **A gap stays a gap.** Where the outline says `[TBD]`, the slide says so too. Filling it
  with something reasonable hides the one thing the author needed to see.
- **Labels say what the thing is.** Axis labels, units, legend entries, column headers and
  footnote markers all resolve. "Other" and "Total" mean the same thing on every slide of
  the deck.
- **The headline is the slide's claim, and the slide supports it.** If the body and the
  visual do not establish the headline, either the headline overstates or the slide is
  missing its evidence. Weaken the headline or add the evidence; do not leave the gap.
- **Hedged in the source stays hedged on the slide.** An estimate, a forecast and a target
  are not results, and a slide that drops the qualifier asserts something the source did not.

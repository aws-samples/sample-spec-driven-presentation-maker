# Animation craft — whether to animate, and how much

Judgement, not mechanics. `read_guides(["animations"])` is the companion: what is authorable,
what each effect measurably writes, what survives a round trip. This one answers the question
that comes first — given that an effect *can* be written, should it be, and with what timing.

Recommendations throughout, with two exceptions that say so where they appear: a slide has to
work with motion off, and an animated deck gets checked against its storyboard frames.

---

## Pick a register first

Most published guidance on motion is from interface design, where motion is feedback for
something the user just did. A deck is not always that. Two registers, named after the thing
that actually differs — **who controls the pace**:

| | `presenter` | `cinematic` |
|---|---|---|
| pace set by | the speaker's clicks | `transition.advance.afterMs` |
| one click delivers | one idea | a whole scene |
| effects per slide | 5–15 | 10–40 |
| motion as feedback | 150–400 ms | 150–400 ms |
| motion as content | avoid — use a click instead | 1200–2600 ms, nothing else moving |
| things moving at once | one event's worth | many, choreographed by delay |
| stagger per item | 40–60 ms | 40–60 ms, or 100–120 ms when order is the content |
| scene length | n/a — the speaker decides | 4–7 s |
| default transition | `fade`, or `morph` when something persists | `morph` |
| emphasis | once per slide, to mark structure | part of the choreography |
| loops | no | yes, for ambient or propagating motion |
| exit effects | rare — the resting state is what gets read | normal — the stage changes |

Pick one before authoring and keep a deck in one register. Mixed registers read as a mistake
rather than a range.

**One consequence for the storyboard**: its warning that a slide *ends with something off
screen* is a defect in `presenter` and expected in `cinematic`, where travelling parts leave on
purpose. Read it against the register.

---

## What motion is for

Four jobs are worth an effect:

| job | what it looks like | the sdpm shape |
|---|---|---|
| **orient** | what changed between two slides | `morph` transition, shared `morphId` |
| **focus** | which of these matters now | one `emphasis`, or `afterEffect` dim on what no longer does |
| **connect** | A caused B; this is the same thing as that | a `motion` path between them |
| **pace** | one idea at a time | a click step, `start.type: "onPageClick"` |

An effect doing none of them is decoration, and that is the best-evidenced point in the area.
Mayer's **coherence principle** — leaving extraneous material out helps learning — held in all
23 experimental comparisons the review summarises, median effect size around 0.86:
[Mayer, *Using multimedia for e-learning*](https://doi.org/10.1111/jcal.12197),
[Mayer & Moreno on cognitive load](https://www.sfu.ca/~jcnesbit/EDUC220/ThinkPaper/MayerMoreno2002.pdf).

The same work licenses emphasis rather than forbidding it: the **signaling principle** says
cueing the structure helps. The test is whether someone who missed the motion also missed the
point. Edward Tufte's
[critique of slideware](https://www.edwardtufte.com/book/the-cognitive-style-of-powerpoint-pitching-out-corrupts-within/)
is worth reading as a reason to justify each effect, not as a reason to avoid motion.

---

## Duration

The interface-design numbers, which are the best measured available:

| length | reads as | source |
|---|---|---|
| ~100 ms | instantaneous, directly caused | [NN/g, response-time limits](https://www.nngroup.com/articles/response-times-3-important-limits/) |
| 150–200 ms | a small change — fade, colour, selection | [Material, duration & easing](https://material.io/archive/guidelines/motion/duration-easing.html) |
| 225 ms | entering or leaving the frame | [Material, movement](https://material.io/archive/guidelines/motion/movement.html) |
| 300–400 ms | a larger move | [Material motion](https://material.io/archive/guidelines/motion/material-motion.html) |
| outside that band | sluggish, or too fast to follow | Material, as above |
| ~1 s | limit for a train of thought to stay unbroken | NN/g, as above |
| ~10 s | limit for attention to stay on one thing | NN/g, as above |

Set with `timing.durationMs`. A gallery preset carries its own measured default, so omitting it
is a legitimate choice.

### The adjustment this repo makes

**Not cited — derived from the decks here, offered as a working rule, not a measured finding.**

Those numbers describe motion that is *feedback*. Presentation motion is sometimes the
*content*: when an object crosses the slide to show a distance exists, the crossing is the
argument, and 400 ms is too fast to read as travel. The decks here needed 1600–2600 ms for
that, and shortening them erased the point.

- **Feedback** — something appeared, was emphasised, receded. Under 400 ms.
- **Content** — the movement is what the slide asserts. Take the time it needs, and move
  nothing else meanwhile. One long motion reads; two at once is noise.

Test: if you can state the slide's point without mentioning the movement, it is feedback.

---

## Easing

Published guidance is written as cubic-bézier curves. PowerPoint has no bézier easing — only
`timing.acceleration` and `timing.deceleration`, each the fraction of the duration spent
ramping. The translation:

| intent | sdpm |
|---|---|
| ease-out — arriving, settling | `deceleration: 0.5`, `acceleration: 0` |
| ease-in — leaving | `acceleration: 0.5`, `deceleration: 0` |
| ease-in-out — passing through | both ≈ 0.3 |
| overshoot | not expressible as easing — see the *overshoot* and *anticipation* recipes |
| spring | does not exist here |

0.5 is not arbitrary: PowerPoint's own Smooth Start and Smooth End record exactly that.

Two recommendations: ease anything that travels a distance (a fade does not need it), and make
entering and leaving asymmetric — arrive decelerating, leave accelerating. That asymmetry is
Material's, and the shape
[NN/g recommends for UI animation](https://www.nngroup.com/articles/animation-duration/).

---

## Recipes

Each verified by building and reading back. Paths are slide fractions, relative to where the
element is authored.

| want | write | register |
|---|---|---|
| settle into place | `motion` `M 0 0.03 L 0 0 E` + entrance fade `withPrevious` | both |
| overshoot | `motionPath` preset + `timing.bounceEnd` (0–1; paths only, ignored elsewhere) | both |
| anticipation | one `motion` whose first leg reverses: `M 0 0 L -0.012 0 L 0.25 0 E` | cinematic |
| follow-through | child in the parent's step, `delayMs` +150, slightly longer duration | both |
| a line drawing itself | entrance `wipe`, `options.direction: "fromLeft"` | both |
| two directions at once | opposing `motion` paths in one click step | cinematic |
| camera move | one stage with shared `morphId`s, reframed per slide | cinematic |
| ambient loop | slow `scale` + `repeatCount` + `autoReverse` | cinematic |
| a group arriving | same effect on each, `withPrevious`, `delayMs` stepped 40–60 ms | both |
| something propagating | same, stepped 100–120 ms — the step *is* the speed | cinematic |

---

## Choreography

Firing a group together makes many objects look like one event. Staggering makes them look like
a group of things, which is usually what was meant. Join with `start.type: "withPrevious"`,
offset with `start.delayMs`.

**Measured in this repository, not cited:** 40–60 ms per item for a set arriving as one group;
100–120 ms when the *order* is the content. The second is the interesting case — when a brake
wave travels back through a queue, the delay between items is the propagation speed and nothing
else on the slide encodes it.

Follow-through is what keeps a group from looking stiff: a child finishing slightly after its
parent, which is the
[overlapping action](https://www.adobe.com/in/creativecloud/roc/blog/video/animation-principles.html)
principle and costs one `delayMs`.

If everything is moving, nothing is emphasised. When a step has many simultaneous effects,
check they are one event rather than several competing ones.

---

## Pacing the build

Mayer's **segmenting principle**: people do better with material in segments they control than
as one continuous run. That is the argument for click-paced builds, and against packing a slide
into one click.

- `presenter`: one idea per click. A click revealing a tile with its icon and caption is one
  idea; three unrelated tiles is three.
- `cinematic`: a click per scene, then `transition.advance.afterMs`. This gives up the
  audience's control deliberately — right for unattended playback, wrong for a room, where the
  presenter's pace *is* the segmenting.

The number of `onPageClick` effects is the number of times someone has to act. The storyboard's
frame count is the honest measure of it.

---

## Morph

[Microsoft's guidance](https://support.microsoft.com/en-us/office/use-the-morph-transition-in-powerpoint-8dd1c7b2-b935-44f5-a74c-741d8d9244ea)
and [Morph tips](https://support.microsoft.com/en-us/office/bc7f48ff-f152-4ee8-9081-d3121788024f)
give two facts that change authoring:

1. Morph needs at least one object the two slides share. Without one it degenerates to a
   cross-fade.
2. Two objects on successive slides given the same custom name beginning with two exclamation
   marks are matched rather than guessed at. **That mechanism is what `morphId` writes** —
   setting the same `morphId` on both slides is the supported way to say "same object", and
   omitting it leaves PowerPoint guessing silently.

- Use Morph when something **persists and changes**. Entirely new content is a cut; a plain
  transition is more honest about that.
- `byObject` morphs shapes; `byWord` and `byChar` morph text. Use the text variants when a line
  genuinely becomes another line, not to make a heading change look expensive.
- A Morph carrying one stage across several slides reads as a continuous shot. That is its
  strongest use, and the reason to keep a deck's framing consistent.

---

## Text in motion

Text has a constraint shapes do not: it has to be read. Keep it
[readable in its final state as early as possible, so nobody waits for motion to finish before
they can read](https://tidewave.net/blog/kinetic-typography-animating-text-without-hurting-usability).

- Body copy: `text.level` builds and the *settle* recipe. Never per-character motion.
- Headings: `byChar` morph only when one line really transforms into another.
- Anything a reader must hold in mind while reading: no motion at all.

---

## Motion is never the only carrier

The one section stating a hard requirement rather than a preference.

[WCAG success criterion 2.3.3, Animation from Interactions](https://www.w3.org/WAI/WCAG21/Understanding/animation-from-interactions)
asks that non-essential motion from interaction can be switched off, for a physical reason: the
W3C's [reduced-motion technique](https://www.w3.org/WAI/WCAG22/Techniques/css/C39) notes that
moving content can trigger vestibular reactions — distraction, dizziness, nausea. Audiences can
act on it: Office honours the operating system's animation setting and has its own switch, so a
deck may simply be shown without its builds —
[turning off Office animations](https://support.microsoft.com/en-us/office/graphics-visuals/turn-off-office-animations).

So the expectation in the animations guide — a slide carries its whole meaning with motion off
— is not house style. It is the only assumption that survives a real audience, and it is
checked.

- Never encode a distinction **only** as motion.
- A build whose final state is incomplete is broken, not minimal.
- This holds in `cinematic` too. A deck that plays itself still has to be legible paused.

---

## Patterns that went wrong in this repository

Each passed a clean build, a full round trip, the layout checks and the lint, and was found only
by looking at storyboard frames.

| what happened | why it is wrong | instead |
|---|---|---|
| An icon had no entrance while its tile faded in | It floats in empty space until the tile arrives | Give every child an entrance in its parent's step, `withPrevious` |
| `afterEffect: hide` on a build's last step | The slide rests with a hole where content was | Hide only when something takes the space |
| `hideOnNextClick` on a tile nothing replaced | Same hole, one click later, with an orphaned icon in it | As above |
| A dim fired as its tile appeared, and never lifted | Introduced and discarded in one motion; the deck rests dimmed | Dim when the *next* thing takes focus, and only if that element should stay receded |
| A motion path moved a decorative icon a few hundred pixels | Motion with no referent | Delete it, or move something whose movement is the content |

The shape of all five: **the resting state is what most people actually read.** Check the last
storyboard frame first.

---

## Verifying

Build, render the storyboard, look at the frames — `read_guides(["animations"])` has the call.
Three questions the frames answer and a build log cannot:

1. **Frame 0** — is anything visible that should not be yet?
2. **The last frame** — is it the whole slide? (In `cinematic`, is it the intended end state?)
3. **Middle frames** — does each read, or is it a state nobody was meant to see?

A still frame cannot show an emphasis that returns to where it started; the storyboard names
those per frame rather than staying silent. A slide whose only motion is that kind will have
identical frames, which is itself worth noticing.

---

## Sources

- [Material Design — duration & easing](https://material.io/archive/guidelines/motion/duration-easing.html),
  [material motion](https://material.io/archive/guidelines/motion/material-motion.html),
  [movement](https://material.io/archive/guidelines/motion/movement.html),
  [Material 3 easing and duration](https://m3.material.io/styles/motion/easing-and-duration)
- [NN/g — executing UX animations](https://www.nngroup.com/articles/animation-duration/),
  [response-time limits](https://www.nngroup.com/articles/response-times-3-important-limits/)
- [Mayer, *Using multimedia for e-learning*](https://doi.org/10.1111/jcal.12197),
  [Mayer & Moreno](https://www.sfu.ca/~jcnesbit/EDUC220/ThinkPaper/MayerMoreno2002.pdf) —
  coherence, signaling, segmenting
- [W3C — Animation from Interactions](https://www.w3.org/WAI/WCAG21/Understanding/animation-from-interactions),
  [reduced-motion technique](https://www.w3.org/WAI/WCAG22/Techniques/css/C39)
- Microsoft — [using Morph](https://support.microsoft.com/en-us/office/use-the-morph-transition-in-powerpoint-8dd1c7b2-b935-44f5-a74c-741d8d9244ea),
  [Morph tips](https://support.microsoft.com/en-us/office/bc7f48ff-f152-4ee8-9081-d3121788024f),
  [turning off Office animations](https://support.microsoft.com/en-us/office/graphics-visuals/turn-off-office-animations)
- [Adobe — the 12 animation principles](https://www.adobe.com/in/creativecloud/roc/blog/video/animation-principles.html)
  for overlapping action and follow-through
- [On animating text without hurting readability](https://tidewave.net/blog/kinetic-typography-animating-text-without-hurting-usability)
- [Duarte on pushing PowerPoint animation](https://www.duarte.com/blog/designer-qa-pushing-the-limits-of-powerpoint-animation/)
  — an elaborate sequence usually decomposes into shapes changing size and position, which is
  what `motion` and `scale` give you
- [Tufte on the cognitive style of slideware](https://www.edwardtufte.com/book/the-cognitive-style-of-powerpoint-pitching-out-corrupts-within/)

Every point drawn from these is summarised in this guide's own words rather than quoted; follow
a link for the original wording and the full argument. Content was rephrased for compliance with
licensing restrictions. The sections marked as derived — the feedback-versus-content split on
duration, the stagger intervals, and the register table — are this repository's own working
rules, measured on the decks here, and carry no external authority.

## Related guides

- `read_guides(["animations"])` — what is authorable, what each effect measurably does, what
  survives import.
- `read_guides(["design-rules"])` — the non-motion half of the same judgement.
- `read_guides(["storytelling-vocabulary"])` — naming what a slide is for before deciding how it
  should move.

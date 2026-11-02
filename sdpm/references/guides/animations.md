---
name: animations
description: "Object animations and slide transitions — deck switches, slide JSON contract, effect and transition catalogs, Morph, and what round-trips today"
category: guide
---

# Animations and Transitions

The canonical contract for object animations (PowerPoint's Animation Pane) and slide
transitions (PowerPoint's Transitions tab). Load it only when you need it:

- `deck.json` has `"animations": {"enabled": true}` or `"transitions": {"enabled": true}`, or
- a slide you were assigned already carries a `transition` or `animations` field.

With neither switch enabled and no such field on your slides, nothing in this guide applies
and you should not load it — a still deck is the default and stays the default.

## Rule — the slide must carry its whole meaning with motion off

Animation is a second reading of a slide that is already complete. No claim, number, label,
caveat, source or instruction may exist **only** in an animated state.

- Both switches can be off at generation time, and then no timing and no transition is
  written at all. The deck still has to be correct.
- PDF export, print and every static preview (PNG / SVG / WebP) render one frame per slide.
  sdpm never plays animation in a preview.
- A motion-path effect that moves a label into place, an entrance that reveals the only copy
  of a number, an emphasis that is the only thing distinguishing the current step — all three
  are defects. Put the content on the slide and let the animation order attention, not supply
  it.
- Progressive disclosure that must survive statically is a job for `override` slides (see the
  slide JSON spec): one slide per build step, each one complete on its own. Use animation for
  live delivery polish on top of that, never instead of it.

If you cannot phrase what a slide says without referring to motion, the slide is wrong, not
the animation.

## Deck switches

`deck.json` carries the two switches and nothing else about motion — no deck-wide timeline,
no deck-wide transition.

```json
{
  "animations": {"enabled": false},
  "transitions": {"enabled": false}
}
```

- Both fields are optional. An absent switch means disabled, so a deck written before this
  feature existed builds exactly as it did before.
- `enabled` must be a boolean, and `animations` / `transitions` accept no other key.
- `animations.enabled` and `transitions.enabled` are independent: transitions on with
  animations off is a normal configuration, and so is the reverse.
- A new PPTX import writes each switch from the content it detected. Hand-edit sync keeps a
  switch the user set explicitly and derives only a missing one.

Generation accepts an independent override per feature, `inherit | on | off`, on the public
API, the CLI and both MCP servers. Precedence is **caller override → deck switch → `false`**,
and no override ever rewrites `deck.json`.

What "off" does:

| Off switch | Effect |
|---|---|
| `animations` | No object-animation timing is written, semantic or raw. Timing needed for supported media playback is still written, so a video keeps playing. |
| `transitions` | No `p:transition` is written. Object and media timing are untouched. |

## Where motion lives

Each slide's motion lives in that slide's own JSON file, `slides/<slug>.json`:

```json
{
  "layout": "Title Only with Left Line",
  "placeholders": {"0": "Introduction"},
  "notes": "...",
  "transition": { },
  "animations": { },
  "elements": [ ]
}
```

A `transition` describes how **its own slide enters**, matching PowerPoint's storage model.
Omitting `transition` means that slide has no transition. PowerPoint's *Apply to All* is
represented by writing the same `transition` object into every slide file; it is not deck
state.

## Target identity

Every animatable target needs a slide-local `id`. Put it on the element (or on the
placeholder's object form) that produces the shape:

```json
{"type": "shape", "id": "details-button", "shape": "rounded_rectangle", "x": 100, "y": 200, "width": 300, "height": 90, "text": "Details"}
```

```json
"placeholders": {"0": {"text": "Introduction", "id": "title"}}
```

- `id` must match `^[A-Za-z][A-Za-z0-9._-]*$` and be unique within the slide **after**
  `include` and `override` expansion. A duplicate is a lint error naming both paths.
- The same `id` may be reused on different slides.
- `include` entries carry no identity themselves; the elements they expand to do.
- Generated shapes carry recoverable sdpm identity in non-visual shape metadata. Your
  accessibility title and description are never used for it and are never overwritten.
- An animation naming an unknown `id` is a build error naming the slide, the sequence, the
  effect and the target. Generation fails before a PPTX is reported.

### `morphId`

An element may also declare a deck-wide `morphId`. Equal `morphId` values on adjacent slides
make PowerPoint's Morph match those two objects deterministically.

```json
{"type": "shape", "id": "card-1", "morphId": "pricing-card", "shape": "rounded_rectangle", "x": 100, "y": 200, "width": 400, "height": 200}
```

- Same character rules as `id`; must be unique **within one slide** (two shapes on one slide
  cannot claim the same Morph identity).
- It is stored in the PowerPoint-preserved non-visual shape name convention, separately from
  `id`, and survives JSON → PPTX → JSON.
- Without `morphId`, matching is left to PowerPoint's own heuristics. sdpm does not invent a
  match.

## `transition`

```json
{
  "transition": {
    "effect": "morph",
    "parameters": {"variant": "byObject"},
    "durationMs": 800,
    "advance": {"onClick": true, "afterMs": null},
    "sound": null
  }
}
```

| Field | Value |
|---|---|
| `effect` | A catalog effect slug from the table below. Required. |
| `parameters` | The effect's option set. Must be one of the sets the catalog records for that effect; anything else fails with the supported sets listed. Omit for the effect's default. |
| `durationMs` | Positive number of milliseconds. Omit to take the effect's own default. |
| `advance.onClick` | Boolean. `false` writes `advClick="0"` (advance only on time). |
| `advance.afterMs` | Non-negative milliseconds, or `null` for no timed advance. |
| `sound` | Must be `null`. See *Not authorable today*. |

### Transition effects and their option sets

Every row is authorable. `{}` is the effect's default option set; each further set is an
alternative value of `parameters`. Parameter names are the persisted option names.

| Effect | Option sets for `parameters` |
|---|---|
| `airplane` | `{}` |
| `blinds` | `{}`, `{"dir": "horz"}` |
| `box` | `{}` |
| `checker` | `{}`, `{"dir": "vert"}` |
| `clock` | `{}`, `{"spokes": "2"}`, `{"spokes": "3"}`, `{"spokes": "4"}`, `{"spokes": "8"}`, `{"spokes": "1", "reverse": "1"}` |
| `comb` | `{}`, `{"dir": "vert"}` |
| `conveyor` | `{}` |
| `cover` | `{}`, `{"dir": "d"}`, `{"dir": "ld"}`, `{"dir": "lu"}`, `{"dir": "r"}`, `{"dir": "rd"}`, `{"dir": "ru"}`, `{"dir": "u"}` |
| `crush` | `{}` |
| `cube` | `{}` |
| `curtains` | `{}` |
| `cut` | `{}`, `{"thruBlk": "1"}` |
| `diamond` | `{}` |
| `dissolve` | `{}` |
| `doors` | `{}` |
| `drape` | `{}` |
| `fade` | `{}`, `{"thruBlk": "1"}` |
| `fallOver` | `{}` |
| `ferris` | `{}` |
| `flash` | `{}` |
| `flip` | `{}` |
| `flythrough` | `{}` |
| `fracture` | `{}` |
| `gallery` | `{}` |
| `glitter` | `{}` |
| `honeycomb` | `{}` |
| `morph` | `{"variant": "byObject"}`, `{"variant": "byWord"}`, `{"variant": "byChar"}` |
| `newsflash` | `{}` |
| `orbit` | `{}` |
| `origami` | `{}` |
| `pageCurl` | `{}` |
| `pan` | `{}` |
| `peelOff` | `{}` |
| `plus` | `{}` |
| `prestige` | `{}` |
| `push` | `{}`, `{"dir": "d"}`, `{"dir": "l"}`, `{"dir": "r"}` |
| `random` | `{}` |
| `randomBar` | `{}`, `{"dir": "horz"}` |
| `reveal` | `{}` |
| `ripple` | `{}` |
| `rotate` | `{}` |
| `shape` | `{}` |
| `shred` | `{}` |
| `split` | `{}`, `{"dir": "in"}`, `{"dir": "in", "orient": "horz"}`, `{"dir": "out"}`, `{"dir": "out", "orient": "horz"}` |
| `strips` | `{}`, `{"dir": "lu"}`, `{"dir": "rd"}`, `{"dir": "ru"}` |
| `switch` | `{}` |
| `uncover` | `{}`, `{"dir": "d"}`, `{"dir": "ld"}`, `{"dir": "lu"}`, `{"dir": "r"}`, `{"dir": "rd"}`, `{"dir": "ru"}`, `{"dir": "u"}` |
| `vortex` | `{}` |
| `wedge` | `{}` |
| `wind` | `{}` |
| `window` | `{}` |
| `wipe` | `{}`, `{"dir": "d"}`, `{"dir": "r"}`, `{"dir": "u"}` |
| `zoom` | `{}` |

An option a PowerPoint menu offers but this table does not is not authorable: the writer
refuses it with the supported sets rather than writing the effect's default and dropping
your choice.

### One parameter names an element rather than an attribute

`clock` with `{"spokes": "1", "reverse": "1"}` is the only option set whose parameters are not
the attributes that get written. PowerPoint persists a reversed Clock as

```xml
<mc:AlternateContent>
  <mc:Choice Requires="p14"><p14:wheelReverse spokes="1"/></mc:Choice>
  <mc:Fallback><p:fade/></mc:Fallback>
</mc:AlternateContent>
```

so "reverse" is carried by the **element name**, and `p14:wheelReverse` has no `reverse`
attribute at all. Pass `reverse` anyway: it is how the value is selected, and the writer emits
the element with `spokes` alone. Reading the package back returns the same two parameters.

Every other effect selects by exactly the attributes it writes. The catalog records the
difference per entry as `ooxml.selectorAttributes` beside `ooxml.attributes`, so nothing has to
special-case Clock by name.

### Morph

Morph is a transition on the **destination** slide plus object correspondence across the two
slides.

```json
// slides/pricing-1.json
{
  "elements": [{"type": "shape", "id": "card", "morphId": "pricing-card", "shape": "rounded_rectangle", "x": 200, "y": 300, "width": 400, "height": 200}]
}
```

```json
// slides/pricing-2.json
{
  "transition": {"effect": "morph", "parameters": {"variant": "byObject"}},
  "elements": [{"type": "shape", "id": "card", "morphId": "pricing-card", "shape": "rounded_rectangle", "x": 1200, "y": 300, "width": 500, "height": 400}]
}
```

- `variant` is required for `morph` and must be `byObject`, `byWord` or `byChar`. All three
  are authorable and all three survive import.
- `byObject` morphs whole shapes; `byWord` and `byChar` morph text at word and character
  granularity.
- Put the same `morphId` on both the source and the destination shape. Matched objects
  transform; unmatched objects cross-fade.
- The transition goes on the destination slide only. The source slide needs no `transition`.

## `animations`

```json
{
  "animations": {
    "mainSequence": [
      {
        "id": "show-title",
        "target": {"element": "title"},
        "preset": {"category": "entrance", "effect": "fade"},
        "start": {"type": "onPageClick", "delayMs": 0},
        "timing": {"durationMs": 500},
        "afterEffect": {"type": "none"},
        "sound": null
      }
    ],
    "interactiveSequences": [
      {
        "id": "details-sequence",
        "trigger": {"type": "onShapeClick", "target": "details-button"},
        "effects": []
      }
    ]
  }
}
```

- `mainSequence` is PowerPoint's main timeline. `interactiveSequences` is one entry per
  trigger shape. Both are arrays and **array order is effect order**.
- Every effect needs an `id` matching `^[A-Za-z][A-Za-z0-9._-]*$`, unique across the whole
  slide (main and interactive sequences share one ID space). The ID is what diff and
  reordering compare, and it survives generation, a PowerPoint open/save, import and
  regeneration — it is written into a PowerPoint-preserved extension on the effect's timing
  node, and derived deterministically from (sequence kind, logical target, normalized effect,
  ordinal among identical effects) when that extension is gone.
- `animations` and the internal `_rawTiming` are mutually exclusive on one slide, as are
  `transition` and `_rawTransition`. A slide carrying both fails lint rather than applying
  both.

### One effect

| Field | Value |
|---|---|
| `id` | Required stable effect ID. |
| `target.element` | Required. The logical `id` of the shape to animate. |
| `target.paragraphRange` | Optional `{"start": 0, "end": 2}` — animate a paragraph range of the target's text instead of the whole shape. |
| `preset` | `{"category", "effect"}` from the preset table. Exactly one of `preset` or `behaviors` per effect. |
| `behaviors` | The advanced form: an explicit list of PowerPoint behavior primitives. See below. |
| `start` | `{"type", "delayMs", "target"}`. See *Triggers*. |
| `timing` | See *Timing*. |
| `afterEffect` | `{"type": "none"}`. Any other value is refused — see *Not authorable today*. |
| `sound` | Must be `null`. Refused — see *Not authorable today*. |
| `text` | Paragraph/word/character build options. See *Builds*. |
| `chart.build` | Chart build. See *Builds*. |
| `smartArt.build` | SmartArt / diagram build. See *Builds*. |

### Presets

`preset.category` is one of `entrance`, `emphasis`, `exit`, `motionPath`, `media`, `custom`.
`preset.effect` is a catalog effect name. Only these are authorable today:

| Category | Authorable effects |
|---|---|
| `entrance` | `appear`, `basicSwivel`, `basicZoom`, `blinds`, `boomerang`, `bounce`, `centerRevolve`, `checkerboard`, `credits`, `curveUp`, `dissolveIn`, `drop`, `expand`, `fade`, `flip`, `float`, `floatIn`, `flyIn`, `growTurn`, `peekIn`, `pinwheel`, `randomBars`, `riseUp`, `shape`, `spinner`, `spiralIn`, `split`, `stretch`, `strips`, `swivel`, `wedge`, `wheel`, `whip`, `wipe`, `zoom` |
| `exit` | `basicSwivel`, `basicZoom`, `blinds`, `boomerang`, `bounce`, `centerRevolve`, `checkerboard`, `collapse`, `contract`, `credits`, `curveDown`, `disappear`, `dissolveOut`, `drop`, `fade`, `flip`, `float`, `floatOut`, `flyOut`, `peekOut`, `pinwheel`, `randomBars`, `shape`, `shrinkTurn`, `sinkDown`, `spinner`, `spiralOut`, `split`, `stretchy`, `strips`, `swivel`, `wedge`, `wheel`, `whip`, `wipe`, `zoom` |
| `emphasis` | `blink`, `boldFlash`, `boldReveal`, `brushColor`, `colorPulse`, `complementaryColor`, `complementaryColor2`, `contrastingColor`, `darken`, `desaturate`, `fillColor`, `fontColor`, `growShrink`, `growWithColor`, `lighten`, `lineColor`, `objectColor`, `pulse`, `shimmer`, `spin`, `teeter`, `transparency`, `underline`, `wave` |
| `motionPath` | `arcs`, `bounce`, `invertedShape`, `lines`, `loops`, `shapes`, `specialCurve`, `specialShape`, `spiral`, `star`, `turns`, `waves` |
| `media` | `mediaPlay` |
| `custom` | none ever |

That is the whole Animations ribbon: 35 entrance, 36 exit, 24 emphasis and 12 of the Path
Animation popup's 16 entries — its Basic group of 5 and its Complex group of 7. The remaining
four are `Draw Curve`, `Draw Freeform`, `Draw Line` and `Draw Scribble`, which are drawn on the
canvas and so have no fixed geometry to write. `emphasis` and `motionPath` used to have none at all, and the gallery tiles were
refused by name, because the available evidence recorded *which* behaviour children each tile
writes and not what they say. A capture of every GUI-addressable value on 2026-11-01 measured
the payloads from the package PowerPoint saved, so each of these effects is now written as
PowerPoint writes it — including the motion-path geometry, which is transcribed rather than
re-derived.

`custom` is not a gallery — it is the advanced form, written with a `behaviors` list; a custom
motion path is a `motion` behavior.

#### Which effect does what

A name does not say what moves. `Boomerang` and `Whip` both move and resize, `Teeter` rotates,
`Stretch` resizes without moving. This is derived from the measured behaviours, so it says what
each effect actually writes rather than what its name suggests:

| what it changes | effects |
| --- | --- |
| recolours | brushColor, colorPulse, complementaryColor, complementaryColor2, contrastingColor, darken, desaturate, fillColor, fontColor, growWithColor, lighten, lineColor, objectColor |
| moves + follows a path | arcs, invertedShape, lines, loops, motionPath.bounce, shapes, specialCurve, specialShape, spiral, star, turns, waves |
| resizes + fades | contract, expand, growTurn, pinwheel, pulse, shrinkTurn, spinner, stretchy, swivel, zoom |
| wipes/dissolves | blinds, checkerboard, randomBars, shape, split, strips, wheel, wipe |
| moves + fades | centerRevolve, float, floatIn, floatOut, riseUp, sinkDown |
| resizes | basicSwivel, basicZoom, collapse, growShrink, stretch |
| moves | credits, drop, flyIn, flyOut |
| restyles text | boldFlash, boldReveal, underline |
| moves + follows a path + resizes + fades | curveDown, curveUp |
| moves + resizes | spiralIn, spiralOut |
| moves + resizes + fades | boomerang, whip |
| moves + resizes + wipes/dissolves | entrance.bounce, exit.bounce |
| moves + wipes/dissolves | peekIn, peekOut |
| rotates | spin, teeter |
| appears/disappears | blink |
| fades | transparency |
| moves + resizes + rotates | flip |
| moves + rotates + follows a path | wave |
| moves + rotates + resizes | shimmer |

A name is bare where it means the same thing in every category it appears in, and qualified
where it does not: `entrance.bounce` moves and resizes, `motionPath.bounce` follows a curve.

For the detail — every behaviour an effect writes, with its keyframes, durations and each of
its options — call the **`describe_effects`** tool. With no arguments it returns this table;
with `effect="flyIn"` it returns the expression:

```
set(style.visibility: -> visible)@1
anim(ppt_x: 1+#ppt_w/2 -> #ppt_x)@500
anim(ppt_y: #ppt_y -> #ppt_y)@500
```

`@` is a duration in milliseconds, `+` a delay, and `#ppt_w` the shape's own width. So
`1+#ppt_w/2` is half a shape-width past the right edge of a slide one unit wide — which is what
"from the right" means, and is not a thing to guess at. Ask about the two or three effects you
are choosing between rather than reading all 209 expressions: together they are about 9,000
tokens, and one is about 300.

#### Prefer a `preset`; reach for `behaviors` only when no effect fits

Both forms are authorable and they are not interchangeable.

A `preset` writes bytes PowerPoint was measured producing, carries a `presetID` so PowerPoint
names the effect in its own UI, and **comes back as the same JSON on import**.

A `behaviors` list also comes back as the same JSON — each of the eight primitives is inverted,
and all eight round-trip byte-for-byte. What it does not carry is a `presetID`: PowerPoint plays
the list but does not name the effect in its own UI, and its Effect Options do not apply. It is
also unverified, which is the substantive difference: the writer transcribes a preset's measured
values, while a composed list is whatever the caller wrote, and the idioms are not obvious.
`1+#ppt_w/2` scales with the shape; a plausible-looking constant does not.

Two spellings normalise rather than survive, because the package does not carry the difference.
A colour comes back as six digits with no leading `#`, and `command` + `value` come back split
at the bracket however they were written. Both forms write the same bytes; import returns the
canonical one.

So: pick a preset when one fits the intent, and compose only when none does. For a deck that is
generated once and never reopened the round-trip cost does not bite — but `import_attachment`
and the hand-edit diff both read animations back, so a deck that will be re-imported should use
presets.

#### `preset.options` — the effect's own settings

Picking a tile is not the whole choice. 33 of the effects above carry a setting of their own,
the one PowerPoint shows under **Animations ▸ Effect Options**, and `preset.options` names it:

```json
{"preset": {"category": "entrance", "effect": "flyIn", "options": {"direction": "fromRight"}}}
{"preset": {"category": "entrance", "effect": "wheel",  "options": {"spokes": "spokes4"}}}
{"preset": {"category": "emphasis", "effect": "spin",   "options": {"amount": "twoSpins"}}}
{"preset": {"category": "emphasis", "effect": "transparency", "options": {"amount": "percent25"}}}
```

There are **133 values over 6 settings** — `direction` (87), `amount` (12), `zoom` (12),
`spokes` (10), `shapes` (8) and `vanishingPoint` (4) — and every one was applied in PowerPoint
and read back out of the saved package. Omit `options` to get the effect's default.

**The values are per effect.** Fly In's `fromRight` and Stretch's `fromRight` are different
measurements, so there is no global list of directions: ask the catalog entry, or read the
error, which names what the effect you asked for actually offers.

```
mainSequence[0].preset.options.direction 'sideways' is not a measured value of
'animation.gallery.entrance.flyIn''s 'Direction'; it offers ['fromBottom', 'fromBottomLeft',
'fromBottomRight', 'fromLeft', 'fromRight', 'fromTop', 'fromTopLeft', 'fromTopRight']
```

**One setting at a time.** Four effects offer two settings at once — `emphasis.growShrink` and
`emphasis.spin` (`amount` + `direction`), `entrance.shape` and `exit.shape` (`direction` +
`shapes`). Each value was measured with the other setting left at its default, so the
combinations were never applied and asking for both is refused rather than composed. Spin's
direction is the *sign* of `p:animRot/@by` and its amount is the magnitude; writing
`counterclockwise` + `twoSpins` would mean inventing `-43200000`, which PowerPoint was never
observed to write.

**`preset.variant` is gone** (a leftover `"variant": null` is ignored; any other value fails).
It took one of the 45 `MsoAnimDirection` scripting names and
never worked — any value at all was refused — and the capture showed why that vocabulary could
not be made to work: 33 of its 45 names are not offered by any gallery tile, 24 of the 36
labels the tiles do offer have no name in it, and the same label means different subtypes on
different effects. Writing `variant` now fails with a pointer to `options`, and one of its old
names fails with the reason.

All 133 round-trip. Import recognises an option two ways, because one is not enough: 87 change
`presetSubtype` and are found by it, and the other 46 do not — Spin's two directions are both
subtype 0, Grow/Shrink's amounts differ only in `p:animScale/p:by`, Transparency's in
`p:animEffect/@prLst` — so those are found by comparing the behaviours. The comparison is an
exact match on the measured bytes, not a nearest one, because the writer transcribes them.

A value that **is** its effect's default reads back without `options`, which is the same JSON
it was written from. That is also why a default is never matched by behaviour: it has the same
bytes as the effect alone, so matching it would label every plain preset with an option nobody
asked for.

A `media` command other than `mediaPlay`, and a custom motion path, are still refused by name
rather than approximated. Asking for one fails with its catalog key:

```
motionPath effect 'custom' cannot be generated: catalog entry
'animation.gallery.motionPath.custom' is semantic-preservation-only (<recorded gap>).
Capture it with the PowerPoint oracle (Task 8); sdpm refuses to approximate it.
```

### `timing.durationMs` on a gallery preset

A preset's behaviours are measured at one duration, and the catalog says which:
`ooxml.measuredDurationMs`. Leave `durationMs` out and that duration is written, byte for byte
as PowerPoint wrote it. Give a different one and every animated behaviour's duration and delay
is scaled in proportion, which is what PowerPoint itself does — measured over 41 behaviours at
three ratios. Two details come with it:

- the discrete visibility toggle does not scale: it stays at 1 ms, and on an exit it is placed
  at `durationMs - 1`, which is how PowerPoint places it at every duration;
- a scaled value can differ from PowerPoint's by **1 ms**, and only where the exact product
  lands on a half. PowerPoint rounds those with its own internal float precision, which is not
  reproducible from the integers; every other value matches exactly.

`boldReveal` and `transparency` have no numeric duration at all — PowerPoint shows `Auto` and
writes `indefinite` — so a `durationMs` on either is **refused** rather than ignored. Omit it.

An option changes the duration basis with it. A setting is measured on its own capture, so
`options` carries its own measured duration and `durationMs` scales against that rather than
against the tile's — which is what lets the 19 effects with no measured duration of their own
be written at any duration once an option names one.

### Triggers

`start.type` is one of:

| `type` | Meaning |
|---|---|
| `onPageClick` | Starts a new click group — runs on the next click on the slide. |
| `withPrevious` | Joins the current start group — runs together with the previous effect. |
| `afterPrevious` | Opens a new start group inside the current click group — runs when the previous one finishes. |
| `onShapeClick` | Runs when a shape is clicked. Only valid inside `interactiveSequences`. |
| `none` | Refused — see *Not authorable today*. |

- `start.delayMs` is a non-negative delay in milliseconds.
- `start.target` is only accepted for `onShapeClick`, must name an existing element, and must
  equal its own interactive sequence's `trigger.target`. PowerPoint stores one trigger shape
  per sequence, so a second shape needs a second interactive sequence.
- An `onShapeClick` effect in `mainSequence` is an error telling you to move it to
  `interactiveSequences`.
- `interactiveSequences[].trigger` takes the same object as `start`, and its `id` must be
  unique among sequences.

### Timing

```json
"timing": {
  "durationMs": 500,
  "repeatCount": 1,
  "repeatDurationMs": null,
  "autoReverse": false,
  "acceleration": 0,
  "deceleration": 0,
  "restart": "always"
}
```

| Field | Value | Authorable |
|---|---|---|
| `durationMs` | Positive ms. Falls back to the preset's observed duration. | yes |
| `repeatCount` | Non-negative whole repetitions. `1` writes nothing. | yes |
| `repeatDurationMs` | Positive ms. | yes |
| `autoReverse` | Boolean. | yes |
| `acceleration` | `0`–`1` fraction of the duration spent accelerating. | yes |
| `deceleration` | `0`–`1` fraction spent decelerating. | yes |
| `restart` | `always` / `whenNotActive` / `never`. | yes |
| `rewind` | Boolean. | **no** |
| `smoothStart` | Boolean. | **no** |
| `smoothEnd` | Boolean. | **no** |
| `bounceEnd` | Non-negative number. | **no** |

A truthy value in one of the last four is refused by catalog key, not ignored.

### Builds — text, chart, SmartArt

One shape and effect group carries exactly one build, so an effect may ask for text options,
a chart build or a SmartArt build — never two of them.

```json
{
  "id": "reveal-bullets",
  "target": {"element": "body"},
  "preset": {"category": "entrance", "effect": "fade"},
  "start": {"type": "onPageClick"},
  "text": {"sequence": "byParagraph", "level": "byParagraphLevel2", "unit": "byWord", "interItemDelayPercent": 10, "reverseOrder": false, "animateBackground": false}
}
```

| Field | Values |
|---|---|
| `text.sequence` | `allAtOnce`, `asOneObject`, `byParagraph` |
| `text.level` | `allParagraphLevels`, `asOneObject`, `byParagraphLevel1`, `byParagraphLevel2`, `byParagraphLevel3`, `byParagraphLevel4`, `byParagraphLevel5` |
| `text.unit` | `byParagraph`, `byWord`, `byCharacter` |
| `text.interItemDelayPercent` | Percentage of the duration between items. **Required** whenever `unit` is `byWord` or `byCharacter` — the capture records no default interval, so sdpm will not guess one. |
| `text.reverseOrder` | Boolean — animate items in reverse. |
| `text.animateBackground` | Boolean — animate the shape together with its text. Defaults to whatever the preset's own capture records. |
| `chart.build` | `chartAllAtOnce`, `chartByCategory`, `chartByCategoryElement`, `chartBySeries`, `chartBySeriesElement` |
| `smartArt.build` | `allAtOnce`, `asOneObject`, `byBranchOneByOne`, `byLevelAtOnce`, `byLevelOneByOne`, `oneByOne` |

`sequence` and `level` must agree — `asOneObject` and `byParagraphLevel2` contradict each
other and are rejected with both values named. A level that only refines its sequence
(`byParagraph` plus `byParagraphLevel2`) is fine.

Use `target.paragraphRange` when the effect should animate a slice of the paragraphs rather
than build the whole text frame.

### `behaviors` — the advanced form

Replace `preset` with `behaviors` to write PowerPoint's behavior primitives directly. The
nine types are `motion`, `color`, `scale`, `rotation`, `property`, `command`, `filter`, `set`
and `none` (the explicit no-op).

```json
{
  "id": "slide-card-right",
  "target": {"element": "card"},
  "behaviors": [
    {"type": "motion", "path": "M 0 0 L 0.25 0", "pathEditMode": "relative", "origin": "layout", "durationMs": 700}
  ],
  "start": {"type": "afterPrevious"},
  "timing": {"durationMs": 700}
}
```

| `type` | Required payload | Other fields |
|---|---|---|
| `motion` | `path` | `pathEditMode` (`relative`/`fixed`), `origin` (`parent`/`layout`), `rotationAngle` (degrees), `pointTypes` |
| `color` | `to` (six-digit sRGB hex) | — |
| `scale` | `to` as `{"x": 1.5, "y": 1.5}` | — |
| `rotation` | one of `by`, `fromValue`, `to` (degrees) | — |
| `property` | one of `by`, `fromValue`, `to`; plus `attrName` | `calcMode` (`discrete`/`lin`/`fmla`), `valueType` (`str`/`num`/`clr`) |
| `command` | `command` | `commandType` (`evt`/`call`/`verb`, default `call`), `value` |
| `filter` | `filter` or `transition` | `transition` is `in`/`out`/`none` |
| `set` | `to`; plus `attrName` | — |
| `none` | — | persists nothing |

- Every behavior may carry its own `durationMs`; otherwise it inherits the effect's.
- A behavior with no payload is an error, not an empty node.
- A `behaviors` list containing only `none` is an error: PowerPoint does not persist an empty
  behavior list.
- Out-of-enum attribute values fail with the allowed values rather than reaching the package,
  so PowerPoint never shows a repair prompt for them.

## Not authorable today

These settings are in the catalog with their PowerPoint evidence, and they are **preserved**
when they come in from an imported PPTX (as raw, see below), but sdpm refuses to *write*
them from semantic JSON. The refusal is deliberate and unconditional: a silent default
substitution would lose the user's setting.

| Setting | Catalog key |
|---|---|
| After animation: dim | `animation.afterAnimation.dim` |
| After animation: dim colour | `animation.afterAnimation.dimColor` |
| After animation: hide after animation | `animation.afterAnimation.hide` |
| After animation: hide on next click | `animation.afterAnimation.hideOnNextClick` |
| Media bookmark as a start trigger | `animation.media.bookmarkTrigger` |
| Effect sound | `animation.sound.effect` |
| Stop previous sound | `animation.sound.stopPreviousSound` |
| Trigger "with no trigger" | `animation.start.none` |
| Timing: bounce end | `animation.timing.bounceEnd` |
| Timing: rewind when done playing | `animation.timing.rewind` |
| Timing: smooth end | `animation.timing.smoothEnd` |
| Timing: smooth start | `animation.timing.smoothStart` |
| Transition sound | `transition.sound.effect` |
| Transition sound: loop until next sound | `transition.sound.loopUntilNext` |

Plus the 45 `MsoAnimDirection` scripting names (`animation.effectOptions.direction.`), which
are not an sdpm input at all — directions are written with `preset.options.direction` and
validated per effect — and every gallery preset outside the table above.

The error always names the key, the recorded gap and the slide:

```
slide 'intro': mainSequence[0].timing.smoothStart cannot be generated: catalog entry
'animation.timing.smoothStart' is semantic-preservation-only (<recorded gap>).
Capture it with the PowerPoint oracle (Task 8); sdpm refuses to approximate it.
```

`afterEffect.color` (the dim colour) is refused on its own key, `animation.afterAnimation.dimColor`,
even when `afterEffect.type` is left at `none`.

A sound needs an audio part plus a package relationship the writer does not create, so
`sound` must stay `null` on both an effect and a transition. The shape is validated when
present, and import produces it for a transition sound, so this is what you will read in an
imported slide file:

```json
"sound": {"src": "media/slide-003-rId3-chime.wav", "mediaType": "audio/wav", "loop": false}
```

`src` is a safe workspace-relative path (no absolute path, no URL, no `..` segment),
`mediaType` must start with `audio/`, and `loop` is a boolean. Import copies the audio part
into the bundle and writes the bundle-relative path here.

## What import recovers

Import reads both a direct `p:timing` / `p:transition` and the `mc:AlternateContent` form. It
evaluates `mc:Choice` branches in document order against the catalog's versioned supported
namespace set, takes the first satisfied Choice, otherwise the Fallback.

A tree becomes **semantic JSON only when every persisted behaviour affecting playback is
recognized**. A partially recognized tree is kept as **raw** instead, because dropping the
part sdpm does not understand would be silent data loss.

Recognized semantically today: slide transitions with their catalogued option sets and all
three Morph variants, duration, advance-on-click and advance-after-time, `morphId`, the
authorable entrance/exit/media presets, all 133 effect-option values (read back as
`preset.options`, by subtype where it identifies them and by behaviour comparison where it
does not), main and interactive
sequences and their order, the four writable triggers, delay, duration, repeat count, repeat
duration, auto-reverse, acceleration, deceleration, restart, catalogued paragraph builds, and
stable effect IDs.

Kept as raw rather than semantic JSON — preserved and replayable, but not authorable:

- a preset the catalog records as capture-required (reading it semantically would produce
  JSON the writer then refuses, so the round-trip would break on content the file carried);
- an effect whose behaviours match no measured form at all — a hand-edited payload, or one
  from a PowerPoint build this catalog was not measured against;
- an explicit behavior list using something outside the eight primitives' own vocabulary — an
  out-of-enum attribute value, a payload-free node, an angle that is not a whole number of
  degrees, or behaviours animating more than one target (the eight primitives themselves now
  import as `behaviors`, so only what the writer would refuse to write back stays raw);
- behaviors that do not match the catalog entry's recorded children exactly, or whose
  `p:set` / `p:animEffect` / `p:cmd` payload differs from the captured one;
- an after-effect or dim node;
- a `p:spTgt` carrying a paragraph/text sub-target;
- a build list (`p:bldP` / `p:bldGraphic` / `p:bldDgm`) with attributes beyond
  `@spid`, `@grpId`, `@animBg`, or whose `@animBg` disagrees with the catalogued build of the
  preset it belongs to;
- a bookmark start condition;
- an effect sound;
- one effect animating more than one shape.

A **transition** sound is the one exception in the other direction: import reads it
semantically into `transition.sound` and copies the audio part into the bundle, but the
writer refuses `transition.sound`. Regenerating such a deck therefore fails with
`transition.sound.effect` until that gap closes. Set `transition.sound` to `null` to
regenerate the deck without its sound.

Raw content is stored in the immutable import bundle, not in the slide file. The slide gets a
small reference:

```json
{
  "_rawTiming": {
    "sidecar": "animations/slide-003-timing.xml",
    "sha256": "…",
    "manifest": "animations/manifest.json",
    "reason": "p:spTgt carries a paragraph/text sub-target, which sdpm does not invert yet"
  }
}
```

The sidecar keeps the original XML, every retained Choice/Fallback branch, the source
namespace declarations, the shape-reference → logical-ID mapping, and the copied
relationship parts. `animations/manifest.json` lists that whole dependency closure with
hashes. On regeneration the writer remaps shape and relationship IDs; if a required
relationship or target cannot be rebuilt, generation fails rather than emitting a dangling
`rId`.

Do not hand-edit a sidecar, and do not write `_rawTiming` / `_rawTransition` yourself. To
replace raw motion with authorable motion, delete the raw reference and write the semantic
`animations` / `transition` instead — the two cannot coexist on one slide.

Limits on imported timing XML, on top of the existing attachment limits: depth at most 256,
at most 100,000 elements per slide, no DTDs and no external entities. A violation is
`IMPORT_LIMIT_EXCEEDED`.

With animations disabled for a slide whose raw tree mixes media and object timing, the
importer reconstructs media-only timing and suppresses the object-animation branches. If it
cannot separate the two safely, generation fails before any output is published.

## Validation errors

All of these fail before a PPTX is reported as generated.

| What | Error |
|---|---|
| Invalid mode value | Names the argument and `inherit`, `on`, `off`. |
| Duplicate `id` / `morphId` | Lint diagnostic naming both JSON paths. |
| Unknown `target.element` | Build error naming slide, sequence, effect and target. |
| Both or neither of `preset` / `behaviors` | `effect requires exactly one of preset or behaviors`. |
| Unknown effect name | Lists the catalog's supported names for that category. |
| Unsupported transition parameters | Lists the supported parameter sets for that effect. |
| Refused setting | `CapabilityGapError` naming the catalog key and the recorded gap. |
| Raw and semantic for the same feature on one slide | Lint failure, not a merge. |
| Text options plus a chart or SmartArt build on one shape | Names both and tells you to split the effect. |
| Contradicting `text.sequence` and `text.level` | Names both values and the `p:bldP` attribute they disagree on. |

## Related guides

- `read_guides(["import-pptx"])` — turning an attached PPTX into a deck, including what its
  animations become.
- `read_guides(["hand-edit-sync"])` — bringing animations the user added in PowerPoint back
  into slide JSON.
- `read_guides(["slide-json-spec"])` — everything else about slide JSON.

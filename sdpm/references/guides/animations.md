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
| `clock` | `{}`, `{"spokes": "2"}`, `{"spokes": "3"}`, `{"spokes": "4"}`, `{"spokes": "8"}` |
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
| `entrance` | `appear`, `blinds`, `checkerboard`, `dissolveIn`, `fade`, `randomBars`, `shape`, `split`, `strips`, `wedge`, `wheel`, `wipe` |
| `exit` | `blinds`, `checkerboard`, `disappear`, `dissolveOut`, `fade`, `randomBars`, `shape`, `split`, `strips`, `wedge`, `wheel`, `wipe` |
| `media` | `mediaPlay` |
| `emphasis` | none yet |
| `motionPath` | none yet |
| `custom` | none ever |

`emphasis` and `motionPath` have no authorable effect at all: every tile in both galleries is
still waiting for its PowerPoint capture. `custom` is not a gallery — it is the advanced form,
written with a `behaviors` list; a custom motion path is a `motion` behavior.

The catalog knows far more effects than the table lists (58 entrance tiles, 36 exit, 32
emphasis, 70 motion paths). The rest are recorded with their PowerPoint evidence but without
an established OOXML form, so the writer refuses them by name instead of substituting a
lookalike. Asking for one fails with its catalog key:

```
entrance effect 'flyIn' cannot be generated: catalog entry
'animation.gallery.entrance.flyIn' is semantic-preservation-only (<recorded gap>).
Capture it with the PowerPoint oracle (Task 8); sdpm refuses to approximate it.
```

`preset.variant` (a direction such as `fromLeft`) is validated against the catalog's 45
direction names and then **refused for every value**: a direction persists as the preset's
`presetSubtype`, and the capture records only each tile's default subtype, so writing it
would silently substitute the default direction. Leave `variant` out (or `null`).

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

Plus every effect direction (`preset.variant`, 45 keys under
`animation.effectOptions.direction.`) and every gallery preset outside the table above.

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
authorable entrance/exit/media presets with their default direction, main and interactive
sequences and their order, the four writable triggers, delay, duration, repeat count, repeat
duration, auto-reverse, acceleration, deceleration, restart, catalogued paragraph builds, and
stable effect IDs.

Kept as raw rather than semantic JSON — preserved and replayable, but not authorable:

- a preset the catalog records as capture-required (reading it semantically would produce
  JSON the writer then refuses, so the round-trip would break on content the file carried);
- a non-default preset direction (`presetSubtype` other than the tile's own);
- an effect with no `presetClass` / `presetID` — an explicit behavior list whose payload sdpm
  does not invert;
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

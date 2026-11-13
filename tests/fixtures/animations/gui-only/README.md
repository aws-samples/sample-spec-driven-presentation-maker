# GUI-only capture evidence

Each subdirectory is one captured value from the PowerPoint GUI, named by its
catalog key. The procedure and the evidence requirements live in
`scripts/animation_catalog/computer-use.md`.

These captures are development-time evidence. sdpm's runtime, CLI, MCP servers,
tests and CI never invoke PowerPoint, AppleScript or Computer Use.

## Captures

| Key | Application | Date | Control path | Evidence |
| --- | --- | --- | --- | --- |
| `transition.gallery.box.fromRight` | PowerPoint for Mac 16.113.1 | 2026-10-31 | Transitions ▸ Transition Styles ▸ Box ▸ Effect Options ▸ From Right | `.pptx`, `.xml`, `powerpoint-readback.jsonl` |
| `animation.gallery.motionPath.lines` | PowerPoint for Mac 16.113.1 | 2026-10-31 | Animations ▸ Path Animation ▸ Basic ▸ Lines | `.pptx`, `.xml`, `powerpoint-readback.jsonl` |
| 9 animation values | PowerPoint for Mac 16.113.1 | 2026-10-31 | Animations ▸ gallery ▸ tile | `batch-2026-10-31/` |
| 43 animation values | PowerPoint for Mac 16.113.1 | 2026-11-01 | Animations ▸ gallery ▸ tile | `batch-2026-11-01/` |
| **all 76 animation values** | PowerPoint for Mac 16.113.1 | 2026-11-01 | Animations ▸ gallery ▸ tile | `batch-2026-11-01-complete/` |
| 95 tiles' Effect Options windows read | PowerPoint for Mac 16.113.1 | 2026-11-01 | Animations ▸ Effect Options | `effect-options-2026-11-01/` |
| **all 133 effect-option values** | PowerPoint for Mac 16.113.1 | 2026-11-02 | Animations ▸ tile ▸ Effect Options ▸ value | `effect-options-capture-2026-11-02/` + `effect-options-remeasure-2026-11-02/` |

### The effect-option captures

`effect-options-2026-11-01/` is the discovery pass: every titled element of
every gallery tile's `Effect Options` window, recorded without interpretation.
33 of the 95 tiles carry a setting; the other 62 expose only `Sequence`.

`effect-options-capture-2026-11-02/` is the measurement, and
`merged-effect-options.json` is the authoritative result:
**133 of 133 values measured, 0 missing, 0 collisions**, across 33 effects and
6 settings (Direction 87, Amount 12, Zoom 12, Spokes 10, Shapes 8, Vanishing
Point 4). It is produced by `effect_options_merge.py` from that batch's
`resolved.json` plus the five targeted re-measurements in
`effect-options-remeasure-2026-11-02/`, and 11 of the 133 values come from
those re-runs.

They exist because **a press inside the `Effect Options` window is
intermittent**: it reaches the control and PowerPoint does not always act on
it, leaving the effect's default behind, which reads as a plausible
measurement. Three values were wrong until they were measured again —
`flyIn` From Right, `stretch` From Top and `transparency` 25% each carried a
sibling's OOXML. `effect_options_merge.py --check` is the standing guard: two
values of one setting cannot produce the same OOXML, and that check is what
found them. The measurement procedure and the attempt counts are in
`scripts/animation_catalog/computer-use.md` Step 8.

Sub-directories of `effect-options-remeasure-2026-11-02/` are each one value on
a freshly generated deck: `from-right/`, `stretch-from-top/`,
`transparency-25/`. `stretch-from-top/` also holds the record of a **refused**
target — `transparency` 25% failing 4 of 4 attempts on a two-target deck — kept
because the gate declining to record a default is the behaviour under test.

### The complete run

`batch-2026-11-01-complete/` is the whole GUI-addressable animation surface the
plan derives from the catalog's gaps: **76 of 76 captured, 76 attributed, 0
`spid` mismatches** — 23 entrance, 24 exit, 24 emphasis and 5 motion paths. Each
record carries the shape it aimed at, the Selection Pane row index it selected,
the `p:spTgt/@spid` the effect landed on, and that effect's own `p:cTn`
attributes, so a value is read per target even though every target shares one
slide. `powerpoint-oracle.pptx` is the package those records were read from.

It supersedes the two earlier batches rather than replacing them: the earlier
runs are what the mechanism was corrected against, and
`scripts/animation_catalog/computer-use.md` cites their failure counts.

**These captures are not in the catalog yet.** Promoting them is a separate step
through `generate.py`, which today ingests transition captures only — the
animation ingest does not exist. Until it does, the catalog's animation presets
remain what the evidence tables say and these files are the measurement that
would confirm or correct them.

### What the motion-path capture established

`computer-use.md` Step 6 said every motion-path entry was
`semanticPreservationOnly` because PowerPoint stores a preset path as literal
path data that no available capture contained. It does now:

```xml
<p:cTn id="5" presetID="42" presetClass="path" presetSubtype="0"
       accel="50000" decel="50000" fill="hold" grpId="0" nodeType="clickEffect">
  <p:animMotion origin="layout" path="M 0 0 L 0 0.25 E"
                pathEditMode="relative" ptsTypes=""/>
```

`@path`, `@origin` and `@pathEditMode` are the three Step 6 asked for.
`presetID="42"`, `presetClass="path"` and `accel`/`decel` at 50000 came with
them — the last two bear on `animation.timing.smoothStart` / `smoothEnd`,
whose own captures have not been taken yet, so do not promote those from this
entry alone.

The Path Animation popup also enumerates the full preset grid in one read:
Custom (Draw Curve, Draw Freeform, Draw Line, Draw Scribble), Basic (Arcs,
Lines, Loops, Shapes, Turns) and Complex (Bounce, Inverted Shape, Special
Curve, Special Shape, Spiral, Star, Waves).

## Known incompleteness of the pilot capture

`computer-use.md` requires four artefacts per value. The pilot carries three:

1. the saved `.pptx` — present;
2. the extracted XML fragment — present;
3. the ribbon read-back at the time of application — present, in
   `powerpoint-readback.jsonl` (`durationShown: "01.60"`, `[No Sound]`,
   advance on mouse click, thumbnail `Has Transition`);
4. **the screenshot is missing**, and the value was **not re-read after closing
   and reopening the file**.

So this capture establishes what PowerPoint *wrote*, not yet that PowerPoint
*reads the same value back from a reopened file*. Treat it as evidence of the
OOXML form and of the capture loop working, not as a completed Step 1 entry.

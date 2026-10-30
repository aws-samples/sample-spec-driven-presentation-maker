# Computer Use reproduction steps for GUI-only catalog values

These steps close the gaps the offline evidence cannot close. They are
development-only (REQ-7.3): sdpm's runtime, CLI, MCP servers, tests and CI never
invoke Computer Use, AppleScript, VBA or PowerPoint.

They were **not executed for the current catalog**. Task 3 was scoped not to
launch or drive PowerPoint, so every entry in
`sdpm/references/catalogs/powerpoint-animation-catalog.json` whose
`capabilityLevel` is `semanticPreservationOnly` still carries its `ooxml.gap`
and `verification: "powerPointReadBackRequired"`. Running the steps below is how
a maintainer promotes those entries.

## Baseline

| Item | Value |
| --- | --- |
| Application | Microsoft PowerPoint for Mac |
| Version | 16.113.1 |
| Scripting definition | `/Applications/Microsoft PowerPoint.app/Contents/Resources/PowerPoint.sdef` |
| GUI manifest | `sdpm/references/catalogs/powerpoint-gui-surface-16.113.1.json` |

Record the exact version string from **PowerPoint ▸ About Microsoft PowerPoint**
before and after a session. A different build invalidates the capture: bump
`manifestVersion` and regenerate rather than mixing builds.

## Session setup

1. Quit PowerPoint. Confirm no recovery deck is pending.
2. Launch PowerPoint and create a deck from **Blank Presentation**.
3. Delete the title slide's placeholders so the slide is empty.
4. Set the window to a fixed size and record it in the session log. Screenshot
   coordinates are only reproducible at a fixed window size.
5. Turn off **PowerPoint ▸ Settings ▸ General ▸ Show Start screen**.

## Evidence that every step must produce

For each value, capture all four of these or the value stays unverified:

1. a screenshot of the control with the value selected, named
   `<guiKey>--<value>.png`;
2. the `.pptx` saved immediately after applying the value, named
   `<guiKey>--<value>.pptx`;
3. the extracted XML fragment — `ppt/slides/slideN.xml`'s `p:transition`,
   `p:timing` and `p:bldLst` — named `<guiKey>--<value>.xml`;
4. the value PowerPoint shows **after** closing and reopening the saved file.

Extract (3) without PowerPoint:

```bash
unzip -p "<guiKey>--<value>.pptx" ppt/slides/slide1.xml \
  | python3 -c 'import re,sys; x=sys.stdin.read(); print("\n".join(re.findall(r"<p:(?:transition|timing|bldLst)\b.*?</p:(?:transition|timing|bldLst)>|<mc:AlternateContent\b.*?</mc:AlternateContent>", x, re.S)))'
```

Store the four files under `tests/fixtures/animations/gui-only/<guiKey>/` and add
a row to that directory's `README.md` naming the application version, the date,
and the control path. Then update the catalog entry's `capabilityLevel`,
`evidence` and `verification`, and run
`uv run python scripts/animation_catalog/generate.py --check --require-sdef`.

## Step 1 — transition directions on extension elements

Covers every `EPPEntryEffect` candidate whose `ooxml.gap` mentions an extension
attribute: the non-default directions of Box, Cube, Rotate, Orbit, Doors,
Window, Switch, Flip, Gallery, Pan, Ferris Wheel, Conveyor, Vortex, Ripple,
Glitter, Shred, Reveal, Fly Through, and the `p15:prstTrans` mirror variants
(Fall Over, Drape, Wind, Peel Off, Page Curl, Airplane, Origami).

For each tile and each direction:

1. Select slide 2. Open **Transitions**.
2. Click the tile. The captured default is already in the catalog; skip it.
3. Open **Effect Options** and choose the direction.
4. Save as `<guiKey>--<direction>.pptx`, close, reopen, confirm **Effect
   Options** still shows the direction, and capture the four evidence files.

What to look for in the XML: whether the direction is a `dir` attribute, an
`invX`/`invY` boolean, or a different `prst` value. The catalog's current guess
is in `ooxml.attributes`; replace it with what PowerPoint wrote and drop
`requiresCapture`.

## Step 2 — Page Curl Single and the mirror variants

`entry effect page curl single left/right` share the Page Curl tile with
`pageCurlDouble`, which is the captured default. Use **Effect Options ▸ Single
Left / Single Right / Double Left / Double Right** and record which `prst` value
and which `invX` each of the four produces.

## Step 3 — After animation (dim, hide, hide on next click)

1. Apply **Animations ▸ Fade** to a rectangle.
2. Open the **Animation Pane**, double-click the effect, open the **Effect** tab.
3. Set **After animation** to each of: *Don't Dim*, a dim colour, *Hide After
   Animation*, *Hide on Next Mouse Click*.
4. Capture evidence per value.

What to look for: whether PowerPoint writes `p:cTn/@afterEffect`, an extra
`p:set` on `style.visibility`, or a trailing `p:animClr`, and where the dim
colour lives. This closes
`animation.afterAnimation.{dim,hide,hideOnNextClick}` and
`animation.afterAnimation.dimColor`.

## Step 4 — Effect sound and Stop previous sound

Same dialog, **Effect** tab, **Sound** dropdown. Capture one built-in sound and
one *Other Sound…* WAV, plus *Stop Previous Sound*. Record the media part path,
the content type and the relationship type, not just the XML: REQ-5.7 needs the
relationship closure. This closes `animation.sound.effect`,
`animation.sound.stopPreviousSound`, `transition.sound.effect` and
`transition.sound.loopUntilNext`.

## Step 5 — Timing: rewind, smooth start/end, bounce end

**Effect Options ▸ Timing** for rewind; **Effect Options ▸ Effect** for a motion
path's smooth start, smooth end and bounce end. Apply a non-default value for
each, one per slide, and diff the saved `p:cTn` attributes against a slide with
the default. This closes `animation.timing.{rewind,smoothStart,smoothEnd,bounceEnd}`.

## Step 6 — Motion paths

Every motion-path entry is `semanticPreservationOnly` because PowerPoint stores
preset paths as literal path data in `p:animMotion/@path`, which no available
capture contains.

1. Apply each tile in **Animations ▸ gallery ▸ Motion Paths** (Lines, Arcs,
   Turns, Shapes, Loops), then each entry in **Add Animation ▸ More Motion
   Paths…**, one per slide.
2. Save once per group of slides and extract every `p:animMotion` verbatim.
3. Record `@path`, `@origin`, `@pathEditMode`, `@rAng` and the `p:rCtr` child.

Keep the path data byte-exact. Re-deriving a Bézier by eye is exactly the
guesswork this catalog is built to avoid.

## Step 7 — MsoAnimEffect ordinals above 31

The scripting ordinal and the OOXML `presetID` agree only up to 31; above that
the mapping is unestablished and the catalog says so. The GUI cannot resolve it
alone because the ribbon shows names, not ordinals. Resolve it with the
AppleScript oracle (`powerpoint.applescript`) on a machine that has granted
Automation permission: it applies a named `MsoAnimEffect` constant and reads back
the saved `presetID`. Use Computer Use only to confirm that the resulting
Animation Pane entry shows the expected gallery name.

## Step 8 — Direction codes (`presetSubtype`)

Every `MsoAnimDirection` candidate is `semanticPreservationOnly`: the available
evidence binds `presetSubtype` codes to gallery tiles, not to direction names
(see `provenance.presetSubtypeEvidence`).

For each effect that offers directions — Fly In, Peek In, Wipe, Blinds,
Checkerboard, Random Bars, Split, Strips, Wheel, Shape, Zoom, Swivel, Stretch —
apply every entry in **Effect Options ▸ Direction**, one per slide, and record
`p:cTn/@presetSubtype` plus the `p:animEffect/@filter` argument. Build the
`direction name → presetSubtype` table from the result, then set
`ooxml.presetSubtype` on the matching candidates.

## Step 9 — SmartArt and chart builds

**Effect Options ▸ SmartArt Animation ▸ Group graphic** for each value, and
**Chart Animation ▸ Group chart** on a clustered-column chart. Confirm the
`p:bldDgm/@build` and `p:bldGraphic` forms the catalog predicts from
`ST_AnimationDgmBuildType` and `ST_AnimationChartBuildType`.

## Step 10 — Non-persisted controls

Confirm, rather than capture, that these write nothing. Apply each, save, and
diff the package against the same deck saved without it:

- **Transitions ▸ Apply To All** — expect identical `p:transition` on every
  slide and no deck-level element.
- **Transitions ▸ Preview**, **Animations ▸ Preview / Play From** — expect a
  byte-identical package.
- **Animations ▸ Animation Painter** — expect the copied effects on the target
  shape and nothing else.
- **Transition gallery ▸ None** — expect no `p:transition` element at all.

A non-empty diff means the catalog's `nonPersisted` status is wrong and must be
corrected rather than explained away.

## Logging

Append one line per value to `tests/fixtures/animations/gui-only/session.jsonl`:

```json
{"guiKey":"animation.afterAnimation.dim","value":"dim","applicationVersion":"16.113.1","capturedAt":"2026-11-02T10:14:00Z","screenshot":"...png","package":"...pptx","fragment":"...xml","reopenedValue":"Dim","operator":"<name>"}
```

`generate.py --check` does not read this log; it is the human audit trail that
justifies a capability-level promotion in review.

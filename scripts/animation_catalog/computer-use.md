# Computer Use reproduction steps for GUI-only catalog values

These steps close the gaps the offline evidence cannot close. They are
development-only (REQ-7.3): sdpm's runtime, CLI, MCP servers, tests and CI never
invoke Computer Use, AppleScript, VBA or PowerPoint.

Almost every entry in
`sdpm/references/catalogs/powerpoint-animation-catalog.json` whose
`capabilityLevel` is `semanticPreservationOnly` still carries its `ooxml.gap`
and `verification: "powerPointReadBackRequired"`. Running the steps below is how
a maintainer promotes those entries.

**One capture has been executed** (2026-10-31), as a proof of the loop rather
than as coverage: Box ▸ Effect Options ▸ From Right. See "Driving mechanics"
below for the method and "What the pilot capture established" for its result.

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

## Driving mechanics (measured 2026-10-31, PowerPoint 16.113.1, 1512x900 window)

AppleScript is not the route. `osascript` reaches PowerPoint's **static**
properties (`get version`) but every document-model access and every
`System Events` call fails with `-10004`. The working route is the macOS
**Accessibility API** through KiroCrew's computer-use tools, which is a
different mechanism and is not blocked.

Three facts decide how a batch is written:

- **`computer_get_state` is reliable**, and the ribbon is fully enumerated:
  every gallery tile, the Duration incrementor, the Sound popup, the advance
  checkboxes, and each thumbnail's `Has Transition` state.
- **`computer_click` with `element_index` always fails** against the main
  window (`element … is no longer present`), because PowerPoint rebuilds its
  accessibility elements between queries. `computer_perform_action` with
  `element_index` **does** work — use it for menu items.
- **`click_method: "app_post"` is delivered but ignored** by the ribbon: it is
  custom-drawn and does not process per-process synthetic mouse events. Only
  `click_method: "global"`, which moves the real pointer, drives it.

Consequences for an unattended batch:

- The machine's pointer is taken over for the length of the batch. PowerPoint
  must hold the capture deck and nothing the operator cares about.
- After a `global` click the pointer rests on the control and macOS raises a
  tooltip there, which makes the **next** click at the same point refuse with
  `the topmost window there is 'Window Server'`. Interleave an unrelated click
  (selecting the slide thumbnail works and is needed anyway) between two
  clicks on the same control.
- Set `max_tree_nodes: 1` before a run of clicks. A click returns a refreshed
  tree at the budget of the last read, and the full ribbon tree is large.

The Transition Styles gallery is positioned arithmetically, verified against
the tree:

```
tile x = 100 + 92 * i - 920 * page        visible band: x in [100, 1012]
page   = floor(92 * i / 920)              Next/Previous move exactly one page
tile centre = (x + 47, 107)               window-relative; add window origin y
```

`i` is the index in gallery order, which is fixed:
None, Morph, Fade, Push, Wipe, Split, Reveal, Cut, Random Bars, Shape,
Uncover, Cover, Flash, Fall Over, Drape, Curtains, Wind, Prestige, Fracture,
Crush, Peel Off, Page Curl, Airplane, Origami, Dissolve, Checkerboard, Blinds,
Clock, Ripple, Honeycomb, Glitter, Vortex, Shred, Switch, Flip, Gallery, Cube,
Doors, Box, Comb, Zoom, Random, Pan, Ferris Wheel, Conveyor, Rotate, Window,
Orbit, Fly Through.

Order a batch by gallery page so the sweep is monotonic: 49 tiles are 5 pages,
so a whole pass costs four `Next` clicks rather than one per tile.

Other measured coordinates, window-relative (add the window origin):

| Control | Frame | Centre |
| --- | --- | --- |
| Transitions ribbon tab | x=247,y=39 94x26 | 294, 52 |
| Previous gallery page | x=82,y=78 18x58 | 91, 107 |
| Next gallery page | x=1020,y=78 18x58 | 1029, 107 |
| Effect Options | x=1040,y=74 50x66 | 1065, 107 |
| Duration (read-back) | x=1204,y=78 78x24 | — |
| Sound (read-back) | x=1180,y=109 102x26 | — |
| Save (Quick Access) | x=221,y=5 30x30 | 236, 20 |
| Thumbnail cell *n* | x=0,y=150+130(n-1) 250x118 | 125, 209+130(n-1) |

Effect Options opens as its own window titled `Effect Options`, whose items
are `menubutton`s. Activate one with `computer_perform_action` + `AXPress`; a
plain `global` click only focuses it and leaves the menu open.

### What the GUI route cannot establish

The AppleScript oracle applied a candidate **by its enumerator code**, so its
read-back was an unambiguous `EPPEntryEffect.<enumerator>` → OOXML mapping.
The GUI applies by **label**, so a capture establishes
`gallery tile + Effect Options label` → OOXML. Linking that to a scripting
enumerator such as `entry effect box down` is a name correspondence, not a
measurement. Record a GUI capture under a `transition.gallery.<tile>.<label>`
key and promote a scripting candidate only by stating the correspondence as
inferred.

### What the pilot capture established

Box ▸ From Right, applied to slide 1 of a four-slide deck generated by sdpm
with both motion switches off, then saved and extracted offline:

```xml
<mc:AlternateContent>
  <mc:Choice Requires="p14">
    <p:transition spd="slow" p14:dur="1600"><p14:prism isInverted="1"/></p:transition>
  </mc:Choice>
  <mc:Fallback>
    <p:transition spd="slow"><p:fade/></p:transition>
  </mc:Fallback>
</mc:AlternateContent>
```

- The deck opened with **no repair prompt**, and only slide 1 gained a
  transition — the other three stayed clean.
- The catalog's predicted `p14:prism`, `p:fade` fallback, `p14` strategy,
  `alternateContent: true` and `legacySpeed: "slow"` are all confirmed.
- The direction is carried by **`isInverted`**, not a `dir` attribute — which
  is the question Step 1 says to answer.
- The catalog's `defaultDurationMs: 1000` for Box is **wrong**: PowerPoint
  wrote `p14:dur="1600"`, and the ribbon's Duration field read `01.60`.

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

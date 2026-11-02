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

## This is the only route to an animation value

> `add effect` is declared in `PowerPoint.sdef` but **PowerPoint for Mac
> 16.113.1 does not implement it** on `main sequence`. In the 2026-10-31
> scripting-oracle run, all 150 `MsoAnimEffect` candidates were refused with
> one identical error:
>
> ```
> main sequence of timeline of slide N of presentation "Presentation1"
> doesn't understand the "add effect" message.
> ```
>
> No slide in that run's package carries a `p:timing` tree. The evidence is
> checked in at `tests/fixtures/animations/oracle-16.113.1/`, and each refused
> candidate's catalog entry records the error in its `capture` block.

Two consequences, both load-bearing for the steps below:

1. **Do not rewrite the AppleScript animation probes.** `probeAnimations`,
   `probeDirections`, `probeTriggers`, `probeBuildLevels`, `probeTextUnits`,
   `probeBehaviors` and `probeAfterEffects` all begin by adding an effect, so
   no terminology fix can make them work in this build. Steps 3 to 10 of this
   file are the *only* way to capture an animation value: every remaining
   capture-required animation entry and every unresolved behavior payload has
   to come through the Accessibility API, by hand, through this procedure.
2. **The transition steps are already closed**, and not from here. The
   scripting oracle applies a candidate by enumerator code, which is what the
   catalog is keyed on, so it settled the transition half outright — see
   Steps 1 and 2. Transitions are scriptable in this build; animations are not.
   That splits the remaining work by mechanism rather than by effort.

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

**Use `computer_perform_action` with `AXPress`, not clicks.** This is the whole
method; everything below about coordinates is a fallback for controls that have
no addressable element.

- **`computer_get_state` is reliable**, and the ribbon is fully enumerated:
  every gallery tile, the Duration incrementor, the Sound popup, the advance
  checkboxes, and each thumbnail's `Has Transition` / `Has Animation` state.
  Enumerated is not the same as drivable: the thumbnails have titles and no
  actions, which is the subject of "Why the driver does not select slides".
- **`computer_perform_action` with `element_index` works**, including on
  main-window elements and on elements scrolled **outside** the visible band.
  Pressing a tile at window `x=1448` inside a 320-pixel-wide gallery applies
  it and scrolls it into view. So there is no coordinate arithmetic, no
  paging, no tooltip problem, and **no pointer takeover** — the operator's
  machine stays usable.
- **One explicit `computer_get_state` per `perform_action`, and nothing in
  between.** The indices come from that call alone. The tree a *click* returns
  does not register, which the tool says plainly once you hit it:
  `no state for 'com.microsoft.Powerpoint'. Call computer_get_state first.`
  Until that error appears the symptom is the misleading
  `element N is no longer present`, so a run of presses reads like PowerPoint
  invalidating its elements when it is really a missing read. Send the two
  calls in separate turns: issued together they race and the action loses.
- **A popup's own window is only visible to an explicit read.** After a click
  opens `Effect Options` or `Path Animation`, the click's refreshed tree still
  shows the document window; the next `computer_get_state` reports
  `Window: "Path Animation"` with the whole grid. Do not conclude a popup
  failed to open from a click's own output.
- **`computer_click` with `element_index` always fails** against the main
  window (`element … is no longer present`), because PowerPoint rebuilds its
  accessibility elements between queries. This is a limitation of that tool,
  not of the accessibility route.
- **`click_method: "app_post"` is delivered but ignored** by the ribbon: it is
  custom-drawn and does not process per-process synthetic mouse events.
  `click_method: "global"` does drive it, but it moves the real pointer, and
  after such a click the pointer rests on the control and macOS raises a
  tooltip there, so the **next** `global` click at the same point refuses with
  `the topmost window there is 'Window Server'`. There is now **nothing in the
  driver that needs it**: the one target with no addressable element, a shape
  on the slide canvas, is reached through its Selection Pane row instead. See
  "Why the driver selects shapes in the Selection Pane".

A gallery **lazily materializes its tiles**: a first read of Entrance Effects
returned 22, and after one tile was pressed the same read returned different
tiles (Rise Up, Spinner, Basic Zoom, Stretch, Boomerang) that had not been
there. Re-read the tree after each press rather than caching an index list,
and never assume the first read enumerated the whole gallery.

### Two constraints that set the cost of a batch

Both were measured, and together they rule out the obvious shortcuts.

**A gallery press replaces the effect of the selected shape; it does not add
one.** There is no Add Animation button on this build. Pressing Lines, then
Appear, then a third tile on one shape leaves **one** effect — the last. A batch
therefore needs **one shape per value**, not one shape with a stack of them. It
does *not* need one slide per value: what the press is scoped to is the
selection, so one slide carrying many well-separated shapes works, and each
effect in the saved `p:timing` says which shape it belongs to through
`p:spTgt/@spid`. That is how the driver attributes a capture — see
"Why the driver does not select slides" below for why it is also the only shape
that works.

**Indices shift as soon as a press scrolls the gallery.** `perform_action`
keeps the state across consecutive actions, so several presses can share one
read — but only while the tile list holds still. After one press the Entrance
gallery scrolled, grew a Previous button, and materialized Swivel, Zoom,
Center Revolve, Float In and Grow Turn, so the index that had been
Checkerboard was Shape. A press aimed by a stale index applies the wrong
effect and the record names the right one, which is worse than failing.
**Re-read before every press.**

So the real cost per value is three calls — select the shape's row, read, press.
(It was four while a slide had to be selected too; that step is gone, and the
next section says why.) Size a batch by the number of shapes in it.

Set `max_tree_nodes: 1` before a run of presses when you do not need the tree:
a press returns a refreshed tree at the budget of the last read, and the full
ribbon tree is large.

If you do fall back to coordinates, the Transition Styles gallery is positioned
arithmetically, verified against the tree:

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

The slide-navigator thumbnail geometry that used to sit in this table has been
removed rather than corrected. It was never usable — see the next section.

## Why the driver does not select slides

Measured 2026-10-31 by a live run of the driver's first version, which selected
a slide per target. Against a 76-target plan on a 76-slide deck it returned
**76 records, 0 captured, 76 rejected**, with `steps` empty on every record:
nothing reached a control. Two distinct causes, both inside slide selection.

**The navigator's cells expose no actions.** `select_slide` pressed the cell,
then set `kAXSelected`, then waited, bounded, for `AXSelected` to read back
true. A manual read of the live tree showed
`cell "Slide 1 of 17 Slides"` with **no `[AXPress]`** and no other action, and
the attribute never became true, so slides 1 to 6 each ended in a 6-second
timeout. The only thing that selected a slide by hand was a synthetic
**global click on the cell's own frame** — a pointer takeover per target, and
the pointer is exactly what the next section stops needing.

**Only the cells scrolled into view exist.** The navigator publishes **6** of
76 cells; the rest are not in the tree at all. Slides 7 to 76 were therefore
rejected as `slide N is outside the 6 thumbnail cells read`. Position-indexing
cannot reach a cell the application has not materialized, and reaching them
would need scrollbar arithmetic plus title matching plus a status-bar
cross-check — three more assumptions with no offline check.

The fix was to stop needing slide selection. `gui_capture_plan.py` now builds
**one slide carrying one named shape per target**, and `gui_capture.py` selects
a target through that shape's Selection Pane row. Attribution got
stronger rather than weaker:
each effect in the saved `p:timing` carries `p:spTgt/@spid`, and the slide's
`p:cNvPr/@id` and `@name` map that back to the shape and so to the target, which
survives reordering and catches a mis-aimed click. "Slide N is target N" did
neither.

Two consequences worth keeping in mind for manual work in this file's other
steps:

- the `Has Animation` thumbnail marker is **not** per-target evidence on a
  one-slide deck. It says the slide has an animation, which it does after the
  first capture. Read `p:spTgt/@spid` instead.
- a deck of 76 slides is still fine to *read* by hand; it is driving the
  navigator that does not work.

## Why the driver selects shapes in the Selection Pane

Measured 2026-11-01. A canvas shape has **no accessibility element**, so for a
while the driver selected one with a synthetic global mouse event at a point
derived from the package geometry, the live editor-pane frame and the live zoom.
That never became reliable. Watching a run, the pointer landed in the right
place and the shape stayed unselected; the same click by hand always worked.
Pacing the event helped and did not fix it — `kCGMouseEventClickState`, a settle
before the button-down, a hold, and a 0.35 s settle after the up took the last
run of that version to **2 of 12** attempted targets, with the other ten
recorded as `effectNotAdded` / "no new effect appeared": the signature of a
click that did not change the selection, so the gallery press replaced the
*previously* selected shape's effect.

Canvas shapes have no element. **Their Selection Pane rows do**, and that
removes coordinates, the pointer, the zoom, the pane frame and the timing all at
once. Measured live:

| Fact | Value |
| --- | --- |
| `Home ▸ Arrange` | an `AXMenuButton`; pressing it opens a window titled `Arrange` |
| the `Arrange` window | holds an `AXMenuButton` titled `Selection Pane...` |
| pressing that | opens the pane **inside the document window that carries the ribbon** (PowerPoint publishes several same-titled windows) |
| the pane | an `AXOutline` whose children are one `AXRow` per shape — 153 rows for a deck of 76 shapes plus 76 labels plus one |
| row order | **reverse z-order**: row 0 `TextBox 152`, row 1 `Rounded Rectangle 151`, row 2 `TextBox 150` |
| a row's `title` | `None`. The shape name is the **`value` of a descendant `AXStaticText`** |
| a row's actions | `AXShowDefaultUI`, `AXShowAlternateUI` and a Rename. **No `AXPress`** |
| selecting a row | **set `AXSelected`**, the standard outline-row mechanism, then read it back |
| `AXRows` vs `AXChildren` | idle: `AXRows` 152, `AXChildren` 153, `AXVisibleRows` 24 |
| `AXRows` **during a run** | **43, 54, 61, 63, 74, 88, 91** rows on consecutive reads of the same 152-shape slide. It is not all of them |
| a row's **name**, during a run | published only for rows that have been scrolled into view. One run read **80** names, then **54** |
| **`AXIndex` on a row** | every row publishes one: 0, 1, 76 and 151 at those offsets. **This is what identifies a row** |
| `AXRowCount` on the outline | not published (`None`) |
| row order against the package | reverse z-order, **152 of 152 agreeing, 0 mismatches, verified twice** |
| the enclosing `AXScrollArea` | its `AXVerticalScrollBar`'s `AXValue` **is settable** — an unused fallback, should the retry below ever stop being enough |

So a shape is selected **by row index** — its position in reverse z-order, read
offline from the package, matched against the row that reports that `AXIndex`.
No coordinates, no keyboard focus, no timing dependency.

Two things that look like they would work and do not. **A name is not a key**:
selecting by name rejected 11 targets as "no Selection Pane row is named ..."
for rows that were there and selectable the whole time, because an unscrolled row
carries no `AXStaticText` to read a name from. And **an offset into `AXRows` is
not a key either**: that rejected 7 more, because the pane rebuilds while the
application works and a read catches it part-built. A row's own `AXIndex` is
readable in both states, so a partial read is usable whenever it contains the row
wanted, and a read that does not is simply retried.

The name is kept as a **check**: if the row at an index publishes a name, it must
be the name expected there. That is what would catch a pane in some other order,
or an `AXIndex` that turned out to be relative to a partial read rather than
absolute, before a press lands on another shape.

Two cautions carried over from elsewhere in this file: pressing
`Selection Pane...` while the pane is open **closes** it, the same trap as
pressing an already-active ribbon tab, so read the pane's presence rather than
remembering it; and rows are re-created between reads like every other element
here, so re-resolve the row from a fresh read every time, index and all.

The coordinate table and the canvas formula below are kept for **manual** work
through the Computer Use tools. `gui_capture.py` uses neither: it posts no mouse
events at all, and the options that corrected the mapping (`--pane-frame`,
`--pane-role`, `--zoom`) are gone with it.

Effect Options opens as its own window titled `Effect Options`, whose items
are `menubutton`s. Activate one with `computer_perform_action` + `AXPress`; a
plain `global` click only focuses it and leaves the menu open.

### The loop is a script now, not an agent round trip

Everything above is still how PowerPoint behaves; what changed is who sends the
calls. **The macOS Accessibility API is reachable from Python in this
environment**, which the KiroCrew tool wrapper is not required for:
`AXIsProcessTrusted()` returns true and `AXUIElementCreateApplication(pid)`
returns PowerPoint's window, under

```bash
uv run --with pyobjc-framework-ApplicationServices --with pyobjc-framework-Cocoa \
  --with lxml \
  python …
```

(`lxml` because the package readers import it lazily, so a run outside the
repository's own environment fails at the first attribution without it. **Quartz
is not needed** — the only binding that wanted it was the mouse event.)

So the calls per value — select the shape's row, read, press, save — are a loop
inside one process rather than that many agent turns, and the two rules that make
the tool contract awkward (one explicit read per action, a popup being invisible
to the read that opened it) stop being rules to remember: the driver re-reads
before every press by construction. It also posts **no mouse events**, so a run
no longer takes the pointer over.

### What a read costs, and where the window's nodes are

Every accessibility attribute read is an **interprocess round trip**, and the
document window is **907 nodes, 762 of them the Selection Pane's rows**. Timed
live on 2026-11-01, best of three:

| operation | cost |
|---|---|
| `find_all_by_title(window, "Save")` — one full window walk | **6.4 s** |
| `selection_outline(backend)` | **17.8 s** |
| walking only the pane's outline (762 nodes) | 4.1 s |
| reading 152 rows' names | 4.3 s |

Two consequences for anyone driving this by hand or by script:

- **PowerPoint publishes four or five `AXWindow`s carrying the same document
  title**, and only one of them holds the ribbon. Searching each by title to
  find out costs a full walk per candidate.
- **The window's controls live in three containers**, and each is the smallest
  thing certain to hold what it holds: `Save` under the window's `AXToolbar`;
  the tab strip and the active tab's command galleries under one `AXTabGroup`;
  the shape rows under the pane's `AXOutline`. The tab group is a **top-level
  child** of the window, which is what makes identifying the right window a
  two-level look rather than a walk.

So a lookup aimed at the whole window pays for the pane's rows even when it wants
a ribbon tile, and vice versa. `gui_capture.py` scopes every lookup to one of the
three containers for exactly that reason, and a run of it that did not captured
**7 targets in 28 minutes**.

`scripts/animation_catalog/gui_capture.py` is that driver and
`gui_capture_plan.py` derives its target list from the catalog's own
`ooxml.requiresCapture` entries. See
[the README](README.md#gui-capture-driver) for how to run them. Use this file
for what the application does; use the driver for doing it.

### Mechanics this file did not record, found while coding against it

Each of these was needed to write the driver and was not here:

- **The Animations galleries are three separate named controls**, not one
  gallery with sections: `Entrance Effects`, `Emphasis Effects`,
  `Exit Effects`, plus the `Path Animation` menu button. A path is therefore
  `Animations > Entrance Effects > Fly In`, and the `Animations` tab has to be
  pressed before any of them resolves.
- **The canvas click point has a formula**, and only its worked example was
  recorded. The driver no longer uses it — see "Why the driver selects shapes in
  the Selection Pane" — but it is the mapping to use for manual work. With the
  editor pane's frame in screen coordinates and the live zoom `z`, a slide of
  `W x H` points showing a shape centred at `(sx, sy)` points:

  ```
  shown     = (W * z, H * z)
  origin    = (pane.x + (pane.w - shown.w)/2, pane.y + (pane.h - shown.h)/2)
  point     = (origin.x + sx * z, origin.y + sy * z)
  ```

  The 2026-10-31 measurement is the check: a 960x540 pt slide at 92% in a
  1258x540 pane at screen (254, 177) puts a shape centred at (140, 190) pt on
  screen (570.2, 373.4). This assumes the slide is **centred** in the pane,
  which holds when the canvas is not scrolled.
- **sdpm names a shape from its geometry, not from the element id.** The capture
  deck asks for elements called `target001`… and the package carries
  `Rounded Rectangle 1`, `Rounded Rectangle 3`, and so on — and that first shape's
  **`p:cNvPr/@id` is `2`, not `1`**, so the name and the `spid` are two different
  numbers and both have to be read. `gui_capture_plan.py --generate` matches each
  target to the shape at the position the grid asked for and writes the name it
  finds into the plan, rather than either side assuming one.
- **A direction entry does not imply a GUI path.** The `Effect Options`
  direction labels depend on which effect is applied — Fly In offers
  `From Bottom`, Wheel offers `1 Spoke` — so Step 8's measurement is
  *effect x label -> presetSubtype*, and the 45 `MsoAnimDirection` entries
  cannot have a path derived from the entry alone. The driver can drive them
  once a plan names the prerequisite effect; the derivation refuses to invent
  one.
- **A gallery tile's title is a name correspondence, not a measurement.** The
  catalog key's last segment de-camel-cases to the label for all but three
  tiles (`Grow/Shrink`, `Grow & Turn`, `Shrink & Turn`). The driver matches the
  live title exactly and records a failure naming what it looked for, so a
  wrong label costs one record instead of producing a mislabelled capture.

### Assumptions only a live run can confirm

The driver is written against these and fails loudly on each rather than
guessing. Correct this section after the first run.

| Assumption | If it is wrong |
| --- | --- |
| The Selection Pane stays open, and keeps publishing rows, across a ribbon tab change and a `Save` | the next target's row lookup fails as `controlNotFound` and the run continues; it does not press on the previous shape |
| Writing `AXSelected` on a row selects the shape, and the row then reads back selected | the read-back times out per target **before** any press, so a selection that does not take costs a record rather than another shape's effect |
| A row's `AXIndex` is its absolute position in the outline, not its offset in a partial read | the row at a derived index publishes another shape's name and that target is `controlNotFound` naming both — provided the row publishes a name at all |
| A row the pane has not published yet appears within the timeout | that target is `controlNotFound` saying how many rows the last read published and which indices, so the operator can tell a missing row from a part-built pane |
| The pane's row order is the reverse of the slide part's shape order | same as the first row of this table: a name mismatch at the derived index |
| A row's name, **when the pane publishes one**, is exactly the package's `p:cNvPr/@name` | the order check above misfires and reports a mismatch that is only a naming difference |
| PowerPoint writes one `p:cTn` with a `presetClass` per applied effect, with the target shape's `spid` beneath it | attribution reads nothing and every target is rejected as `effectNotAdded`, loudly and on the first target |
| `Save` writes the new effect into the file before the next read | the attribution reads a stale package and rejects, rather than crediting the wrong effect |
| The `Path Animation` window lists presets directly, without a `Basic` grouping level | an extra level in the path is tolerated and recorded as `groupAbsent` |
| `Save` in the Quick Access toolbar overwrites in place with no Save As sheet | the driver waits, bounded, for the file to change and records a save failure per target |

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
  is the question Step 1 asked.
- Box's duration is **1600 ms**: PowerPoint wrote `p14:dur="1600"` and the
  ribbon's Duration field read `01.60`, which is what
  `ooxml.defaultDurationMs` now carries. (The later scripting-oracle run reads
  `2000` for every effect, because it set the entry effect and nothing else and
  the probe slide already carried that duration. A ribbon-applied value is the
  effect's own default; a scripted one is not.)

## What the Duration field does to an effect's XML — **MEASURED**

Measured 2026-11-01 on PowerPoint for Mac 16.113.1, by applying a tile and then
pressing `AXIncrement` on the ribbon's `Duration:` incrementor, saving, and
reading the behaviours back out of the package. 4 effects, 41 behaviours, two
ratios (×2 and a fractional one).

Two preconditions, both measured:

- **Selecting the shape is not enough.** With only the shape selected, the
  `Duration:` incrementor reads `''` and is **disabled**; the effect itself has
  to be selected, which pressing its gallery tile does. The incrementor is an
  `AXIncrementor` whose `AXValue` is **not settable** — its actions are
  `AXConfirm`, `AXIncrement`, `AXDecrement` — so a duration is reached by
  stepping, and one step is **0.25 s**.
- Changing the duration leaves `presetID`, `presetSubtype`, the behaviour count
  and the behaviour order **unchanged**, and touches **no attribute at all**:
  `@path`, `@by`, `@filter`, `@calcmode` and `@valueType` are identical before
  and after. Only time moves.

| Behaviour | What happens to `dur` and `delay` |
| --- | --- |
| `p:anim`, `p:animClr`, `p:animEffect`, `p:animMotion`, `p:animRot`, `p:animScale` | both scale in proportion to the effect duration |
| the visibility `p:set` | `dur` stays **1** and does **not** scale; its `delay` is **recomputed** from the new duration, not scaled |

At ×2 every animated value doubled exactly: Wave's `p:animMotion` 250→500 and
its four `p:animRot` 125→250 at delays 0, 250, 500, 750; entrance Bounce's 14
animated behaviours all doubled, down to `dur="26"`→`52`. Fly In's `p:set`
stayed at `dur="1"` while its two `p:anim` went 500→1000, which is what proves
the visibility behaviour is exempt rather than merely rounding to the same
number.

The exit visibility delay distinguishes the two candidate rules by exactly one
millisecond, and it was measured: Fly Out sits at `delay="499"` at 0.50 s, and
at 1.00 s it is **999**, not the 998 that scaling 499 would give. So an exit
hides the shape at `duration − 1` whatever the duration is.

**A fractional ratio is reproducible except on an exact tie.** At ×3/2 and
×9/8, every value whose exact product was not a half rounded normally
(1822→2050, 164→185, 26→29, 650→731, 1642→1847). The six values whose exact
product **was** a half split both ways — 580→652 and 332→373 down, 1324→1490,
676→761 and 125→188 up — which is the signature of PowerPoint's own internal
float precision rather than a tie rule that can be restated here. So:

- writing an effect **at its measured default duration is byte-exact**, because
  the measured integers are what get written;
- writing it at any other duration is proportional and **may differ by 1 ms**
  from PowerPoint on a `.5` boundary. That limit is a measurement, not an
  estimate, and it belongs in the catalog beside the scaled values.

## The route to a direction — **MEASURED, not yet captured**

Measured 2026-11-01. A direction persists as `p:cTn/@presetSubtype`, and 45 of
them are open. The route exists and it is the same shape as the Duration one:

1. select the shape through its Selection Pane row;
2. press the effect's gallery tile — this is what **selects the effect**, and
   `Effect Options` is `enabled=False` until it is, exactly as `Duration:` was;
3. press `Effect Options`, which opens a **window titled `Effect Options`**;
4. press the direction, save, read `presetSubtype` off the effect's `p:cTn`.

For Fly In the window published 14 titled items in two groups:

| Group | Items |
| --- | --- |
| `Direction` | `From Bottom`, `From Bottom-Left`, `From Left`, `From Top-Left`, `From Top`, `From Top-Right`, `From Right`, `From Bottom-Right` |
| `Sequence` | `As One Object`, `All at Once`, `By Paragraph` |

Two things follow for the plan. **The direction labels are per effect** — Fly In
offers eight compass directions, a Wipe offers four, a Wheel offers spoke counts
— so the plan is one target per (effect, direction) pair that the applied effect
actually offers, read from the window rather than from the catalog's 45 names.
And the `Sequence` group is the text-unit setting, which is already writable; it
is in the same window, so it costs nothing to confirm while there.

This probe ran with PowerPoint **not frontmost**, which is the other half of the
change: see the README. A capture of this size has to be able to run while the
operator works.

## Step 1 — transition directions on extension elements — **CLOSED**

Closed on 2026-10-31 by the scripting oracle, not from here. It applied all 207
`EPPEntryEffect` candidates **by enumerator code** and kept what PowerPoint
wrote, which is the mapping the catalog is keyed on; applying by GUI label
cannot produce it — Box ▸ "From Right" writes `p14:prism isInverted="1"` with
no `dir`, while `entry effect box right` writes `dir="r" isInverted="1"`, so the
label and the enumerator are not the same value.

Evidence: `tests/fixtures/animations/oracle-16.113.1/`. The entries carry
`verification: "scriptingOracleCapture"` and a `capture` block naming the slide
and the measured attributes. Nothing here needs recapturing unless the
application version changes; if it does, rerun the oracle rather than the GUI.

The capture also corrected 15 directions the catalog had read off the
enumerator's name — `entry effect cube right` is `dir="u"`, `cube up` is
`dir="r"` — and moved `entry effect wheel reverse 1 spoke` from a guessed
`reverse` attribute on `p:wheel` to the `p14:wheelReverse` element PowerPoint
actually writes.

## Step 2 — Page Curl Single and the mirror variants — **CLOSED**

Closed by the same run. `entry effect page curl single left/right` write
`p15:prstTrans prst="pageCurlSingle"`, and the mirror of each `p15:prstTrans`
variant is carried by `invX="1"` on the **left**-hand enumerator, which is the
opposite of what the catalog had inferred for Airplane, Origami and Wind.

## The per-effect settings surface — **there is no modal dialog on Mac**

Steps 3 to 5 all read the same surface, and it is not the one the Windows
documentation describes. **PowerPoint for Mac 16.113.1 has no "Effect Options"
dialog with Effect / Timing / Text Animations tabs.** Those settings sit inline
in the Animation Pane as four collapsible sections, so **no double-click is
needed and none is available**: this driver posts no mouse events, and every
section answers `AXPress`.

The route, measured 2026-11-02 on a deck with a motion path selected:

1. Ribbon ▸ **Animations** tab. `Animation Pane` is a **`switch`**, not a
   button — toggling it adds a second tab to the pane tab bar
   (`tablist "Tab bar, 2 tabs"`), and the pane's own tab is named
   **`Animations`**, not "Animation Pane".
2. Inside `group:Animations` the lower `scrollarea` carries the AX identifier
   **`SettingsScrollView`**. Its direct children are four `disclosure` controls,
   each offering `Click` / `Expand` / `Collapse`:

   | Disclosure | AX identifier | What it holds |
   | --- | --- | --- |
   | `Effect Options` | `_NS:236` | `Property:`, `After animation:`, `Sound:`, and 4 checkboxes |
   | `Timing` | `_NS:843` | `Start:`, `Duration:`, `Delay:`, `Repeat:`, `Rewind when done playing` |
   | `Text Animations` | `_NS:774` | text build levels (Step 7) |
   | `Triggers` | `_NS:732` | trigger conditions |

3. `expand` each section you need. Both `Effect Options` and `Timing` verified
   `delivered_verified` with `states: ["expanded"]`, `value "1"`.

**Two different surfaces are both named `Effect Options`.** The ribbon's
`Effect Options` **menubutton** opens its own window and carries the direction /
shape options measured for the 133 effect-option values ("Driving mechanics"
above). The Animation Pane's `Effect Options` **disclosure** is this one. They
are unrelated; resolving by name alone picks the wrong one.

### Reading a popup inside the pane

Each combobox opens as a `menu` **surface**, not as a separate window the way
the ribbon's popups do. Click the combobox, let it settle, then
`snapshot --surface menu`. Two cautions, both hit during the 2026-11-02 pass:

* A snapshot issued immediately after the click returns `TIMEOUT`
  (`surface_read`, `ax_error -25204`). Allow ~1.2 s.
* Under memory pressure a single write-type call held its lease 5–10 s. Six
  popups chained into one process ran past the tool timeout and produced
  nothing. **Enumerate one popup per process** — `enum_anim_pane.py --index N`.

Close every popup with `escape` before touching the next control.

## Step 3 — After animation (dim, hide, hide on next click)

**The route is measured; the values are not yet captured.**
`Effect Options ▸ After animation:` defaults to `Don't Dim` and offers 12 items:

| Item | Role | Closes |
| --- | --- | --- |
| 8 scheme swatches: Background, Text and Lines, Shadows, Title Text, Fills, Accent, Accent and Hyperlink, Accent and Followed Hyperlink | `button` | `animation.afterAnimation.dim` |
| `More Colors...` | `menuitem` | `animation.afterAnimation.dimColor` |
| `Don't Dim` | `menuitem` | the default |
| `Hide After Animation` | `menuitem` | `animation.afterAnimation.hide` |
| `Hide on Next Mouse Click` | `menuitem` | `animation.afterAnimation.hideOnNextClick` |

The 8 swatches are the **scheme** colours, so a dim records a theme-colour
reference rather than an RGB literal; `More Colors...` is the arbitrary-RGB
route. Capture one swatch and one `More Colors...` value to tell the two
storage forms apart.

What to look for: whether PowerPoint writes `p:cTn/@afterEffect`, an extra
`p:set` on `style.visibility`, or a trailing `p:animClr`, and where the dim
colour lives.

## Step 4 — Effect sound and Stop previous sound

Same section, `Sound:` dropdown, default `[No Sound]`. The popup offers **22
items**: `[No Sound]`, `[Stop Previous Sound]`, 19 named built-ins (Applause,
Arrow, Bomb, Breeze, Camera, Cash Register, Chime, Click, Coin, Drum Roll,
Explosion, Hammer, Laser, Push, Suction, Typewriter, Voltage, Whoosh, Wind) and
`Other Sound...`.

Capture one built-in and one `Other Sound…` WAV, plus `[Stop Previous Sound]`.
Record the media part path, the content type and the relationship type, not just
the XML: REQ-5.7 needs the relationship closure. This closes
`animation.sound.effect`, `animation.sound.stopPreviousSound`,
`transition.sound.effect` and `transition.sound.loopUntilNext`.

## Step 5 — Timing: rewind, smooth start/end, bounce end

All four are checkboxes, and **two of them default to on**, which inverts the
usual capture: the value that writes bytes is the *cleared* one.

| Setting | Control | Section | Default on a motion path |
| --- | --- | --- | --- |
| `smoothStart` | checkbox `Smooth Start` | `Effect Options` | **checked** |
| `smoothEnd` | checkbox `Smooth End` | `Effect Options` | **checked** |
| `bounceEnd` | checkbox `Bounce End` | `Effect Options` | cleared |
| `rewind` | checkbox `Rewind when done playing` | `Timing` | cleared |

So capture **both** states of each, not just the non-default one: a default-on
setting's cleared state is what has to be identified on read-back. A fifth
checkbox, `Auto-reverse` (cleared), sits beside them and has no catalog entry
yet. This closes `animation.timing.{rewind,smoothStart,smoothEnd,bounceEnd}`.

Two neighbouring popups are already fully enumerated and need no discovery
pass, only measurement:

* `Timing ▸ Repeat:` — `(none)` (default), `2`, `3`, `4`, `5`, `10`, `Custom:`,
  `Until Next Click`, `Until End of Slide`.
* `Timing ▸ Duration:` — `5 seconds (Very Slow)`, `3 seconds (Slow)`,
  `2 seconds (Medium)` (default), `1 seconds (Fast)`,
  `0.5 seconds (Very Fast)`, plus a free `seconds` field.

`Timing ▸ Start:` offers exactly the three conditions already supported: `On
Click`, `With Previous`, `After Previous`.

### `Property:` is effect-type-dependent

The first combobox under `Effect Options` is labelled `Property:` and its
contents change with the selected effect's type. With a motion path selected it
offers `Not Anchored` / `Anchored to Object` (the default). **Do not plan one
target list for it** — read it per effect type, the same way the galleries were
read rather than assumed.

## Step 6 — Motion paths

**The five gallery groups are measured.** They were
`semanticPreservationOnly` because PowerPoint stores a preset path as literal
path data in `p:animMotion/@path` and no available capture contained it. The
2026-11-01 GUI capture does, verbatim, all five at `origin="layout"`
`pathEditMode="relative"` `ptsTypes=""` and `dur="2000"`:

| Tile | `presetID` | `@path` |
| --- | --- | --- |
| Lines | 42 | `M 0 0 L 0 0.25 E` |
| Turns | 50 | `M 0 0 L 0.125 0 C 0.181 0 0.25 0.069 0.25 0.125 L 0.25 0.25 E` |
| Arcs | 37 | `M 0 0 L 0.067 0.04 C 0.081 0.049 0.102 0.054 0.124 0.054 C 0.149 0.054 0.169 0.049 0.183 0.04 L 0.25 0 E` |
| Shapes | 1 | a closed circle: `M 0 0 C 0.069 0 0.125 0.056 0.125 0.125 C … Z` |
| Loops | 26 | a closed figure-eight: `M 0 0 C 0 0.033 0.027 0.06 0.06 0.06 C … Z` |

The full strings are in the capture's `merged-evidence.json`; the two closed
paths are elided here only to keep the table readable, and the file is what the
catalog reads.

Still open: the entries behind **Add Animation ▸ More Motion Paths…**, which the
gallery does not list. For those:

1. Apply each entry, one per slide.
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

## Step 8 — Effect options, directions included — **MEASURED**

This step asked for the `direction name → presetSubtype` table. The capture
that answered it covers more than direction: **133 values across 6 settings**
(Direction 87, Amount 12, Zoom 12, Spokes 10, Shapes 8, Vanishing Point 4) on
33 of the 95 gallery tiles — the other 62 tiles expose only `Sequence`, which
is the text-unit setting and already writable.

Evidence: `effect-options-capture-2026-11-02/merged-effect-options.json`,
merged from one full pass plus five targeted re-measurements by
`effect_options_merge.py`. Reproduce with `discover_effect_options.py` →
`effect_options_plan.py` → `gui_capture.py` → `effect_options_resolve.py` →
`effect_options_merge.py --check`.

### The setting is not always in `presetSubtype`

The step assumed a subtype code per direction name. That is wrong for 7 of the
35 (effect, setting) groups, where **`presetSubtype` does not move at all** and
the setting lives entirely in the behaviour payload:

| Group | What carries the value |
| --- | --- |
| `emphasis.spin` Direction | sign of `p:animRot/@by` (±21600000) |
| `emphasis.spin` Amount | magnitude of `p:animRot/@by` (5400000 / 10800000 / 21600000 / 43200000) |
| `emphasis.growShrink` Direction | `p:animScale/p:by` x vs y (150000/100000) |
| `emphasis.growShrink` Amount | `p:animScale/p:by` x=y (25000 / 50000 / 150000 / 400000) |
| `emphasis.transparency` Amount | `p:animEffect/@prLst` `opacity: 1 − amount` |
| `entrance.floatIn` / `exit.floatOut` Direction | keyframe sign in `p:anim` |
| `entrance.shape` / `exit.shape` Shapes | `p:animEffect/@filter` |

In the remaining 28 groups the subtype and the behaviours **both** vary. No
group varies the subtype alone, so the behaviour payload is always the ground
truth and a variant cannot be expressed as a subtype number.

Direction numbering, where it is used, is shared across effects: From Top 1,
From Right 2, From Top-Right 3, From Bottom 4, From Bottom-Right 6, From Left
8, From Top-Left 9, From Bottom-Left 12, Across 10.

### The press inside `Effect Options` is intermittent

An `AXPress` on a value inside the `Effect Options` window reaches the control
and PowerPoint does not always act on it. The ribbon's own presses do not
behave this way. The failure is silent and indistinguishable from success,
because what it leaves behind is the effect's default — so the value reads as
a plausible measurement.

Measured attempt counts, each on a freshly generated single-target deck:

| Value | Took on attempt |
| --- | --- |
| `emphasis.spin` Half Spin | 2 |
| `emphasis.spin` Quarter Spin | 3 |
| `entrance.flyIn` From Right | 3 |
| `emphasis.transparency` 25% | 3 |
| `entrance.stretch` From Top | **4** |

Three values reached `resolved.json` wrong before this was understood:

| Value | Recorded | Measured |
| --- | --- | --- |
| `entrance.flyIn` From Right | `presetSubtype` 4 (From Bottom's) | `presetSubtype` 2 |
| `entrance.stretch` From Top | `presetSubtype` 10 (Across's) | `presetSubtype` 1 |
| `emphasis.transparency` 25% | `opacity: 0.5` (50%'s) | `opacity: 0.75` |

**Do not capture an effect option without the gate.** Put `verifyChange: true`
on the target (`effect_options_plan.py --verify-change`) and the driver saves
before the press, compares the shape's effects after it, and retries up to
`--value-press-attempts` (default 8) before refusing the target outright. The
comparison covers the behaviours, not just `p:cTn`: Grow/Shrink's `Huge` and
its default carry identical preset attributes and differ only in
`p:animScale/p:by`.

Two further conditions matter, both measured:

- **Generate a fresh deck.** `From Right` failed 4 of 4 attempts on a deck
  earlier presses had already touched, and took on the third on a new one.
- **One target per deck helps.** `transparency` 25% failed 4 of 4 on a
  two-target deck and took on the third alone.

`effect_options_merge.py --check` is the standing guard, and
`test_every_effect_option_is_measured_and_no_two_values_agree` runs it: two
values of one setting cannot produce the same OOXML, so a collision means a
press did not take. That check is what found all three errors above.

### Close the decks between runs

PowerPoint keeps every capture deck open. Eight accumulated during this work.
Only the active document publishes a ribbon, so `document_window` still
resolved correctly and `assert_ready` would have refused a wrong one — but the
decks are what "a deck earlier presses had already touched" means, and the
`Effect Options` window is resolved **by name**, not per document. Close them.
`osascript` and `agent-desktop close-app` are both unavailable under the
gateway sandbox; close each window through its title-bar `Close` button ref and
verify by re-listing, because PowerPoint answers that click with
`APP_UNRESPONSIVE` even when the window does close.

## Step 9 — SmartArt and chart builds

Reached through the Animation Pane's settings sections, not a dialog — see "The
per-effect settings surface". **Which sections exist depends on what is
selected**: the 2026-11-02 read, with a motion path on a plain rectangle,
returned exactly four (`Effect Options`, `Timing`, `Text Animations`,
`Triggers`) and **no SmartArt or Chart section**. So the first move here is to
select a SmartArt graphic and re-read the disclosure list, the same way
`Property:` has to be re-read per effect type. Do not assume a
`SmartArt Animation` section until a read returns one.

Then set **Group graphic** for each value, and **Group chart** on a
clustered-column chart, and confirm the `p:bldDgm/@build` and `p:bldGraphic`
forms the catalog predicts from `ST_AnimationDgmBuildType` and
`ST_AnimationChartBuildType`.

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

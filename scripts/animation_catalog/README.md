# PowerPoint animation catalog tools

Development-only tools in this directory create native PowerPoint evidence used by sdpm's checked-in animation and transition catalog. Runtime generation never invokes PowerPoint, AppleScript, or GUI automation.

## Morph spike

Run from the repository root:

```bash
uv run python scripts/animation_catalog/morph_probe.py --verify-package
```

The probe applies Microsoft's documented forced-Morph naming convention: matching adjacent objects are named with the same `!!`-prefixed Selection Pane name. It builds destination slides for `byObject`, `byWord`, and `byChar` using the Office 2015/09 `p159:morph` transition inside `mc:AlternateContent`, with a standard fade fallback.

The automated probe verifies package structure only. This dashboard's sandbox cannot control PowerPoint through Apple Events (`-10004` privilege violation), so visible interpolation versus cross-fade is verified once in the final PowerPoint acceptance flow.

Source: [Morph transition: Tips and tricks](https://support.microsoft.com/en-us/office/morph-tips-and-tricks-bc7f48ff-f152-4ee8-9081-d3121788024f)

## Capability catalog

Two checked-in artefacts, with different owners:

| File | Owner | Role |
| --- | --- | --- |
| `sdpm/references/catalogs/powerpoint-gui-surface-16.113.1.json` | hand-maintained | the versioned **expected universe**: every GUI control/value with its discovery evidence, persistence flag, verification method and expected disposition, plus the assignment of all 435 scripting candidates to a GUI surface |
| `sdpm/references/catalogs/powerpoint-animation-catalog.json` | generated | the **derived catalog**: full semantic JSON, OOXML mapping metadata, capability level, evidence and provenance per entry |

`generate.py` writes the second file and the generated candidate arrays inside `powerpoint.applescript`. The manifest is never written by a script, which is what lets `--check` catch drift in either direction (REQ-7.4).

```bash
# verify the checked-in pair and the oracle (no network, no PowerPoint)
uv run python scripts/animation_catalog/generate.py --check

# the same, but fail if the local scripting definition or the oracle is missing
uv run python scripts/animation_catalog/generate.py --check --require-sdef

# deterministically regenerate the catalog and the oracle's candidate arrays
# (needs PowerPoint installed; reads its scripting definition, never runs it)
uv run python scripts/animation_catalog/generate.py --write
```

`--check` compares four independent inputs and reports every disagreement:

- the local `PowerPoint.sdef` candidate set against the manifest and the catalog — missing and extra candidates, and four-char code drift;
- manifest expectations against catalog dispositions — status and `guiKey` drift, GUI items accounted on one side only;
- required metadata — fixed `generatedAt`, manifest linkage, a reason on every non-accepted entry, `semanticJson` plus `ooxml` on every accepted entry, a pinned fixture behind every `nativeTemplate` claim, and a documented gap behind every `semanticPreservationOnly` claim;
- the AppleScript oracle — all 435 candidate names and codes against the sdef, no empty candidate array or unfinished-work marker, and the object-model constructs the scripting definition actually declares (see [the oracle section](#powerpoint-oracle-and-gui-only-values));
- byte-level drift against a deterministic regeneration of both the catalog and the oracle's generated region.

Without PowerPoint installed, `--check` skips only the sdef comparison and still runs every structural and drift check, so CI stays green on machines that have no Office.

### Candidate universe

435 candidates, read from the locally installed scripting definition:

| Enumeration | Count | GUI surface |
| --- | --- | --- |
| `MsoAnimEffect` | 150 | Animations gallery, More … Effects dialogs |
| `MsoAnimDirection` | 45 | Effect Options ▸ Direction |
| `MsoAnimTriggerType` | 5 | Animations ▸ Start |
| `MsoAnimateByLevel` | 12 | Effect Options ▸ Text / Chart Animation ▸ Group |
| `MsoAnimTextUnitEffect` | 3 | Effect Options ▸ Effect ▸ Animate text |
| `MsoAnimAfterEffect` | 4 | Effect Options ▸ Effect ▸ After animation |
| `MsoAnimType` | 9 | Animation Pane behaviour primitives |
| `EPPEntryEffect` | 207 | Transitions gallery and Effect Options |

Animation-relevant enumerations outside that set are listed in the manifest's `supplementaryEnums` with an explicit disposition, so nothing disappears quietly.

### Capability levels

Every accepted entry declares how far its evidence actually reaches. Task 4's writer must branch on this rather than assume a usable template exists.

| Level | Meaning | Writer action |
| --- | --- | --- |
| `nativeTemplate` | exact OOXML captured from retail PowerPoint for this value; `evidence.fixture` names the artefact | emit the captured form |
| `presetMapping` | the element, attribute or identifier is fixed by a normative ECMA-376 enumeration, or corroborated by two independent sources; no visual capture | emit the mapping; schedule read-back |
| `semanticPreservationOnly` | the JSON round-trips, but the OOXML identifier or geometry is **not** established; `ooxml.gap` says exactly what is missing and `ooxml.requiresCapture` is set | do not guess an identifier — emit a documented fallback or defer to Task 8 |

Two gaps are worth knowing before reading the catalog:

- **`MsoAnimEffect` ordinals above 31 have no established `presetID`.** The ordinal equals the OOXML entrance/exit `presetID` only up to 31. Above that the numbering diverges (`msoAnimEffectLightSpeed` is 32 but saves 34; `msoAnimEffectFold` is 53 but saves 58). Where a gallery tile has the same name, the catalog records it under `ooxml.nameMatchedGalleryItem` with `nameMatchConfidence: nameMatchOnly` — a lead to verify, not a mapping to trust.
- **Preset motion paths carry literal path data.** `p:animMotion/@path` is the payload and the `presetID` is informational, so every motion-path entry stays `semanticPreservationOnly` until the geometry is captured.

### Maintaining the manifest

Edit `powerpoint-gui-surface-16.113.1.json` by hand when the GUI surface changes, then regenerate and check:

1. Bump `manifestVersion` (the catalog's `baseline.guiManifest` pins it, so a stale catalog fails `--check`).
2. Add or change `items` entries. Every item needs `control`, `value`, `surface`, `sourceEvidence`, `persisted`, `verificationMethod` and `status`.
3. Add or change `candidates` entries. Every candidate needs `enum`, `enumerator`, `code`, `guiKey` and `status`.
4. Teach `generate.py` the matching evidence — a new GUI item with no generator evidence fails `--check` rather than being silently accepted.
5. Run `--write`, then `--check --require-sdef`, then `uv run pytest tests/test_animation_catalog.py -q`.

A PowerPoint upgrade that changes an enumeration shows up as a missing or extra candidate, which is the point: the manifest, not the generator, defines what complete means.

### Evidence sources

The catalog records provenance for every external input in `provenance.references`. No external code or fixture bytes are copied into this repository; the OOXML facts were re-derived and the generator is original work.

| Source | Pin | License | Used for |
| --- | --- | --- | --- |
| [`office-kit/pptx`](https://github.com/office-kit/pptx) | `18b7e75c` | MIT | 95 animation gallery, 3 text-build and 49 transition native fixtures saved by PowerPoint for Mac 16.113.3, plus their capture provenance |
| [`ChristopherVR/ooxml`](https://github.com/ChristopherVR/ooxml) | `e269a0bb` | Apache-2.0 | COM-derived entrance/exit and emphasis `presetID` tables, and its documented ordinal/`presetID` divergence above 31 |
| `PowerPoint.sdef` | local 16.113.1 | not redistributed | the candidate universe: enumerator names and four-char codes |
| ECMA-376 Part 1 PresentationML | — | — | normative transition elements, `ST_TLTimeNodeType`, `ST_IterateType`, chart and diagram build types |

The captured fixtures come from 16.113.**3** while the baseline is 16.113.**1**. That difference is recorded in `provenance.references[].capturedApplicationVersion` and is one of the things Task 8's read-back has to confirm.

## PowerPoint oracle and GUI-only values

`powerpoint.applescript` is the development-only scripting oracle. It drives the AppleScript dictionary only — no VBA anywhere. Nothing in sdpm's runtime, CLI, MCP servers, tests or CI runs it; a maintainer ran it once, on 2026-10-31, from a terminal holding the Automation grant. This dashboard still cannot: addressing PowerPoint from it is refused with a `-10004` privilege violation.

### What the 2026-10-31 run established, and what it did not

The run's three artefacts are checked in under `tests/fixtures/animations/oracle-16.113.1/` and are a **generator input**: `--write` folds them into the catalog, so a promoted value is derived from evidence in the repository rather than hand-edited into the JSON, and `--check` fails when the catalog and the capture disagree.

| | Result |
| --- | --- |
| **Transitions** | All 207 `EPPEntryEffect` candidates probed. 160 produced a `p:transition`; 157 of them are accepted mappings and are promoted, with `verification: "scriptingOracleCapture"` and `capture` naming the package, the read-back, the slide and the measured attributes. No transition entry is capture-required any more. |
| **Animations** | Nothing. All 150 `MsoAnimEffect` candidates were refused with the same error, and no slide in the package carries a `p:timing` tree. |
| **The other six enumerations** | Never reached: the run aborted in `msoAnimDirectionConstants`. Their entries carry no `capture` block, and `provenance.scriptingOracle.unprobedEnumerations` names them. |

### `add effect` is not implemented in 16.113.1, so the dictionary cannot author animations

Every `MsoAnimEffect` probe failed with:

```
main sequence of timeline of slide N of presentation "Presentation1"
doesn't understand the "add effect" message.
```

`add effect` **is** declared in `PowerPoint.sdef` — the oracle's whole animation half was written against it — but PowerPoint for Mac 16.113.1 does not implement it on `main sequence`. The dictionary over-promises, and correcting the oracle's terminology cannot fix it: `probeAnimations`, `probeDirections`, `probeTriggers`, `probeBuildLevels`, `probeTextUnits`, `probeBehaviors` and `probeAfterEffects` all depend on first adding an effect.

**Do not rewrite the AppleScript animation probes.** Every animation-side capture — the remaining capture-required entries and the unresolved behavior payloads — has to go through the GUI procedure in [`computer-use.md`](computer-use.md). The transition half of the oracle is worth keeping, and is the better route where it works, because it applies a candidate **by enumerator code** and so yields the enumerator → OOXML mapping the catalog is keyed on; the GUI applies by label and cannot.

### Where a captured duration is and is not evidence

All 160 captured transitions carry `spd="slow"` and `p14:dur="2000"`. The probe set each slide's `entry effect` and nothing else, so that is the duration the script-created probe slide already held, not the effect's own default — a per-effect default could not be identical across 160 effects, and the Box tile is 1600 ms in both its native capture and the Transitions ribbon. The capture is therefore recorded per entry as `capture.transitionAttributes`, `provenance.scriptingOracle` explains it, and `ooxml.defaultDurationMs` keeps its native-capture value.

### It only launches PowerPoint when a maintainer says so

The run handler needs two arguments and refuses to send a single Apple event without the second one:

```bash
osascript scripts/animation_catalog/powerpoint.applescript \
  /absolute/path/to/output-dir --run-powerpoint
```

Without `--run-powerpoint` it errors out before the first `tell application` block. `tests/test_animation_catalog.py` asserts that the consent argument appears nowhere except the oracle, the generator that checks it, this README and the test itself, so `--check` and `pytest` cannot start PowerPoint even by accident.

### Checking its syntax does not launch PowerPoint

Compiling resolves the terminology out of the application bundle's `PowerPoint.sdef`; it does not start the application:

```bash
osacompile -o /tmp/powerpoint-oracle.scpt scripts/animation_catalog/powerpoint.applescript
```

The test suite runs exactly that on macOS when PowerPoint is installed, and round-trips the result through `osadecompile` to prove the 435 constants are real enumerators rather than identifiers the compiler happened to tolerate.

### The candidate arrays are generated, not hand-pasted

Everything between `-- >>> BEGIN GENERATED sdef CANDIDATE ARRAYS >>>` and its end marker is written by `generate.py --write` from the locally installed scripting definition: three parallel arrays per enumeration — the constants, their sdef names, and their sdef codes — for all 435 candidates, including the 150 `MsoAnimEffect` and 207 `EPPEntryEffect` values. `--check --require-sdef` compares every name and every code in that region against the sdef, rejects an empty array or an unfinished-work marker, and requires the object-model constructs below.

A constant is named **by code**, not by term: `my enumConstant("pEeF00F60F55")` is the enumeration's four-character type code followed by the enumerator's own eight hex digits, and the oracle's `enumConstant` handler turns it into the Apple Event constant through AppleScript's raw constant syntax. A bare enumerator term is ambiguous two ways, and both are measured in `tests/test_animation_catalog.py`:

- `top`, `font bold`, `font italic` (`MsoAnimDirection`) and `dim` (`MsoAnimAfterEffect`) are also PowerPoint **property** names, so the compiler builds a property reference and evaluating one raises `-1728`. That is what aborted the 2026-10-31 run, after 357 candidates had been applied.
- `horizontal` and `vertical` (`MsoAnimDirection`) compile to constants of a **different enumeration** — `TxOr`, text orientation. Nothing fails: the probe would apply a text orientation and the record would name the direction that was asked for.

Naming every candidate by code removes both classes by construction rather than by keeping a list of the terms known to collide. A raw `«data pEeF00F60F55»` literal would compile, but its AppleScript class is `data` rather than `constant`, so it compares unequal to the value PowerPoint reports back and every record's `applied` field would be `null`; the constant `enumConstant` builds compares equal to the term it names, which the test suite checks for all 435 candidates offline.

### The object model it uses

| Candidate | How the oracle applies it | How the value comes back |
| --- | --- | --- |
| `EPPEntryEffect` | `set entry effect of slide show transition of theSlide to …` | `entry effect of slide show transition of theSlide` |
| `MsoAnimEffect` | `add effect (main sequence of timeline of theSlide) for theShape fx … trigger on page click` | `animation effect type of theEffect` |
| `MsoAnimDirection` | `set direction of effect parameters of theEffect to …` | `direction of effect parameters of theEffect` |
| `MsoAnimateByLevel` | `add effect … level … trigger on page click` | `build by level of effect information of theEffect` |
| `MsoAnimTextUnitEffect` | `convert to text unit effect … Effect … unit …` | `text unit effect information of effect information of …` |
| `MsoAnimType` | `add behavior theEffect type …` | `animation behavior type of theBehavior` |
| `MsoAnimTriggerType` | `add effect … trigger …` | **not readable**: neither `effect` nor `timing` exposes a trigger property |
| `MsoAnimAfterEffect` | **not settable**: `after effect information` is read-only | — |

A slide's transition is a property of its own `slide show transition` object and animations hang off `timeline` → `main sequence`, not off the slide. The first draft of this file had neither, plus empty candidate lists and a constant mapper that raised on every name; `--check` now fails on all of those. Everything in the `MsoAnim*` rows of that table is declared by the dictionary and refused by the application — see `add effect` above.

### One failed probe no longer discards the run

`captureCatalog` dispatches the eight probes through `runProbe`, which contains each one: a failure becomes a `{"record": "probe", "rejected": true, …}` line and the run continues to the next probe, `saveSnapshot` writes the package after every probe, and `savePackage` is reached whatever happened. A capture run is expensive and partially valuable by nature — the 2026-10-31 run applied 357 candidates and then lost all of them to one bad term in the fourth probe, because the failure propagated out before the save; only a hand save of the still-open deck recovered the evidence that is now checked in.

### The values the dictionary cannot report

The oracle saves its probe deck (`save probe in (POSIX file packagePath) as save as Open XML presentation`) and the Python side reads the rest out of the package — no PowerPoint, no network:

```bash
uv run python scripts/animation_catalog/generate.py --parse-oracle /absolute/path/to/output-dir
```

That reads `powerpoint-oracle.pptx` part by part and joins it with `powerpoint-readback.jsonl` on the probe slide index, reporting:

- `p:transition`, its attributes, and which `mc:Choice`/`mc:Fallback` branch it came from, with the `Requires` prefix;
- `p:cTn/@presetClass`, `@presetID`, `@presetSubtype`, `@nodeType` and `@afterEffect`, with the behaviour elements under each preset node;
- `p:cond/@evt` start conditions, `p:iterate/@type`, `p:bldP`/`p:bldDgm` builds and `p:animMotion/@path` geometry;
- a `unresolvedCandidates` list, so a candidate whose evidence is still missing is named rather than quietly dropped.

Nothing in that output is promoted to a capability level automatically. A maintainer decides, and the catalog entry then names the artefact the claim came from.

`computer-use.md` covers the remaining values no offline source and no dictionary call can settle, with reproducible steps, required evidence and a logging format keyed to the catalog entries they would promote.

## GUI capture driver

Every remaining animation value has to be applied through the ribbon, and the macOS Accessibility API is reachable from Python here, so the four calls per value that `computer-use.md` measures are a loop inside one process rather than four agent turns. Two development-only modules do that, and like the oracle, nothing in sdpm's runtime, CLI, MCP servers, tests or CI invokes either.

| File | Role |
| --- | --- |
| `gui_capture_plan.py` | derives the target list from the catalog's own gaps, and builds the capture deck that list implies |
| `gui_capture.py` | drives PowerPoint: select a target's own shape by its Selection Pane row, press by title, save, attribute the new effect to that shape |

### It selects a shape through its Selection Pane row, because clicking the canvas did not work

A canvas shape has no accessibility element, so shape selection used to be a
synthetic global mouse event at a point derived from the package geometry, the
live editor-pane frame and the live zoom. It never became reliable: watching a
run, the pointer landed in the right place and the shape stayed unselected,
while the same click by hand always worked. Pacing the event — a click state, a
settle before the button-down, a hold, and a 0.35 s settle after the up — helped
without fixing it. The last run of that version captured **2 of 12** attempted
targets; the other ten were rejected as `effectNotAdded` with "no new effect
appeared", which is what a click that did not change the selection looks like,
because the gallery press then replaced the *previously* selected shape's
effect.

Canvas shapes have no element, but **their Selection Pane rows do**. The driver
opens `Home ▸ Arrange ▸ Selection Pane...` once per run and selects each target
by **setting `AXSelected` on that shape's row** — there is no `AXPress` on a row
— then reads the row back to confirm. No coordinates, no pointer, no zoom, no
editor-pane frame and no settling.

A row is addressed by **index**, which is the shape's position in **reverse
z-order**, read offline from the package and matched against the row that reports
that `AXIndex`. The row order was verified against the live pane twice at 152
rows with 0 mismatches.

Two keys were tried and discarded, and both failures are measured. A **name**
cannot be the key: a row's `title` is `None` and its name is the `value` of a
descendant `AXStaticText` that only exists once the row has been scrolled into
view, so one run's batches read 80 names, then 54, and rejected 11 targets as "no
Selection Pane row is named ..." for rows that were selectable throughout. An
**offset into `AXRows`** cannot be the key either: the pane published 43, 54, 61,
63, 74, 88 and 91 rows on consecutive reads of the same 152-shape slide, because
it rebuilds while the application works, and that rejected 7 more targets. Every
row publishes its own `AXIndex` in both states, so that is what a row is found
by, and a read that does not contain the row is retried until it does.

The name is still checked whenever the pane publishes one, as a check on the
order rather than a lookup: if the row at an index is named something other than
the shape expected there, the target is refused. That is what stands between a
renumbered pane and a value applied to the wrong shape under the right key, which
no later gate can undo.

So `read_canvas_geometry`, `canvas_point`, `read_shape_center_pt`, `parse_zoom`
and the `--pane-frame` / `--pane-role` / `--zoom` options are gone, along with
the backend's `click`. `computer-use.md` records the measured pane mechanics
under "Why the driver selects shapes in the Selection Pane", and keeps the
canvas formula for manual work only.

### It does not select slides, because that is what failed

A live run of the first version — one slide per target, selected in the
navigator — returned **76 records, 0 captured, 76 rejected**, with no record
getting as far as pressing a control. The navigator's cells expose no
accessibility actions and `kAXSelected` never reads back true, so the first six
targets timed out; and the navigator publishes only the cells currently
**scrolled into view**, six of seventy-six, so the rest were not addressable at
all.

Slide selection is therefore gone, together with the thumbnail lookup and the
`Has Animation` check that depended on it. `computer-use.md` records both
failures under "Why the driver does not select slides", and
`tests/test_animation_gui_capture.py` fails if either function's name comes back.

### The plan is derived, so it cannot drift

A hand-written target list stays the same length when a capture closes an entry, which is exactly when it stops being true. So the plan is read out of `powerpoint-animation-catalog.json`: the entries whose `ooxml.requiresCapture` is true, restricted to the key namespaces the GUI can address, with the GUI path each entry's own metadata implies.

```bash
uv run python scripts/animation_catalog/gui_capture_plan.py --summary
```

Four lists come out, because "not in the plan" has four different meanings and none of them is "dropped":

| List | Count today | What it is |
| --- | --- | --- |
| `targets` | 0 | GUI-addressable and resolvable by title in one press. **Empty, because every gallery gap is closed** — 76 captured on 2026-11-01 (71 gallery tiles plus 5 motion-path presets), and 16 more reached through their own default effect option, whose measured behaviours are the tile's — and the plan is the catalog's own open gaps. A tile added to the gallery tables, or a gap reopened, appears here again |
| `deferredTargets` | 51 | GUI-addressable namespace whose metadata implies no pressable path: the 45 `Effect Options` directions (their labels depend on which effect is applied), 3 After animation values (a dialog behind a prerequisite effect), 2 Media tiles (need a media object on the slide), and the custom motion path (drawn on the canvas) |
| `setAsideScriptingEnumerators` | 185 | the `MsoAnim*` candidates. The GUI applies by **label**; a scripting enumerator is a different identity, so closing one here would state a name correspondence rather than measure a value |
| `gapsWithoutCaptureFlag` | 8 | GUI-addressable entries carrying an `ooxml.gap` and `powerPointReadBackRequired` but no `requiresCapture` flag — `computer-use.md` Steps 3 to 5. Listed so the selection rule's edge is visible rather than looking like coverage |

The driver supports a prerequisite press, so a deferral is a statement about the derivation, not a limit of the driver: a plan that names the prerequisite effect for a direction can be run.

### The capture deck is generated by committed code: one slide, many shapes

Today's 92 targets become **one slide** carrying one named shape each, laid out
as a **12x8** grid with the key's last segment as visible text under its own
shape, built through `sdpm.api.generate` with **both motion switches off** — in
`deck.json` and again as a caller override — so sdpm contributes no motion and
every `p:timing` tree in the saved package came from PowerPoint.

The grid was 8x10 with two-line labels, which left each shape 77x22 pt. A click's
accuracy was bounded by the **short** side, and 22 pt was too small: a live run put
71 presses onto five shapes, because a click that lands on empty canvas leaves the
previous shape selected and the next press overwrites **its** effect. Squarer cells
and a one-line label take the short side to 43.5 pt. The key itself is not lost —
it is in the plan, and each shape carries its ordinal.

Shape size and separation are **no longer load-bearing**, because nothing is
clicked: a shape is selected through its Selection Pane row. The deck is kept as
it is rather than regenerated, and the grid's separation checks stay, so a future
reader is not left wondering whether a tighter grid would change a capture.

```bash
uv run python scripts/animation_catalog/gui_capture_plan.py --emit-plan \
  --out /abs/out/plan.json \
  --build-deck /abs/out/deck \
  --generate /abs/out/capture-deck.pptx
```

The grid is derived from the target count and then checked rather than eyeballed:
no two shapes overlap, a shape's centre sits at least 10 pt inside its own edges,
and it clears every other shape by at least 10 pt, so a click aimed at a centre
cannot land on a neighbour. A count that does not fit one slide under those
constraints is split across as few slides as it can be and the plan's `deck`
block says so; one slide holds 128 at the 40 pt minimum short side, so 92 fits with room to spare.

`--generate` also reads every target shape's real name back out of the package,
matching each target to the shape at the position the grid asked for, and writes
the `target key -> shape name` mapping into the plan. sdpm names a shape from its
geometry rather than from the element id the deck JSON asked for: the first shape
is asked for as `target001` and the package calls it `Rounded Rectangle 1` while
giving it `p:cNvPr/@id="2"`, so the name and the `spid` are two different numbers
and the driver reads both.

### Running it

Open the generated deck in PowerPoint. It does **not** have to stay frontmost — a run
drives an occluded window and takes no focus, so keep working while it goes:

```bash
uv run --with pyobjc-framework-ApplicationServices --with pyobjc-framework-Cocoa \
  --with lxml \
  python scripts/animation_catalog/gui_capture.py \
    --plan /abs/out/plan.json --out /abs/out --document /abs/out/capture-deck.pptx \
    --drive-powerpoint
```

Three dependencies, and that is the whole list. **Quartz is not among them** — the only
binding that needed it was the mouse event, which went with the coordinate click.
`lxml` is: the package readers import it lazily inside the function, which keeps `--help`
working with nothing installed, and a run outside this repository's environment then
fails with `ModuleNotFoundError: No module named 'lxml'` at the first attribution unless
the invocation asks for it.

A line per batch goes to **stderr** while it runs — batch index, targets attempted,
captured so far, elapsed — so a 76-target run is distinguishable from a hang, while
stdout stays pure JSON for the summary.

**It does not move the pointer**, and it **does not need PowerPoint to be frontmost**. Every action is an `AXPress` or a single `AXSelected` write addressed to a named element, so no mouse event is posted, the pointer is never taken over, and an occluded window is still reached — the operator keeps the keyboard and the screen while a run proceeds. The driver still **refuses to start** unless PowerPoint's document window is the expected capture deck: an `AXPress` goes to whatever window the title resolution found, and the wrong document would mean pressing ribbon controls and `Save` on the operator's own deck.

Without `--drive-powerpoint` it sends nothing. `--help` and `--emit-record-schema` work with no accessibility bindings installed at all: pyobjc is imported inside the live backend, so importing the module never requires it and `tests/test_animation_gui_capture.py` runs against a fake.

### What it guarantees, and why each guarantee exists

- **One shape per target, and every press attributed to its own shape.** A gallery press *replaces* the effect of the **selected shape** rather than adding one, so a target owns a shape rather than a slide. After the press and the save, the slide must have gained at least one effect and **every** new effect's `p:spTgt/@spid` must be the selected shape's `p:cNvPr/@id`. (Not "exactly one": a compound value writes several `p:cTn` nodes, and the stricter form rejected a correctly applied target.) An effect on another shape is a `rejected` record naming **both** spids; a press that added nothing is a recorded failure. This gate is unchanged by the move to the Selection Pane, deliberately — it is what proved the click unreliable, and it is the only thing that makes a capture evidence.
- **Re-read and re-resolve by title before every press.** A press scrolls the gallery and renumbers it; a press aimed by a stale index applies the wrong effect while the record names the right one. Scopes are held as titles, never as elements, and a title matching two controls is a refusal rather than a choice.
- **A failure is recorded and the run continues.** A control that is absent, ambiguous, disabled, a verification that times out, or an effect that cannot be attributed becomes a `rejected` record with its error kind. The 2026-10-31 scripting run lost 357 applied candidates to one bad term because the failure propagated out before the save.
- **Every wait is bounded.** There is one `while True` in the module, inside the bounded poll, and a timeout is a recorded failure rather than a hang. Nothing blocks on the GUI.
- **One Save per batch of targets**, because the save is the measurement: the attribution reads the file Save writes, so there is no switch to skip it and a save that does not land rejects every target pressed into it rather than being a footnote on a passing one. The default batch is 10 and `--batch-size` changes it; `1` is a save per target. Each target is still attributed by **its own** `spid` against the saved package, and the batch adds a gate of its own — **no spid outside the batch may have gained an effect**, which fails the batch naming the stray — while a target whose own spid gained nothing is rejected on its own with the rest of the batch still credited. Each record carries its `batchIndex`, and `effectCount` is then the batch's before/after for the slide while `newEffectCount` is the target's own.

  What batching gives up, stated rather than implied: **crash granularity** (a crash costs the presses since the last save, which a resumed run re-presses because an uncaptured target has no record), and **telling two targets inside one batch apart when they swap effects** — if each gained one effect and nothing outside the batch did, the package cannot say whose value is whose. `--batch-size 1` gives both back. What bounds the second is that the mechanism which used to cause it, a selection that did not take, is caught by `select_shape`'s `AXSelected` read-back *before* any press, and a press landing outside the batch is caught by the stray-spid gate.
- **Cost is a correctness property, and it is measured rather than assumed.** A run of the previous version captured **7 targets in 28 minutes** — about four minutes each, every one correct and attributed. The mechanism worked; it was far too slow to reach 76. Timed live against the real window, best of three: one `find_all_by_title` over the whole window **6.4 s**, `selection_outline` **17.8 s**, walking only the pane's outline (762 nodes) 4.1 s, reading 152 row names 4.3 s. The window is **907 nodes, 762 of them the Selection Pane's rows**, and every accessibility attribute read is an interprocess round trip.

  The dominant cost was full-tree walking, not saving. Every lookup started at the window, so resolving a ribbon control traversed all 762 pane rows and resolving a row traversed the ribbon; and `document_window` identified the ribbon-carrying window by walking **each** of PowerPoint's four or five same-titled windows, from a function nearly every helper calls. Four changes, in descending order of what they were worth: lookups are **scoped to a container** (`Save` in the window's `AXToolbar`, tabs and galleries in the ribbon `AXTabGroup`, rows in the `AXOutline`), found by a search of the window's top levels that **stops at every container boundary** instead of descending through one; `document_window` probes each candidate's direct children; the window and its containers are resolved once per stretch of work and dropped at **every** press, every `AXSelected` write and every poll; and one Save judges a batch. A scope that cannot be identified **raises** — it never widens back to the window, because a lookup that quietly walked everything is exactly what this removed and nobody would look for it again.

  Measured against the test fake, whose pane carries 156 rows and which publishes the same four same-titled sibling windows: **2,218 attribute reads per target, down from 19,826 — 8.9x.** `tests/test_animation_gui_capture.py` counts the reads and budgets them at 3,000 per target, so a lookup that goes back to walking the window fails a test rather than costing an operator an afternoon.

- **Resumable.** An output directory that already has records skips the targets already captured and retries the ones that failed, restarting at the first uncaptured target whatever the batch boundaries were; `--force` reruns everything. The read-back is rewritten rather than appended to, so there is exactly one record per key. **`--force` wants a freshly generated deck**, because a re-press on a shape that already carries an effect *replaces* it rather than adding one, and the attribution gate requires a new effect — a forced rerun against an already-captured deck is rejected per target rather than credited on the previous run's evidence.

### Its output feeds `--parse-oracle`

The driver writes `powerpoint-readback.jsonl` in the shape the generator already consumes — an `{"record": "application"}` first line naming the PowerPoint version and the driver, then one record per target with the catalog key, the slide index, the GUI path applied, the shape name and `spid` it aimed at, the Selection Pane row it selected and that it selected by row rather than by click, the ribbon read-back (`Start:`, `Duration:`) taken while that shape was still the selected one, the `spid` the new effect was attributed to with that effect's own `p:cTn` attributes, how many `p:cTn` nodes appeared on that `spid`, the batch index whose Save judged it with that batch's before/after effect counts, whether it was rejected and any error — and copies the saved deck to `powerpoint-oracle.pptx` beside it, so the two join offline:

```bash
uv run python scripts/animation_catalog/generate.py --parse-oracle /abs/out
```

A GUI record carries `enum: "guiCapture"` with the catalog key as its enumerator, which is what the join is keyed on, and `code: null` — a GUI control has no four-character scripting code and inventing one would assert the very correspondence the capture does not measure.

That join is **by slide index**, and every target now shares one slide, so the merged view puts the whole slide's OOXML beside every candidate. The per-target evidence is therefore read out of the record rather than out of the join: match a record's `attributedSpid` against the `p:spTgt/@spid` of the effects in the merged `ooxml.timing`, or read its `effectCTn` directly. As with the oracle, nothing in that output is promoted automatically: a maintainer decides, and the catalog entry then names the artefact the claim came from.

# PowerPoint animation catalog tools

Development-only tools in this directory create native PowerPoint evidence used by sdpm's checked-in animation and transition catalog. Runtime generation never invokes PowerPoint, AppleScript, or GUI automation.

## Morph spike

Run from `/Users/naohitoa/dev/sdpm-animations`:

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
| `gui_capture.py` | drives PowerPoint: one slide per target, press by title, verify, read back, save |

### The plan is derived, so it cannot drift

A hand-written target list stays the same length when a capture closes an entry, which is exactly when it stops being true. So the plan is read out of `powerpoint-animation-catalog.json`: the entries whose `ooxml.requiresCapture` is true, restricted to the key namespaces the GUI can address, with the GUI path each entry's own metadata implies.

```bash
uv run python scripts/animation_catalog/gui_capture_plan.py --summary
```

Four lists come out, because "not in the plan" has four different meanings and none of them is "dropped":

| List | Count today | What it is |
| --- | --- | --- |
| `targets` | 76 | GUI-addressable and resolvable by title in one press — 71 gallery tiles plus 5 motion-path presets |
| `deferredTargets` | 51 | GUI-addressable namespace whose metadata implies no pressable path: the 45 `Effect Options` directions (their labels depend on which effect is applied), 3 After animation values (a dialog behind a prerequisite effect), 2 Media tiles (need a media object on the slide), and the custom motion path (drawn on the canvas) |
| `setAsideScriptingEnumerators` | 185 | the `MsoAnim*` candidates. The GUI applies by **label**; a scripting enumerator is a different identity, so closing one here would state a name correspondence rather than measure a value |
| `gapsWithoutCaptureFlag` | 8 | GUI-addressable entries carrying an `ooxml.gap` and `powerPointReadBackRequired` but no `requiresCapture` flag — `computer-use.md` Steps 3 to 5. Listed so the selection rule's edge is visible rather than looking like coverage |

The driver supports a prerequisite press, so a deferral is a statement about the derivation, not a limit of the driver: a plan that names the prerequisite effect for a direction can be run.

### The capture deck is generated by committed code

One slide per target, one named shape, the target key as visible text, built through `sdpm.api.generate` with **both motion switches off** — in `deck.json` and again as a caller override — so sdpm contributes no motion and every `p:timing` tree in the saved package came from PowerPoint.

```bash
uv run python scripts/animation_catalog/gui_capture_plan.py --emit-plan \
  --out /abs/out/plan.json \
  --build-deck /abs/out/deck \
  --generate /abs/out/capture-deck.pptx
```

`--generate` also reads the target shape's real name back out of the package and writes it into the plan, because sdpm names a shape from its geometry rather than from the element id the deck JSON asked for.

### Running it

Open the generated deck in PowerPoint, leave it frontmost, then:

```bash
uv run --with pyobjc-framework-ApplicationServices --with pyobjc-framework-Cocoa \
  --with pyobjc-framework-Quartz \
  python scripts/animation_catalog/gui_capture.py \
    --plan /abs/out/plan.json --out /abs/out --document /abs/out/capture-deck.pptx \
    --drive-powerpoint
```

**It moves the real pointer.** Canvas shapes have no accessibility element, so selecting one posts a global mouse event at a point derived from the package geometry, the live editor-pane frame and the live zoom. Everything else is `AXPress` and leaves the pointer alone. Because that one click lands wherever the frontmost window is, the driver **refuses to start** unless PowerPoint is frontmost and its document window is the expected capture deck; it cannot type into the operator's own work. Do not use the machine during a run.

Without `--drive-powerpoint` it sends nothing. `--help` and `--emit-record-schema` work with no accessibility bindings installed at all: pyobjc is imported inside the live backend, so importing the module never requires it and `tests/test_animation_gui_capture.py` runs against a fake.

### What it guarantees, and why each guarantee exists

- **One slide per target.** A gallery press *replaces* the shape's effect rather than adding one, so slide N's `p:timing` is evidence about target N alone.
- **Re-read and re-resolve by title before every press.** A press scrolls the gallery and renumbers it; a press aimed by a stale index applies the wrong effect while the record names the right one. Scopes are held as titles, never as elements, and a title matching two controls is a refusal rather than a choice.
- **A failure is recorded and the run continues.** A control that is absent, ambiguous, disabled, or a verification that times out becomes a `rejected` record with its error kind. The 2026-10-31 scripting run lost 357 applied candidates to one bad term because the failure propagated out before the save.
- **Every wait is bounded.** There is one `while True` in the module, inside the bounded poll, and a timeout is a recorded failure rather than a hang. Nothing blocks on the GUI.
- **Save after every target**, so a crash costs one target.
- **Resumable.** An output directory that already has records skips the targets already captured and retries the ones that failed; `--force` reruns everything. The read-back is rewritten rather than appended to, so there is exactly one record per key.

### Its output feeds `--parse-oracle`

The driver writes `powerpoint-readback.jsonl` in the shape the generator already consumes — an `{"record": "application"}` first line naming the PowerPoint version and the driver, then one record per target with the catalog key, the slide index, the GUI path applied, the ribbon read-back (`Start:`, `Duration:`), the thumbnail label, whether it was rejected and any error — and copies the saved deck to `powerpoint-oracle.pptx` beside it, so the two join offline:

```bash
uv run python scripts/animation_catalog/generate.py --parse-oracle /abs/out
```

A GUI record carries `enum: "guiCapture"` with the catalog key as its enumerator, which is what the join is keyed on, and `code: null` — a GUI control has no four-character scripting code and inventing one would assert the very correspondence the capture does not measure. As with the oracle, nothing in that output is promoted automatically: a maintainer decides, and the catalog entry then names the artefact the claim came from.

# What each effect option writes

Captured 2026-11-02 from PowerPoint for Mac 16.113.1, with PowerPoint **not
frontmost** throughout. **133 targets, 133 captured, 0 spid mismatches**, after
four resumed passes (40 → 11 → 4 → 2 → 1 remaining; every failure was
`AX error -25202`, a Selection Pane row caught mid-rebuild).

Each target presses twice: the gallery tile, because `Effect Options` is
disabled until an effect is selected, and then the value inside the window the
control opens.

## What it measures

| Setting | targets | resolved |
| --- | --- | --- |
| `Direction` | 87 | 87 |
| `Zoom` | 12 | 12 |
| `Spokes` | 10 | 10 |
| `Shapes` | 8 | 8 |
| `Vanishing Point` | 4 | 4 |
| `Amount` | 12 | 4 |
| **total** | **133** | **125** |

Fly In's eight directions carry eight `presetSubtype` values; a Wheel's spoke
counts are `presetSubtype` 1, 2, 3, 4 and 8, matching their labels. An `Amount`
is **not** a `presetSubtype` — Grow/Shrink's stays `0` and the amount lives in
`p:animScale`'s `p:by`, measured as `x=150000` by default and `x=400000` for
`Huge`.

## The press modifies in place — except for `Amount`

**125 of the 133 targets leave exactly one effect on their shape**, so the press
edits the applied effect rather than adding one. A single-target trial on
Grow/Shrink's `Amount` had shown two effects and the conclusion was generalised
from it; measuring all 133 showed only `Amount` ever adds.

Re-selecting the shape between the two presses was tried to stop the adding, and
it breaks the route: selecting the shape in the Selection Pane **deselects its
effect**, so `Effect Options` goes disabled and the next step times out. Either
the shape is selected or its effect is.

## The default is resolved inside the capture

`effect_options_resolve.py` reads the tile's default from the capture's **own**
targets: a tile has one target per value, each on its own shape, so a behaviour
fingerprint appearing on more than one of those shapes is the default and the
rest are values. Nothing external is consulted.

The first version compared against the 76-value capture instead and could not
resolve 58 of 133, because that capture holds only the tiles that *needed*
capturing — `Appear`, `Blinds`, `Wipe` and 21 others were already writable and
have no measured default anywhere.

## The 8 unresolved, and why they are recorded rather than guessed

All eight are `Amount` on Grow/Shrink or Spin, and all eight sit on shapes
carrying 2 to 4 effects. Three of those shapes were used by single-target trial
runs against the same open document before the full pass, so they carry trial
residue; the rest are the genuine add plus a repeat. With more than one effect
differing from the default, the package cannot say which press wrote which, so
the resolver reports `ambiguous` and the value is **not** promoted.

A clean re-run of the twelve `Amount` targets on untouched shapes closes them.

## Files

| File | What it is |
| --- | --- |
| `plan.json` | the 133 targets, each with its prerequisite tile and its shape |
| `powerpoint-readback.jsonl` | one record per target: the presses, the shape, the spid, the effects |
| `powerpoint-oracle.pptx` | the package those records were read from |
| `resolved.json` | per target: the measured effect, how it was written, and what distinguishes it |

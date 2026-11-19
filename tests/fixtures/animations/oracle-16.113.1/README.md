# PowerPoint scripting-oracle capture, 16.113.1

Output of `scripts/animation_catalog/powerpoint.applescript`, run 2026-10-31
from a Terminal holding the Automation grant for Microsoft PowerPoint. The sdpm
dashboard sandbox refuses Apple Events (`-10004`), so this cannot be produced
from an agent session.

| File | What it is |
| --- | --- |
| `powerpoint-readback.jsonl` | One record per probed candidate: requested enumerator, sdef code, probe slide index, what the dictionary reported, and any error. |
| `powerpoint-oracle.pptx` | The saved probe deck, 357 slides, one per candidate. |
| `merged-evidence.json` | `generate.py --parse-oracle` output: the read-back joined to the OOXML extracted from the package. Regenerate with `uv run python scripts/animation_catalog/generate.py --parse-oracle tests/fixtures/animations/oracle-16.113.1`. |

## What this capture establishes

**Transitions: complete.** 160 `EPPEntryEffect` candidates produced a
`p:transition`, closing **all 61** entries the catalog had marked
`requiresCapture`, with their real attribute sets — `entry effect box down` is
`p14:prism dir="d" isInverted="1"`, `entry effect airplane right` is
`p15:prstTrans prst="airplane"`.

196 candidates were rejected by PowerPoint. The `collapse*` and `crawl*`
families are the legacy per-shape entry effects that the catalog already
accounts for as `animation.legacyShapeEntryEffect`, so a rejection there is the
expected answer, not a gap.

## What it does NOT establish, and why

**Animations: nothing.** All 150 `MsoAnimEffect` candidates were rejected with
the same error:

```
main sequence of timeline of slide N of presentation "Presentation1"
doesn't understand the "add effect" message.
```

`add effect` is declared in `PowerPoint.sdef`, but PowerPoint for Mac 16.113.1
does not implement it on `main sequence`. No slide in the package carries a
`p:timing` tree. Correcting the oracle's terminology cannot fix this; every
animation-side capture has to go through the GUI procedure in
`scripts/animation_catalog/computer-use.md`.

## Why the run is incomplete

The script aborted in `msoAnimDirectionConstants` with `Can't get top (-1728)`:
the generated constants arrays emit bare sdef enumerator names, and `top` is
also a PowerPoint property name, so it compiles to a property reference. The
abort happened before `savePackage`, so the package here was saved by hand from
the still-open probe deck. `MsoAnimDirection`, `MsoAnimTriggerType`,
`MsoAnimateByLevel`, `MsoAnimTextUnitEffect`, `MsoAnimType` and
`MsoAnimAfterEffect` were never probed.

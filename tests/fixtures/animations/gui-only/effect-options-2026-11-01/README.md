# What each gallery tile's `Effect Options` window offers

Read 2026-11-01 from PowerPoint for Mac 16.113.1 by
`scripts/animation_catalog/discover_effect_options.py`, with PowerPoint **not
frontmost**. 95 tiles read, 0 failed.

This is a **discovery** pass: it records labels, not values. Nothing was saved
and no package was read. The `presetSubtype` behind each label is measured by
the capture run the plan derived from this file drives.

## Why it exists

A direction persists as `p:cTn/@presetSubtype`, and the catalog has 45
`MsoAnimDirection` names open. Those 45 cannot be planned from, because **the
labels are per effect**: Fly In offers eight compass points, Peek In four,
Checkerboard `Across`/`Down`, and 62 of the 95 tiles offer no direction at all.

## What it found

| Setting | (effect, value) pairs | distinct labels |
| --- | --- | --- |
| `Direction` | 87 | 36 |
| `Amount` | 12 | 12 |
| `Zoom` | 12 | — |
| `Spokes` | 10 | 5 |
| `Shapes` | 8 | 4 |
| `Vanishing Point` | 4 | 2 |
| **total** | **133** | |

**33 of the 95 tiles carry a setting; 62 carry none** beyond `Sequence`, which
is the text-unit setting and is already writable. So the surface to capture is
133 (effect, value) pairs rather than 45 directions — more precise in both
directions: more pairs than 45, across six settings rather than one, and
concentrated in a third of the gallery.

## How a heading is told from a value

Measured, after two wrong readings that are recorded in the script's docstring.
At depth 2 inside the window:

| Element | Meaning |
| --- | --- |
| `AXMenuButton`, `enabled=False` | a heading — `Direction`, `Amount`, `Spokes` |
| `AXMenuButton`, `enabled=True` | a value — `From Bottom`, `Clockwise`, `4 Spokes` |
| `AXGroup` at depth 2 | the colour picker; its 71 disabled `AXRadioButton` children sit at depth 3+ and are not settings of the effect |

A value belongs to the nearest heading before it. The window is **flat** — the
heading and its values are siblings — which is why grouping by the enclosing
element did not work and the first reading reported 79 directions for Spin.

## Files

| File | What it is |
| --- | --- |
| `effect-options.json` | one record per tile: every titled element of its window with role, enabled, selected and depth |
| `tiles.json` | the 95 tiles the pass walked, by gallery |

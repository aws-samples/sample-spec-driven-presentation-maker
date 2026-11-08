---
name: visual-forms
description: "Visual forms — when to draw a form instead of text, icon use and sizing, and the geometry of flow, cycle, hub, hierarchy, matrix, timeline, progress and other forms in slide JSON"
category: guide
---

# Visual forms

A slide is seen before it is read. When the content has a shape — steps, a loop, parts of a
whole, a centre and its satellites, a trade-off between two axes, a change from one state to
another, a quantity — draw that shape; keep sentences for claims that are sentences (a quote,
a takeaway). A card holding a paragraph is still text. Build each form from the style's
components (its node, connector, icon and marker treatment) with its tokens; the recipes below
give only the geometry. Everything the style's rules forbid stays forbidden; everything else
the content calls for may be drawn, at the style's density.

**Icons.** `search_assets("keyword")` → `"src": "assets:<source>/<name>"`. An icon stands for a
concept next to a short label (1–4 words): a list of concepts becomes icon + label rows, a card
gets an icon at its head, a node carries one; a single large icon may also be a slide's hero.
How it sits is the style's `icon`: a bare glyph, or on a shape behind it (the icon's `iconColor`
contrasting with that fill), in the text colour or colour-coded by category. One icon family per
deck (a general pack for concepts; `aws` for AWS services — those are multi-colour: no
`iconColor`, nothing drawn behind them). Size is relative: beside a line of text, 1.5–2 × its
line height; at the head of a card or node, 25–35 % of its shorter side; as a hero, large enough
to own its area. Icons in a row share one size and one baseline.

**Recipes** — N items in a region (`rx`, `ry`, `rw`, `rh`); rectangular node size
`w × h`, circle diameter `s`, gap `g`.

| Form | Use for | Geometry |
|---|---|---|
| flow | 3–6 ordered steps | Nodes in one `grid` row. Connector per pair: `line` from `(x_i + w, cy)` to `(x_{i+1}, cy)`, `arrowEnd`. Chevron row instead: `chevron` shapes (first may be `pentagon`), `x_{i+1} = x_i + w − notch + g`. |
| cycle | stages that repeat | Centre `(cx, cy)`, radius `r`; node `i` at `θ = −90° + 360°·i/N`: `x = cx + r·cosθ − s/2`, `y = cy + r·sinθ − s/2`. Clockwise connector: `arc` box `(cx−r, cy−r, 2r, 2r)`, `adjustments: [start, sweep]`, `arrowEnd`; shorten each sweep to clear the nodes. Or use a `block_arc` ring with markers at `ring_center_r`. |
| hub | a centre and 3–8 satellites | Satellites on the cycle geometry. Spoke: `line` from `c + R_c·u` to `p − R_s·u`, `u` the unit vector centre → satellite. No arrows unless the direction is the point. |
| hierarchy | parent → children, org, breakdown | One row per level from `grid`; `line` `connectorType: "elbow"`, `elbowStart: "vertical"` from the parent's bottom centre to each child's top centre. |
| matrix | two criteria, 2×2 | Two `line` axes crossing at the region centre, `arrowEnd`; axis names at the ends; quadrant names in the corners; items as markers at `(rx + tx·rw, ry + (1 − ty)·rh)`. |
| spectrum | one criterion, positions on it | One `line` with `arrowStart` + `arrowEnd`, pole labels at both ends, items as markers at `x = x0 + t·len`. |
| timeline | dated events | Baseline `line`; `oval` markers on it; date on one side, label on the other; alternate sides when labels are long. |
| stack | layers built on each other (architecture, maturity) | Full-width bands in one column from `grid`, bottom layer first in meaning; one icon + name at each band's left, what it adds on the right; the band the slide is about in the selected treatment. |
| funnel / pyramid | narrowing stages, layers | Stack `trapezoid`s. Pyramid: default orientation (narrow top), widths grow top → bottom, label in `text`. Funnel: widths shrink top → bottom and `flipV`; because `flipV` also flips shape text, omit `text` and add an upright centred `textbox` inset slightly from each shape box. |
| brace | several items → one conclusion | `right_brace` spanning the items' height; the conclusion beside it, centred on the brace. |
| progress | a share or completion | Ring: `donut` track `adjustments: [t]` + `block_arc` `[270, "N%", t]` on the same box, figure centred. Bar: track `rectangle` + filled rectangle of width `w·p`. |
| isotype | a count of things | One single-colour icon repeated on a grid; the counted share in the accent via `iconColor`, the rest muted. |
| before-after | a change of state | Two panels, the after panel in the style's `selected` treatment, an `arrow_right` (or connector) between them. |
| icon + label rows | a list of concepts | One `grid` row per concept; icon beside its 1–4 word label. Keep one source, size, baseline and token-driven `iconColor`; size the visible glyph to 1.5–2 × label line height. |
| big number | one figure carries the claim | The style's `metric` component: figure at metric scale, unit smaller, one comparator line. |

Quantities with more than one series or period are a native `chart`; exact values to compare
across rows are a `table` — see their guides.

Checks: connectors end at a node's edge, never its centre or inside its label; labels clear the
connectors; nodes within one form share one size; the form fills its region rather than
sitting small in the middle of it.

---
name: grid
description: "Coordinate calculation via CSS Grid — read before placing elements"
category: guide
---

# Grid Command

Divide any rectangular area using CSS Grid track-list syntax and compute coordinates.
Works for splitting an entire slide or subdividing the inside of a component.

**Constraints:**
- You MUST read this guide before first use of grid command in a session

```bash
echo '{ ... }' | uv run python3 scripts/pptx_builder.py grid -
```

---

## Command Reference

### Input

```json
{
  "area": { "x": 90, "y": 173, "w": 1750, "h": 777 },
  "columns": "280px 1fr 300px",
  "rows": "120px 1fr",
  "gap": "20",
  "areas": [
    ["sidebar", "header", "header"],
    ["sidebar", "main",   "aside"]
  ]
}
```

- `area`: Rectangle to divide (required)
- `columns` / `rows`: track-list. When rows is omitted, defaults to `"1fr"`
- `gap`: `"20"` = uniform, `"20 40"` = row-gap col-gap. Defaults to `0` when omitted
- `areas`: Equivalent to CSS `grid-template-areas`. Cells with the same name are merged. `.` is an empty cell. When omitted, auto-numbered as `r0c0`
- `items`: Like CSS `place-items`. Declares the size of content to center within a cell. Keys are cell names, values are `{"w": N}` or `{"w": N, "h": N}`. Optional

### track-list

| Syntax | Example | Meaning |
|---|---|---|
| Equal shorthand | `"3"` | Split into 3 equal parts |
| fr ratio | `"2fr 3fr"` | Distribute remainder at 2:3 |
| px fixed | `"280px 1fr"` | 280px fixed + all remaining |
| Mixed | `"280px 1fr 300px"` | Both ends fixed + center flexible |

Calculation: Reserve fixed (px) → subtract gaps → distribute remainder by fr ratio.

### Output

Coordinates for each cell. Output can be fed directly as the next grid's `area` (extra keys are ignored).

```json
{
  "r0c0": {
    "x": 96, "y": 173, "w": 840, "h": 364,
    "x2": 936, "y2": 537,
    "cx": 516, "cy": 355,
    "gx2": 960, "gy2": 561
  }
}
```

- `x, y, w, h`: Usable directly in elements
- `x2, y2`: Bottom-right coordinates
- `cx, cy`: Center coordinates
- `gx2`: Midpoint x between this cell and the right neighbor's gap (not output for the rightmost cell)
- `gy2`: Midpoint y between this cell and the bottom neighbor's gap (not output for the bottommost cell)

gx2/gy2 are for placing divider lines or similar. Not output when gap=0.

When `items` is specified, matched cells get an additional `"item"` key with centered coordinates:
```json
{
  "icon": {
    "x": 100, "y": 200, "w": 400, "h": 80,
    "cx": 300, "cy": 240,
    "item": {"x": 268, "y": 208, "w": 64, "h": 64}
  }
}
```
- `item.x = cell.x + (cell.w - item.w) / 2`
- `item.y = cell.y + (cell.h - item.h) / 2` (only when h is provided)
- When h is omitted, item contains only x and w (horizontal centering only)

---

## 3 Steps of Layout Thinking

### Step 1: Decide the area

The starting point of grid is "which region to divide." This decision determines layout quality.

- **Full slide**: Use analyze-template to get the title bottom edge and calculate the content area
- **Output from a parent grid**: First split the slide coarsely, then use the output coordinates as the next area
- **Inside a component**: Use a card or section's coordinates as the area and subdivide its contents
- **Partial region**: You don't have to use the full area — reserve space above for description text, below for a flow diagram, etc. Narrow the area to fit the content

```bash
# Calculate content area for Title Only layout
uv run python3 scripts/pptx_builder.py analyze-template template.pptx --layout "Title Only"
# → TITLE: {x:64, y:47, w:1803, h:95, y2:142, ...}
# → area_y = title.y2 + margin = 142 + 31 = 173
```

### Step 2: Divide with grid

Read the structure of the content and translate it into CSS Grid syntax.

- Number of elements → number of columns/rows
- **Give every placed element its own cell** — arrows, triangles, and other elements with width/height get their own cells too. Placing elements in the gap requires manual calculation, which defeats the purpose of grid's coordinate automation
- Difference in element importance → fr ratio or px fixed
- Relationship between elements → gap size (connectedness → narrow / independence → wide)
- Narrow gap between elements of the same kind, wider gap between different kinds → gap: "row-gap col-gap"
- Non-rectangular shapes → areas merge patterns
- Elements with no width (divider lines, etc.) can be placed using gx2/gy2

### Step 3: Nest

Feed the output as the next area and subdivide further.
Use when left and right sides have different row counts, or regions have different internal structures.

---

## Thinking Examples

These are samples showing how to use grid. They are not canonical layout patterns.
The combinations of columns/rows/gap/areas are open-ended — invent freely to match the content.

### Funnel

> I want to build a 4-stage funnel: Awareness → Interest → Consideration → Purchase.
> Funnel diagram on the left half, description text for each stage on the right.
>
> **Step 1: Decide the area**
> First split the whole slide left and right. The funnel should be visually dominant, so 55:45.
>
> ```json
> {"area":{"x":96,"y":173,"w":1728,"h":777}, "columns":"55fr 45fr", "gap":"40"}
> ```
> → left: {x:96, y:173, w:928, h:777}
>   right: {x:1064, y:173, w:760, h:777}
>
> **Step 2: Turn left into a funnel**
> Take left's x, y, w, h from Step 1 output.
> Wide at the top, narrow at the bottom. To express this with grid — slice into many columns and vary width by how many cells each row merges.
> Let's use 10 columns. Top row spans all 10, each subsequent row drops 1 column from each side. 10 → 8 → 6 → 4.
> Gap should be tight to convey continuity between stages. 8.
>
> ```json
> {"area":{"x":96,"y":173,"w":928,"h":777},
>  "columns":"10", "rows":"4", "gap":"8",
>  "areas":[
>    ["r1","r1","r1","r1","r1","r1","r1","r1","r1","r1"],
>    [".","r2","r2","r2","r2","r2","r2","r2","r2","."],
>    [".",".","r3","r3","r3","r3","r3","r3",".","."],
>    [".",".",".","r4","r4","r4","r4",".",".","."]
>  ]}
> ```
>
> **Step 3: Split right into 4 rows**
> Take right's x, y, w, h from Step 1 output.
> Description text corresponding to each funnel stage. 4 equal rows.
> Match the gap to the funnel side to align row heights. Same gap: 8.
>
> ```json
> {"area":{"x":1064,"y":173,"w":760,"h":777}, "rows":"4", "gap":"8"}
> ```

### Gantt Chart

> I want to build a Gantt chart with 5 tasks × 4 quarters.
> Task names on the left, timeline bars on the right.
>
> **Step 1: Decide the area**
> A Gantt chart uses the full slide. Check the content area with analyze-template.
> area: {x:96, y:173, w:1728, h:777}
>
> **Step 2: Split the main frame**
> Task names have a known character count. Something like "Requirements" or "Design" — 200px is enough. The rest is all timeline.
> → columns: "200px 1fr"
>
> Rows = 5 tasks. But we also need a header row (Q1, Q2...). 40px fixed is enough for the header.
> → rows: "40px 1fr 1fr 1fr 1fr 1fr"
>
> Row gap — spacing between task rows. Too tight and the bars feel cramped, too wide and scannability suffers. 16.
> Column gap — spacing between the task name column and the timeline. Labels and bars are different information, so a bit wider. 24.
> → gap: "16 24" (row-gap col-gap)
>
> ```json
> {"area":{"x":96,"y":173,"w":1728,"h":777},
>  "columns":"200px 1fr", "rows":"40px 1fr 1fr 1fr 1fr 1fr", "gap":"16 24",
>  "areas":[
>    [".", "header"],
>    ["t1", "bar1"],
>    ["t2", "bar2"],
>    ["t3", "bar3"],
>    ["t4", "bar4"],
>    ["t5", "bar5"]
>  ]}
> ```
>
> The task name column's x, y, w, h can be used directly for textboxes.
>
> **Step 3: Split the timeline into quarters**
> Take bar1's x, y, w, h from Step 2 output.
>
> ```json
> {"area":{"x":320,"y":229,"w":1504,"h":131}, "columns":"4", "gap":"0"}
> ```
> → Each quarter's x and w come out. If a bar spans Q2–Q3,
>   x=q2.x, w=q3.x2 - q2.x gives the start-to-end width.

### Process Flow

> I want to build a 4-step flow: Discover → Analyze → Plan → Execute.
> Each step is a box, with right-pointing triangles between them to show direction.
>
> **Step 1: Decide the area**
> Leave space above the flow for a title or description text.
> Leave room below for subtext too.
> → Don't use the full area — narrow it to y:300, h:400.
>
> **Step 2: Give boxes and triangles their own cells**
> Every placed element gets its own cell. 4 boxes + 3 triangles = 7 columns.
> Triangles just indicate direction, so a small width is enough — 48px. Boxes share the rest equally.
> A little breathing room between boxes and triangles would be nice — gap:12.
>
> ```json
> {"area":{"x":96,"y":300,"w":1728,"h":400},
>  "columns":"1fr 48px 1fr 48px 1fr 48px 1fr", "gap":"12",
>  "areas":[["box1","tri1","box2","tri2","box3","tri3","box4"]]}
> ```
> → box1: {x:96, y:300, w:378, h:400}
>   tri1: {x:486, y:300, w:48, h:400}
>   box2: {x:546, y:300, w:378, h:400}
>   ...
>
> The triangle cell's x, y, w, h become the triangle shape's coordinates directly.
> If the triangle's height matching the box at 400 feels too tall, shrink it vertically around cy.

### Cycle Diagram

> I want to build a PDCA cycle. 4 elements circulating clockwise.
>
> **Step 1: Decide the area**
> Circular structures look best in a near-square region.
> Match the content area height of 777, make the width 777 too, and center it.
> x = 96 + (1728 - 777) / 2 = 571
> → area: {x:571, y:173, w:777, h:777}
>
> **Step 2: Split into 3×3 — arrows get cells too**
> Every placed element gets its own cell. 4 boxes + 4 arrows = 3×3 grid.
> Center is empty. Arrow cells just need to fit a line — 60px.
> Tight coupling matters for a cycle, so gap:0. Boxes and arrows sit flush.
>
> ```json
> {"area":{"x":571,"y":173,"w":777,"h":777},
>  "columns":"1fr 60px 1fr", "rows":"1fr 60px 1fr", "gap":"0",
>  "areas":[
>    ["plan",  "atop",    "do"],
>    ["aleft", ".",       "aright"],
>    ["act",   "abottom", "check"]
>  ]}
> ```
> → plan: {x:571, y:173, w:358, h:358}
>   atop: {x:929, y:173, w:60, h:358}
>   do: {x:989, y:173, w:359, h:358}
>   aleft: {x:571, y:531, w:358, h:60}
>   aright: {x:989, y:531, w:359, h:60}
>   act: {x:571, y:591, w:358, h:359}
>   abottom: {x:929, y:591, w:60, h:359}
>   check: {x:989, y:591, w:359, h:359}
>
> Clockwise placement: Plan=top-left, Do=top-right, Check=bottom-right, Act=bottom-left
>
> **Place arrows using each cell's cx, cy**
> Arrow cells are elongated. Draw a line along the cell's center axis.
>   Plan→Do (right):    Horizontal line inside atop cell. y=atop.cy, x=atop.x, w=atop.w
>   Do→Check (down):    Vertical line inside aright cell. x=aright.cx, y=aright.y, h=aright.h
>   Check→Act (left):   Horizontal line inside abottom cell. y=abottom.cy, x=abottom.x, w=abottom.w
>   Act→Plan (up):      Vertical line inside aleft cell. x=aleft.cx, y=aleft.y, h=aleft.h
>
> Cell coordinates become line coordinates directly. Direction is indicated by end_arrow.

### Icon Cards (items)

> I want 3 feature cards side by side. Each card has a centered icon, a title, and a description.
>
> **Step 1: Decide the area**
> Full content area. 3 cards with some spacing between them.
>
> ```json
> {"area":{"x":96,"y":173,"w":1728,"h":777}, "columns":"3", "gap":"24"}
> ```
> → r0c0: {x:96, y:173, w:560, h:777}
>   r0c1: {x:680, y:173, w:560, h:777}
>   r0c2: {x:1264, y:173, w:560, h:777}
>
> **Step 2: Split each card's interior — use items for the icon**
> Take r0c0's x, y, w, h from Step 1 output.
> Icon (100px row) + title (50px row) + description (rest). Gap 16 for tight grouping.
> The icon is 64×64 but the cell is 560×100. Without items, the icon would sit at the cell's top-left.
> Declare items to get centered coordinates.
>
> ```json
> {"area":{"x":96,"y":173,"w":560,"h":777},
>  "rows":"100px 50px 1fr", "gap":"16",
>  "areas":[["icon"],["title"],["desc"]],
>  "items":{"icon":{"w":64,"h":64}}}
> ```
> → icon: {x:96, y:173, w:560, h:100, item:{x:344, y:191, w:64, h:64}}
>   title: {x:96, y:289, w:560, h:50}
>   desc: {x:96, y:355, w:560, h:595}
>
> The image uses item's x, y, w, h: `{x:344, y:191, width:64, height:64}`.
> The title textbox uses the title cell's full width with align:center — its visual center aligns with the icon.
> Run the same grid for r0c1 and r0c2, changing only the area.

### Comparison Layout

> I want to compare Current State and Proposal side by side.
> Each side has a title, 3 points, and a summary.
>
> **Step 1: Decide the area**
> It's a comparison, so use the full slide. area: {x:96, y:173, w:1728, h:777}
>
> **Step 2: Split left and right**
> Comparison means equal widths. We want a divider line between them, so make the gap generous. 48.
>
> ```json
> {"area":{"x":96,"y":173,"w":1728,"h":777},
>  "columns":"2", "gap":"48"}
> ```
>
> Place the divider line at left's gx2. gx2 = midpoint x of the gap.
> line's x = r0c0.gx2, y = area.y, height = area.h draws a vertical line.
>
> **Step 3: Split each side's contents**
> Take left's x, y, w, h from Step 2 output.
> Title (40px fixed) + 3 point rows (equal) + summary (60px fixed).
>
> ```json
> {"area":{"x":96,"y":173,"w":840,"h":777}, "rows":"40px 1fr 1fr 1fr 60px", "gap":"12"}
> ```
>
> Right uses the same structure. Just change the area's x, y, w, h and run the same grid.
> Using the same rows/gap for both sides keeps row heights aligned — alignment matters in comparison layouts.

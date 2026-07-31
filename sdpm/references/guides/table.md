---
description: "Table styling guide — read when slide contains a data table"
---

Tables for structured data: comparisons, feature matrices, status dashboards, pricing plans.

## Structure

```json
{
  "type": "table",
  "x": 58, "y": 270, "width": 1804, "height": 250,
  "colWidths": [400, 500, 300],
  "rowHeights": [50, 50, 50],
  "style": { ... },
  "columnStyles": { ... },
  "cellOverrides": { ... },
  "headers": ["Col A", "Col B", "Col C"],
  "rows": [["a1", "b1", "c1"], ["a2", "b2", "c2"]],
  "shadow": "md"
}
```

- `height`: omit → auto-calculated from row count
- `colWidths`: omit → equal split. Array of px values
- `rowHeights`: omit → default. Only needed for special cases (e.g. tall card-like header)
- `shadow`: `"sm"` / `"md"` / `"lg"` or object (same as other elements)

## Design points

- `padding` controls whitespace inside cells. Use `style.body.padding` for baseline, `cellOverrides` for edge rows that need more breathing room (e.g. first data row top, last data row bottom)
- Fewer rows → more padding. A 4-row table with tight rows wastes the slide. Scale padding up so the table fills the available space
- Horizontal-only borders feel cleaner than full grid — use per-side `border`
- `columnStyles` colors entire columns — effective for plan comparison or emphasis
- `cellOverrides` with `background: "none"` + all borders `fill: "none"` makes a cell invisible
- Accent color on one column draws the eye to the recommended option
- `gridSpan` on some rows + no borders hides column structure — the table looks like 3 columns but is actually 6. Merged rows show one value, non-merged rows reveal sub-columns
- Styled text `{{bold,24pt,#FF0000:$27}}/mo` mixes sizes and colors within a cell — numbers large and colored, units small and neutral

## Cascade

```
style (header/body/altRow/altCol) → columnStyles → cellOverrides → cell direct
```

When `style` is specified, all borders default to none (CSS convention). Add `border` explicitly to get lines.
When `style` is omitted, theme colors auto-generate header/body/altRow.

### style

```json
"style": {
  "header":  { "background": "#232F3E", "color": "#FFF", "font-weight": "bold" },
  "body":    { "background": "#FFF", "color": "#232F3E", "padding": {"top": 25, "bottom": 25} },
  "altRow":  { "background": "#F2F3F3" },
  "altCol":  { "background": "#F8F8F8" },
  "border":  { "color": "#D5DBDB", "width": 0.5 }
}
```

- `header`: header row
- `body`: all data rows. `padding` here sets the baseline for all cells
- `altRow`: even data rows (overrides `body`)
- `altCol`: even columns (overrides `body`/`altRow`)
- `border`: all cells. Uniform or per-side:
  - Uniform: `{ "color": "#DDD", "width": 0.5 }` → all 4 sides
  - Per-side: `{ "top": { "color": "#DDD", "width": 0.5 }, "bottom": { ... } }` → only specified sides, rest stay none
- `header.border`: overrides `border` for header row only (same uniform/per-side format)

### columnStyles

Column-index keyed (0-based string):

```json
"columnStyles": {
  "2": { "text-align": "right", "color": "#FF9900" }
}
```

### cellOverrides

`"row,col"` keyed (0-based, row 0 = header row):

```json
"cellOverrides": {
  "3,2": { "font-weight": "bold" },
  "0,0": { "background": "none", "borders": { "left": {"fill": "none"}, "top": {"fill": "none"} } }
}
```

## CSS properties

| Property | Values | Notes |
|---|---|---|
| `background` | `"#232F3E"` / `"none"` / `"rgba(255,255,255,0.2)"` | rgba for transparency |
| `color` | `"#FFFFFF"` | text color |
| `font-weight` | `"bold"` | |
| `font-style` | `"italic"` | |
| `text-decoration` | `"underline"` | |
| `font-size` | `14` | pt |
| `text-align` | `"left"` / `"center"` / `"right"` | |
| `vertical-align` | `"top"` / `"middle"` / `"bottom"` | default middle |
| `padding` | `{"top": 25, "bottom": 25, "left": 10, "right": 10}` | cell inset in px |
| `gradient` | `{"angle": 0, "stops": [...]}` | per-cell gradient fill |

## Cell object

Cells in `rows` can be strings or objects:

```json
{
  "text": "{{bold,24pt,#FF0000:$27}}/mo",
  "background": "#232F3E",
  "gradient": {"angle": 90, "stops": [{"color": "#E8A0BF", "position": 0}, {"color": "#7EC8E3", "position": 1}]},
  "color": "#FFFFFF",
  "font-size": 14,
  "font-weight": "bold",
  "text-align": "center",
  "vertical-align": "middle",
  "gridSpan": 2,
  "rowSpan": 2,
  "merged": true,
  "padding": {"left": 10, "right": 10, "top": 5, "bottom": 5},
  "borders": {
    "left":   {"color": "#FFF", "width": 1.0},
    "right":  {"fill": "none"},
    "top":    {"color": "#FFF", "width": 1.0},
    "bottom": {"color": "#FFF", "width": 1.0}
  }
}
```

- `gradient`: per-cell gradient fill. `position` is 0-1 scale. Participates in cascade
- `merged: true`: consumed by gridSpan/rowSpan (place with empty text)
- `borders.*.fill`: `"none"` to hide a border side
- `padding`: per-cell margin override
- Styled text: `{{bold,24pt,#RRGGBB:text}}` for inline size/color/weight mixing

---

## Samples

### Glass table

Translucent cells on a colored background. The table floats on the slide.

```json
{
  "type": "table",
  "style": {
    "header": { "background": "#55608F", "color": "#FFFFFF", "font-weight": "bold" },
    "body":   { "background": "rgba(255,255,255,0.2)", "color": "#FFFFFF" }
  },
  "shadow": "md"
}
```

- `rgba()` transparency lets the slide background bleed through
- No borders — the color difference between header and body is enough separation
- `shadow` lifts the table off the background

### Gradient pricing table

Hidden column structure via `gridSpan`, gradient headers, per-column color theming.
Actually 6 columns — merged rows look like 3, non-merged rows reveal label + value sub-columns.

```json
{
  "type": "table",
  "colWidths": [180, 393, 180, 393, 180, 393],
  "style": {
    "header": { "color": "#FFFFFF", "font-weight": "bold", "font-size": 28, "text-align": "center", "padding": {"top": 30, "bottom": 30} },
    "body":   { "background": "#FFFFFF", "color": "#555555", "text-align": "center", "vertical-align": "middle", "padding": {"top": 25, "bottom": 25, "left": 10, "right": 10} }
  },
  "columnStyles": {
    "0": { "background": "rgba(232,160,191,0.1)" },
    "1": { "background": "rgba(232,160,191,0.1)" },
    "2": { "background": "rgba(126,200,227,0.1)" },
    "3": { "background": "rgba(126,200,227,0.1)" },
    "4": { "background": "rgba(27,58,107,0.08)" },
    "5": { "background": "rgba(27,58,107,0.08)" }
  },
  "cellOverrides": {
    "0,0": { "gradient": {"angle": 0, "stops": [{"color": "#E8A0BF", "position": 0}, {"color": "#C4A8D8", "position": 1}]}, "color": "#FFFFFF" },
    "0,2": { "gradient": {"angle": 0, "stops": [{"color": "#7EC8E3", "position": 0}, {"color": "#4A7FB5", "position": 1}]}, "color": "#FFFFFF" },
    "0,4": { "gradient": {"angle": 0, "stops": [{"color": "#3A5FA0", "position": 0}, {"color": "#1B3A6B", "position": 1}]}, "color": "#FFFFFF" },
    "1,0": { "font-size": 36, "padding": {"top": 100, "bottom": 70} },
    "1,2": { "font-size": 36, "padding": {"top": 100, "bottom": 70} },
    "1,4": { "font-size": 36, "padding": {"top": 100, "bottom": 70} },
    "2,0": { "font-size": 13, "text-align": "right" },
    "2,2": { "font-size": 13, "text-align": "right" },
    "2,4": { "font-size": 13, "text-align": "right" },
    "3,0": { "font-size": 13, "text-align": "right", "padding": {"bottom": 100}, "borders": {"bottom": {"color": "#E8A0BF", "width": 3}} },
    "3,1": { "padding": {"bottom": 100}, "borders": {"bottom": {"color": "#E8A0BF", "width": 3}} },
    "3,2": { "font-size": 13, "text-align": "right", "padding": {"bottom": 100}, "borders": {"bottom": {"color": "#4A7FB5", "width": 3}} },
    "3,3": { "padding": {"bottom": 100}, "borders": {"bottom": {"color": "#4A7FB5", "width": 3}} },
    "3,4": { "font-size": 13, "text-align": "right", "padding": {"bottom": 100}, "borders": {"bottom": {"color": "#1B3A6B", "width": 3}} },
    "3,5": { "padding": {"bottom": 100}, "borders": {"bottom": {"color": "#1B3A6B", "width": 3}} }
  },
  "headers": [
    {"text": "Basic", "gridSpan": 2}, {"merged": true},
    {"text": "Pro", "gridSpan": 2}, {"merged": true},
    {"text": "Business", "gridSpan": 2}, {"merged": true}
  ],
  "rows": [
    [{"text": "{{bold,48pt,#E8A0BF:1}} Form", "gridSpan": 2}, {"merged": true}, ...],
    ["Monthly", "{{bold,24pt,#C4789A:$27}}/mo", "Monthly", "{{bold,24pt,#4A7FB5:$44}}/mo", ...],
    ["Annual",  "{{bold,24pt,#C4789A:$198}}/yr", "Annual",  "{{bold,24pt,#4A7FB5:$396}}/yr", ...]
  ]
}
```

- `gridSpan: 2` on header and "N Forms" rows hides the 6-column structure — looks like 3 columns
- Non-merged rows reveal label + value sub-columns with aligned text
- Label columns right-aligned, value columns centered — the pair reads as one unit
- `columnStyles` pairs (0+1, 2+3, 4+5) give each plan a tinted background
- `gradient` on header cells via `cellOverrides` — each plan has its own gradient
- Styled text `{{bold,48pt,#E8A0BF:1}} Form` — number is large/colored/bold, unit is small/neutral
- Edge row padding (`top: 100` on first data row, `bottom: 100` on last) creates breathing room at table boundaries
- `borders.bottom` on last row adds colored accent line per plan

### Pricing comparison table

Column-colored plan comparison. Feature labels on the left, plan columns on the right.

```json
{
  "type": "table",
  "rowHeights": [180, 48, 48, 48, 48, 48, 48, 48],
  "style": {
    "header": { "background": "none", "color": "#666666", "font-weight": "bold", "font-size": 20, "text-align": "center" },
    "body":   { "background": "none", "color": "#666666", "text-align": "center" },
    "border": { "color": "#DDDDDD", "width": 0.5 }
  },
  "columnStyles": {
    "1": { "background": "rgba(50,205,50,0.08)", "color": "#2E8B57" },
    "2": { "background": "#30305B", "color": "#85BAFC" }
  },
  "cellOverrides": {
    "0,0": {
      "background": "none",
      "borders": { "left": {"fill": "none"}, "right": {"fill": "none"}, "top": {"fill": "none"}, "bottom": {"fill": "none"} }
    },
    "0,1": { "font-size": 28 },
    "0,2": { "font-size": 28, "font-weight": "bold" }
  }
}
```

- `columnStyles` paints each plan column — the color itself communicates identity
- Top-left cell made invisible with `background: "none"` + all borders `fill: "none"`
- Tall header row (`rowHeights[0]: 180`) gives plan names card-like presence
- `font-size: 28` on header cells reinforces the card weight
- Feature column stays neutral (no columnStyles for column 0) — it's the axis, not the content

### Grid pricing table

Full grid lines, accent column for the recommended plan, generous padding.

```json
{
  "type": "table",
  "style": {
    "header": { "background": "#50535D", "color": "#FFFFFF", "font-weight": "bold", "text-align": "center", "padding": {"top": 40, "bottom": 40, "left": 30, "right": 30} },
    "body":   { "background": "#FFFFFF", "color": "#333333", "text-align": "center", "padding": {"top": 45, "bottom": 45, "left": 8, "right": 8} },
    "border": { "color": "#EEEEEE", "width": 1.5 }
  },
  "columnStyles": {
    "0": { "text-align": "left", "font-size": 14 }
  },
  "cellOverrides": {
    "0,1": { "background": "#E81010", "color": "#FFFFFF", "font-weight": "bold" },
    "1,1": { "color": "#E81010", "font-weight": "bold", "font-size": 20 },
    "1,2": { "font-weight": "bold", "font-size": 20 },
    "1,3": { "font-weight": "bold", "font-size": 20 },
    "1,4": { "font-weight": "bold", "font-size": 20 }
  }
}
```

- One header cell overridden to red (`#E81010`) — the recommended plan pops against the grey header
- Price row uses larger `font-size` + `bold` — the most important data gets the most visual weight
- Recommended plan's price in red text echoes the header accent
- `padding` on body gives each row breathing room — no `rowHeights` needed
- Left column `text-align: left` separates labels from centered data
- Full grid `border` with light color (`#EEE`) — structure without heaviness

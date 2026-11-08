---
name: slide-json-elements
description: "Slide JSON elements — fields of textbox, shape, line, image, include and group, text sizing, labeled shapes, and slide override (inheritance)"
category: guide
---

# Slide JSON Elements

The common element types of `slides/<slug>.json` `elements`, and how a slide inherits another
slide's elements (the slide format core is `slide-json-spec`). Image treatments, QR codes, code blocks, charts, freeform and video are in
`slide-json-media`; effects in `slide-json-effects`.

## Slide Override (inheritance)

```json
{"id": "base", "layout": "Title Only with Left Line", "placeholders": {"0": "Agenda"}, "elements": [...]}
{"override": "base", "layout": "Title Only with Left Line", "placeholders": {"0": "Agenda - Section 1"}, "elements": [...]}
```

Note: `notes` omitted for brevity. In actual slides, write them before `elements`.

- Derived slides inherit the base's `elements`; derived `elements` are drawn on top
- `placeholders`/`notes`/`layout` are NOT inherited
- Chain inheritance is supported (A → B → C)

**Use cases:**
- **Agenda highlight**: Base has all items; derived overlays the current section with a highlight-colored shape
- **Progressive disclosure**: Build an architecture diagram step by step; each derived slide adds one element
- **Step highlight**: Base has all steps in muted color; derived emphasizes only the current step
- **Repeating frame**: Shared frame for customer case studies etc. where only the content changes
- Actively use override for progressive disclosure, highlight, and agenda patterns

## include
Expands an external JSON file's elements array. Draw order is controlled by position within elements.
```json
{"type": "include", "src": "arch/payment-elements.json"}
```
- `src`: path to a JSON file containing an elements array (relative to the slide JSON)
- Expanded elements are inserted at the include's position (drawn above preceding elements)
- Can use `arch_diagram(...)` output directly
- Multiple includes can be placed

## textbox
```json
{
  "type": "textbox",
  "x": 58, "y": 216, "width": 1804, "height": 120,
  "align": "left|center|right",
  "fontSize": 18,
  "text": "Text",
  "fill": "#FF9900",
  "opacity": 0.5,
  "line": "#232F3E",
  "lineWidth": 2,
  "rotation": 45,
  "autoWidth": false,
  "fontFamily": "Lucida Console",
  "marginLeft": 14, "marginTop": 7, "marginRight": 14, "marginBottom": 7,
  "verticalAlign": "top|middle|bottom",
  "textGradient": {"angle": 0, "stops": [{"position": 0, "color": "#..."}, {"position": 1, "color": "#..."}]}
}
```

- `height`: **Required**. Text that overflows the box is detected and warned — adjust layout or content to fit
  - Height guide: 1 line = `fontSize × 3.5`, multiple lines = `lines × fontSize × 2.7` (varies with afterSpace etc.)
- `fontFamily`: font name (omit to use theme default)
- `marginTop`: textboxes keep PowerPoint's default top inset (7), so the visual top of the text sits below `y`. Set `marginTop: 0` when the text's top edge must align exactly with `y` (or with a neighbouring shape)
- Code blocks with syntax highlighting: `code_to_slide` (`slide-json-media`)

**Height per font size** (measured values, including line spacing):

| fontSize | 1 line | 2 lines | 3 lines | Use case |
|----------|--------|---------|---------|----------|
| 12pt | 35px | 70px | 105px | Annotation |
| 16pt | 45px | 90px | 135px | Supplementary |
| 20pt | 50px | 100px | 150px | Body |
| 24pt | 60px | 120px | 180px | Main |
| 28pt | 70px | 140px | 210px | Heading |
| 32pt | 80px | 160px | 240px | Large heading |

**Width guide**: fullwidth px = `fontSize ÷ ptPerPx × char count`, halfwidth = half that.
  `ptPerPx` is in `deck.json` `slideSize.ptPerPx` (16:9 = 0.5 → ×2, 4:3 = 0.375 → ×2.67)
- `autoWidth`: true → word_wrap disabled (width fits text)
- `line`: border color. Omit or `"none"` for no border
- `lineWidth`: border thickness (pt, default 1)
- `margin*`: px (same 1920-wide canvas basis as other coordinates)
- `verticalAlign`: `top`, `middle`, `bottom` (default: top for textbox)
- **Line breaks**: `\n` creates a line break (internally split into paragraphs)

**Bullets / numbered lists**:
```json
{"type": "textbox", "paragraphs": [
  {"text": "Item 1", "list": {"type": "disc"}},
  {"text": "Step 1", "list": {"type": "arabicPeriod"}}
]}
```

- `spaceAfter`: space after paragraph (hundredths of a point. 800 = 8pt). Works in textbox `paragraphs` and shape `items`
```json
{"text": "Item 1", "list": {"type": "disc"}, "spaceAfter": 800}
```
- `list.level`: paragraph level (0=top, 1=sub, 2=sub-sub). For nested lists
```json
{"text": "Sub-item", "list": {"type": "disc", "level": 1}}
```
- `lineSpacingPct`: line spacing (percent × 1000. 120000 = 120%)
```json
{"text": "1.2x line spacing", "lineSpacingPct": 120000}
```

## table

`"type": "table"` — CSS-style cascade styling with `style`, `columnStyles`, `cellOverrides`.
- Call `read_guides(["table"])` for structure, cascade, CSS properties, and styled samples.

## image
```json
{
  "type": "image",
  "src": "assets:aws/Arch_AWS-Lambda_48",
  "x": 192, "y": 324, "width": 154, "height": 154,
  "rotation": 0,
  "label": "Lambda",
  "labelPosition": "bottom|right|none",
  "labelSize": 11,
  "link": "https://..."
}
```

- `src`: `assets:SOURCE/NAME`, `icons:NAME` (backward compatible), `qr:URL`, file path, relative path
- `height`: omit to maintain aspect ratio
- `fit`: `"contain"` (default) | `"cover"` | `"stretch"` — controls sizing when both width and height are specified
  - `contain`: maintain aspect ratio, fit within the box (may leave gaps)
  - `cover`: maintain aspect ratio, fill the box (excess is cropped via PowerPoint trim)
  - `stretch`: ignore aspect ratio, fill the box exactly
- `labelSize`: default 11
- `iconColor`: (optional) change SVG icon color. Single-color SVGs only (multi-color icons are ignored)
- Masks, crops, colour treatments and QR codes: `slide-json-media`; shadow, glow and soft edge: `slide-json-effects`

## shape
```json
{
  "type": "shape",
  "shape": "rectangle|rounded_rectangle|oval|circle|arrow_right|arrow_left|arrow_up|arrow_down|arrow_circular|arrow_left_right|arrow_up_down|arrow_curved_right|arrow_curved_left|arrow_curved_up|arrow_curved_down|arrow_circular_left|arrow_circular_left_right|triangle|diamond|pentagon|hexagon|cross|trapezoid|parallelogram|chevron|donut|arc|block_arc|chord|pie|pie_wedge|cloud|lightning_bolt|star_5_point|no_symbol|callout_rectangle|callout_rounded_rectangle|callout_oval|flowchart_process|flowchart_decision|flowchart_terminator|left_brace|right_brace|left_bracket|right_bracket",
  "x": 192, "y": 216, "width": 576, "height": 162,
  "fill": "#FF9900",
  "opacity": 0.0-1.0,
  "gradient": {"angle": 90, "stops": [{"position": 0, "color": "#...", "opacity": 1.0}, {"position": 1, "color": "#..."}]},
  "line": "#232F3E",
  "lineWidth": 2,
  "lineGradient": {"angle": 90, "stops": [...]},
  "lineOpacity": 0.5,
  "dashStyle": "solid|dash|dot|dash_dot|long_dash|square_dot",
  "adjustments": [0.06],
  "rotation": 0,
  "flipH": false,
  "flipV": false,
  "text": "Label",
  "paragraphs": [{"text": "Title", "fontSize": 24, "align": "center"}, {"text": "Body", "list": {"type": "disc"}}],
  "fontSize": 14,
  "fontColor": "#FFFFFF",
  "align": "left|center|right",
  "verticalAlign": "top|middle|bottom",
  "textDirection": "vert270",
  "items": ["Bullet 1", "Bullet 2"],
  "arrowStart": "arrow|triangle|stealth|oval|diamond|none",
  "arrowEnd": "arrow|triangle|stealth|oval|diamond|none",
  "link": "https://..."
}
```

- `opacity`: fill opacity (default 1.0)
- `line`: border color. Omit or `"none"` for no border
- `lineWidth`: border thickness (pt, default 1)
- `flipH`/`flipV`: horizontal/vertical flip (default false)
- `patternFill`: pattern fill `{"pattern": "dkDnDiag|ltHorz|ltVert|dkHorz|dkVert|smGrid|lgGrid|dnDiag|upDiag|...", "fgColor": "#...", "bgColor": "#..."}`
- `adjustments`: adjustment handle values (corner radius for rounded_rectangle, etc.)
- `verticalAlign`: `top`, `middle`, `bottom` (default: middle for shape)
- `rotation`: rotation angle (degrees, clockwise). Base orientation at 0° differs per shape: `arrow_right` points right, `triangle` points up — a right-pointing triangle is `"shape": "triangle", "rotation": 90`
- `gradient.angle`: gradient angle, clockwise from right. 0°=left→right, 90°=top→bottom, 180°=right→left, 270°=bottom→top. Same convention as block_arc/pie shapes
- `sendToBack`: render this element BEHIND template placeholders (title/subtitle). Elements normally stack in array order, all in front of placeholders — use this on full-bleed decorative shapes/images that must not cover the title. Works on any element type
- `circle`: alias for oval. Squared using min(width, height)
- `arrow_circular` / `arrow_circular_left` / `arrow_circular_left_right`: arc arrows for cycle diagrams
- `arrow_curved_*`: thick curved arrows
- `chevron`: for process flows
- `donut`: adjustments=[hole size (default: 0.25)]
- `block_arc`: adjustments=[start angle, sweep, thickness (default: 0.25), clockwise (default: true)]. Sweep is degrees or "N%" string (e.g. "73%"). 0°=right(3 o'clock), 90°=bottom(6), 180°=left(9), 270°=top(12). Progress circle example: donut (background) + block_arc [270, "73%", 0.15]. **thickness** = ring width as a ratio of the diameter (bbox width). Effective range 0–0.5 (values >0.5 are clamped). Given `r = width/2`: thickness = `ring_width / (2r)`, ring_width = `2r × thickness`, inner_r = `r × (1 − 2×thickness)`, ring_center_r = `r × (1 − thickness)`. Use ring_center_r when placing elements on the ring (e.g. direction markers in a cycle diagram).
- `arc`: adjustments=[start angle, sweep, clockwise (default: true)]. Line arc. Sweep is degrees or "N%"
- `pie`: adjustments=[start angle, end angle]. Sector shape
- `chord`: adjustments=[start angle, end angle]. Chord shape (arc closed by a straight line)
- `pie_wedge`: fixed 90° sector
- `callout_*`: callout shapes
- `flowchart_*`: flowchart shapes

### Labeled shapes — use `text`, never overlay a textbox

When a shape needs a label, put the label in the shape's own `text` (or
`paragraphs` / `items`) property. **Do NOT** add a separate `textbox` element
on top of the shape with the same bounding box.

**Wrong** — two elements stacked at the same coordinates:
```json
{"type": "shape", "shape": "rounded_rectangle",
 "x": 100, "y": 200, "width": 200, "height": 100, "fill": "#0066CC"}
{"type": "textbox",
 "x": 100, "y": 200, "width": 200, "height": 100,
 "text": "Service A", "fontSize": 20,
 "align": "center", "verticalAlign": "middle"}
```

**Right** — single shape with `text`:
```json
{"type": "shape", "shape": "rounded_rectangle",
 "x": 100, "y": 200, "width": 200, "height": 100, "fill": "#0066CC",
 "text": "Service A", "fontSize": 20,
 "align": "center", "verticalAlign": "middle"}
```

Why: the two elements wrap independently — if widths drift the textbox
collides with the shape edge; both must be moved together for any layout
change; and the shape's `measure` overflow check does not see the textbox.
Build emits an "Overlay textbox detected" warning when this anti-pattern
is found, but you should not produce it in the first place.

## line
```json
{
  "type": "line",
  "x1": 192, "y1": 324, "x2": 576, "y2": 324,
  "color": "#8FA7C4",
  "lineWidth": 1.25,
  "dashStyle": "solid|dash|dot|dash_dot|long_dash|square_dot",
  "connectorType": "straight|elbow|curved",
  "elbowStart": "horizontal|vertical",
  "preset": "bentConnector3",
  "adjustments": [0.5],
  "arrowStart": "arrow|triangle|stealth|oval|diamond|none",
  "arrowEnd": "arrow|triangle|stealth|oval|diamond|none",
  "lineGradient": {"angle": 0, "stops": [...]}
}
```

- `preset`: connector preset name (e.g. `bentConnector3`, `bentConnector4`, `bentConnector5`)
- `adjustments`: elbow/curved connector waypoints (0–1 ratio array). Auto-selects bentConnector3/4/5 by count
- `elbowStart`: first segment direction for elbow connectors. `"horizontal"` (default, H-V-H) or `"vertical"` (V-H-V)

**Polyline** (3+ point path):
```json
{
  "type": "line",
  "points": [[100, 200], [300, 200], [300, 400], [500, 400]],
  "color": "#FF9900",
  "lineWidth": 2,
  "arrowEnd": "triangle"
}
```

- `x1`/`y1`: start point, `x2`/`y2`: end point. Direction is implicit — (x1,y1) to (x2,y2)
- Lines carry no text: `text` on a line is ignored. Label a line with a separate `textbox` placed beside or over it
- `elbowStart`: first segment direction for elbow connectors. `"horizontal"` (default, H-V-H) or `"vertical"` (V-H-V)

## group
```json
{
  "type": "group",
  "elements": [{"type": "shape", ...}, {"type": "textbox", ...}]
}
```
- Child elements are expanded and added individually (not grouped)

## Placeholder (for user editing)

```json
{
  "type": "shape", "shape": "rectangle",
  "fill": "#F0F0F0", "line": "#CCCCCC",
  "text": "{{#888888:<Insert screenshot here>}}"
}
```

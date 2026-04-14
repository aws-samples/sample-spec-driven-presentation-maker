# JSON Schema Reference

## Top-level

```json
{
  "fonts": {
    "fullwidth": "メイリオ",
    "halfwidth": "Calibri"
  },
  "defaultTextColor": "#000000",
  "slides": [...]
}
```

- `"fonts"`: **Required**. Font configuration for text rendering.
  - `"fullwidth"`: Font for fullwidth characters (e.g. Japanese, Chinese)
  - `"halfwidth"`: Font for halfwidth characters (e.g. English, numbers)
  - Run `analyze-template` to detect fonts from your template.
- `"defaultTextColor"`: **Required**. Default color for text and icons (e.g. `"#FFFFFF"` for dark backgrounds, `"#000000"` for light). Overridden per element by `fontColor` / `iconColor`.
- Line color, table color, and chart color are auto-resolved from the template's theme colors

## Comments

JSON has no comment syntax, so use the `_comment` key. Can be used inside elements too (ignored).

```json
{"_comment": "--- Section: Problem ---"}
```

## Slide Background

```json
{
  "layout": "blank",
  "background": "#232F3E",
  "defaultTextColor": "#FFFFFF",
  "elements": [...]
}
```

- `"background"`: Solid fill color for the slide background. Overrides the template's default background for this slide only.
- `"defaultTextColor"`: Override the top-level `defaultTextColor` for this slide. Affects text, icons, lines, and table auto-colors.
- Omit either to use the top-level / template default.
- When `background` is set, table auto-colors and icon theme (dark/light) also adapt automatically.
- Per-element `fontColor` / `iconColor` still takes highest priority.

## notes and elements

A slide has two layers:
- `notes` = **Content** (guide for what the presenter says; also serves as a spec for what goes on the slide)
- `elements` = **Implementation** (builds coordinates and styles based on notes)

Write `notes` before `elements`. You cannot build the implementation without knowing what the slide says.

### How to write notes

Notes are speaker notes (presentation script). Write as words spoken to the audience:
- Use conversational language that can actually be spoken aloud
- Include questions and calls to the audience
- Write as a script addressed to the audience, not as slide composition instructions
- When slide content has references (official docs, blog posts, papers, etc.), list URLs at the end of notes after a `---` separator

```
❌ Meta-instruction: "Introduce the 6 main components of AgentCore.
   Runtime, Gateway, Memory, Identity, Observability, Built-in Tools.
   Emphasize that it's framework-agnostic and model-agnostic,
   working with existing tools and frameworks as-is."

✅ Presentation script: "Let's look inside AgentCore. There are six
   major components. I'll name them one by one, but don't worry about
   memorizing all of them. The key point is that none of these are
   tied to a specific framework or model. You can plug them right
   into the tools you're already using."

✅ With references: "...You can plug them right into the tools you're already using.
   ---
   https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html"
```

## Slide Layouts

Use the template's actual layout names. Check with `analyze-template`.

Specify `"0": ""` in placeholders to delete the title placeholder.

## Placeholders

All placeholder content is specified via the `placeholders` dict, keyed by placeholder index (as string).
Run `analyze-template --layout <name>` to see available indices and their descriptions for each layout.

```json
"placeholders": {
  "0": "Text",
  "1": "Subtitle text",
  "11": {
    "text": "{{bold:AWS}} Service Overview",
    "fontSize": 36,
    "fontColor": "#FF9900",
    "bold": true,
    "italic": true,
    "align": "center"
  }
}
```

- String form: simple text
- Object form: only `text` is required, everything else is optional
- Styled Text (`{{bold:...}}`, `{{#RRGGBB:...}}`, etc.) works in both forms
- `"0": ""` / `"0": {"text": ""}` deletes the placeholder

**Use cases**:
- Long title → reduce `"fontSize"` to fit
- Emphasize a keyword → `"text": "{{#FF9900:AWS}} Service Overview"` for partial color
- Full canvas → `"0": ""` to remove the title
- Title overlaps subtitle → `"offsetY": -10` to shift up, `"offsetHeight": 30` to expand height

**Position offsets** (relative to layout default, in px):
- `offsetX`: X offset (positive=right, negative=left)
- `offsetY`: Y offset (positive=down, negative=up)
- `offsetWidth`: width offset (positive=wider, negative=narrower)
- `offsetHeight`: height offset (positive=taller, negative=shorter)

```json
"placeholders": {
  "0": {
    "text": "A Long Title Text",
    "fontSize": 28,
    "offsetY": -10,
    "offsetHeight": 30
  }
}
```

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

## Positioning

- Coordinates and sizes are in pixels (px)
- Sample template: 1920×1080 basis, recommended drawing area x=58–1862, y=173–950
- Custom templates: use slide size and placeholder positions from `analyze-template`
- Bottom-most element: aim for `y + height ≥ 80% of slide height`

### Coordinate quick reference

| % | x (horizontal) | y (vertical) |
|---|----------------|--------------|
| 5 | 96 | 54 |
| 10 | 192 | 108 |
| 25 | 480 | 270 |
| 50 | 960 | 540 |
| 75 | 1440 | 810 |
| 100 | 1920 | 1080 |

**Common sizes**: card width 400–600px, 2-column 900px each, 3-column 600px each, 4-column 450px each. Icon size is relative to context — see design-rules.

## Elements

### include
Expands an external JSON file's elements array. Draw order is controlled by position within elements.
```json
{"type": "include", "src": "arch/payment-elements.json"}
```
- `src`: path to a JSON file containing an elements array (relative to the slide JSON)
- Expanded elements are inserted at the include's position (drawn above preceding elements)
- Can use `layout` command output directly
- Multiple includes can be placed

### textbox
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

**Code blocks (syntax highlighting)**:

Generate elements with the `code-block` command and include them:

```bash
# From file
uv run python3 scripts/pptx_builder.py code-block main.py -l python --x 480 --y 100 --width 500 --height 200 -o code.json

# From stdin
echo 'const client = new S3Client();' | uv run python3 scripts/pptx_builder.py code-block - -l typescript --x 480 --y 100 --width 500 --height 200 -o code.json
```

Include in presentation.json:
```json
{
  "elements": [
    {"type": "include", "src": "code.json"}
  ]
}
```

Options:
- `-l` / `--language`: language name (python, typescript, go, java, yaml, json, etc. default: text)
- `--font-size`: font size (default: 12)
- `--theme`: dark/light (default: dark)
- `--no-label`: hide language label
- `--x`, `--y`, `--width`, `--height`: position and size (px)

Height includes the language label (22px). Code body height is `height - 22`.

**Height per font size** (measured values, including line spacing):

| fontSize | 1 line | 2 lines | 3 lines | Use case |
|----------|--------|---------|---------|----------|
| 12pt | 35px | 70px | 105px | Annotation |
| 16pt | 45px | 90px | 135px | Supplementary |
| 20pt | 50px | 100px | 150px | Body |
| 24pt | 60px | 120px | 180px | Main |
| 28pt | 70px | 140px | 210px | Heading |
| 32pt | 80px | 160px | 240px | Large heading |

**Width guide**: fullwidth = `pt × 2 × char count`, halfwidth = `pt × 1 × char count`
- `autoWidth`: true → word_wrap disabled (width fits text)
- `line`: border color. Omit or `"none"` for no border
- `lineWidth`: border thickness (pt, default 1)
- `margin*`: px (same 1920×1080 basis as other coordinates)
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

### table

`"type": "table"` — CSS-style cascade styling with `style`, `columnStyles`, `cellOverrides`.
- Read `guides table` for structure, cascade, CSS properties, and styled samples.

### image
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
- `labelSize`: default 11
- `iconColor`: (optional) change SVG icon color. Single-color SVGs only (multi-color icons are ignored)

**Image effects** (non-SVG images only):
```json
{
  "type": "image",
  "src": "profile.png",
  "x": 192, "y": 216, "width": 600, "height": 400,
  "mask": "circle|rounded_rectangle|hexagon|diamond|triangle|pentagon|star_5_point|heart|trapezoid",
  "maskAdjustments": [0.15],
  "crop": {"left": 10, "top": 5, "right": 10, "bottom": 5},
  "brightness": 20,
  "contrast": 10,
  "saturation": -100
}
```
- `mask`: clip image to a shape. For circular profile photos, decorative hexagons, etc. **Omit for screenshots and web images** — display them as plain rectangles by default.
- `maskAdjustments`: corner radius for rounded_rectangle, etc. (0–1)
- `crop`: trim the image (% per side, cutting inward)
- `brightness`: brightness adjustment (-100–100, 0=no change)
- `contrast`: contrast adjustment (-100–100, 0=no change)
- `saturation`: saturation adjustment (-100=monochrome, 0=no change, 100=vivid)
- `duotone`: two-color conversion `["#dark", "#light"]`. For brand-colored photo treatments
- shadow/glow/softEdge also apply to images (see Visual Effects)

**QR code** (`src: "qr:URL"`):
```json
{
  "type": "image",
  "src": "qr:https://example.com",
  "x": 1600, "y": 800, "width": 200, "height": 200,
  "color": "#FF9900",
  "gradient": {"angle": 0, "stops": [{"position": 0, "color": "#FF9900"}, {"position": 1, "color": "#FFFFFF"}]}
}
```
- Generates an SVG QR code with round dots, rounded finders, and transparent background
- `color`: dot color (omit for theme-aware default: dark→white, light→black)
- `gradient`: gradient specification (overrides `color`)
- `width`/`height`: default 200px

**QR code use cases**:
- Share URLs with the audience on the spot (demos, hands-on labs, docs)
- Improve survey/feedback form response rates
- Replace long URLs that would clutter the slide as text

### shape
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
- `rotation`: rotation angle (degrees, clockwise)
- `gradient.angle`: gradient angle, clockwise from right. 0°=left→right, 90°=top→bottom, 180°=right→left, 270°=bottom→top. Same convention as block_arc/pie shapes
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

## Visual Effects

Effects applicable to shape, textbox, and image.

### shadow
```json
"shadow": "sm"
"shadow": "md"
"shadow": "lg"
"shadow": {"type": "outer|inner", "blur": 8, "distance": 4, "direction": 315, "color": "#000000", "opacity": 0.35}
```
- Presets: `"sm"` / `"md"` / `"lg"` (outer shadow, varying size)
- Custom: `type` (outer/inner), `blur` (blur radius px), `distance` (px), `direction` (angle deg), `color`, `opacity`
- For card floating effect, text readability, layer expression

### glow
```json
"glow": "sm"
"glow": "md"
"glow": "lg"
"glow": {"radius": 8, "color": "#FF9900", "opacity": 0.5}
```
- Presets: `"sm"` / `"md"` / `"lg"` (default color: #FF9900)
- Custom: `radius` (glow radius px), `color`, `opacity`
- For neon effects, highlights on dark backgrounds, attention guidance

### softEdge
```json
"softEdge": 10
```
- Blur radius (px). Blurs the edges of shapes/images to blend into the background

### reflection
```json
"reflection": "sm"
"reflection": "md"
"reflection": "lg"
"reflection": {"blur": 2, "distance": 0, "size": 50, "opacity": 0.3}
```
- Presets: `"sm"` / `"md"` / `"lg"`
- Custom: `blur` (px), `distance` (px), `size` (reflection size %), `opacity`
- For Apple Keynote-style polish, product image reflections

### bevel
```json
"bevel": "sm"
"bevel": "md"
"bevel": "lg"
"bevel": {"type": "circle|relaxedInset|softRound", "width": 8, "height": 8}
```
- Presets: `"sm"` / `"md"` / `"lg"`
- Custom: `type` (bevel shape), `width`/`height` (pt)
- For emboss, button-UI style, texture expression

### rotation3d
```json
"rotation3d": "perspective-left"
"rotation3d": "perspective-right"
"rotation3d": "perspective-top"
"rotation3d": "isometric-top"
"rotation3d": "isometric-left"
"rotation3d": {"rotX": 0, "rotY": 20, "rotZ": 0, "perspective": 120}
```
- Presets: perspective (with depth), isometric (parallel projection)
- Custom: `rotX`/`rotY`/`rotZ` (rotation degrees), `perspective` (field of view pt, 0=parallel)
- For angled screenshots, mockup style, "doesn't look like PowerPoint" effect

### line
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
- `elbowStart`: first segment direction for elbow connectors. `"horizontal"` (default, H-V-H) or `"vertical"` (V-H-V)

### freeform
```json
{
  "type": "freeform",
  "x": 192, "y": 216, "width": 576, "height": 162,
  "fill": "none",
  "line": "#FFFFFF",
  "lineWidth": 3,
  "path": [
    {"cmd": "M", "x": 0, "y": 162},
    {"cmd": "C", "pts": [[100, 162], [100, 80], [200, 80]]},
    {"cmd": "L", "x": 576, "y": 0},
    {"cmd": "Z"}
  ]
}
```

- `path`: path commands (`M`, `L`, `C`, `Q`, `A`, `Z`). Coordinates are shape-interior px (0,0 = top-left, width,height = bottom-right)
- `paths`: multi-path alternative (array of path arrays or objects with `commands` and `fill`)
- `customGeometry`: raw XML string also accepted (`path`/`paths` take priority)
- Supports `fill`, `line`, `lineWidth`, `lineGradient`, `lineOpacity`, `dashStyle`, `opacity`, effects
- `headEnd`/`tailEnd`: arrow heads on open paths (`"triangle"`, `"arrow"`, `"stealth"`, etc.)
- `text`, `items`, `fontSize`, `align`, `verticalAlign`, `marginLeft/Top/Right/Bottom`: text inside freeform
- For command details, control points, multi-path, fill mode, and coordinate system, see `guides freeform`

### group
```json
{
  "type": "group",
  "elements": [{"type": "shape", ...}, {"type": "textbox", ...}]
}
```
- Child elements are expanded and added individually (not grouped)

### chart

Native PPTX chart (editable in PowerPoint).

```json
{
  "type": "chart",
  "chartType": "bar|line|pie|donut",
  "x": 192, "y": 216, "width": 1536, "height": 700,
  "categories": ["A", "B", "C"],
  "series": [{"name": "Series 1", "values": [10, 20, 30], "color": "#FF9900"}],
  "stacked": false,
  "horizontal": false,
  "smooth": false,
  "markers": true,
  "legend": true,
  "dataLabels": false,
  "numberFormat": "#,##0",
  "title": "Chart Title",
  "holeSize": 50
}
```

- `chartType`: `bar`, `line`, `pie`, `donut`
- Colors, gridlines, and fonts are auto-adjusted from the theme
- `stacked`/`horizontal`: bar variations. `smooth`/`markers`: line variations. `holeSize`: donut only
- For details, variations, axis control, and style overrides, read the relevant guide:
  - `guides chart-bar` — bar/column charts
  - `guides chart-line` — line/trend charts
  - `guides chart-pie` — pie/donut charts

### video

```json
{
  "type": "video",
  "src": "demo.mp4",
  "poster": "demo-poster.png",
  "x": 100, "y": 200, "width": 800, "height": 450
}
```

- `src`: video file path (mp4, avi, wmv, mov)
- `poster`: poster frame image (optional)

## Styled Text

```
{{bold:Bold text}}
{{italic:Italic text}}
{{#FF9900:Orange text}}
{{24pt:24 point text}}
{{bold,24pt,#FF9900:Combined styles}}
{{font=Lucida Console:Code font}}
{{link:https://example.com:Link text}}
```

## Placeholder (for user editing)

```json
{
  "type": "shape", "shape": "rectangle",
  "fill": "#F0F0F0", "line": "#CCCCCC",
  "text": "{{#888888:<Insert screenshot here>}}"
}
```

## Complete Reference

For the full list of all supported properties (including video, polyline, arch-group, radial gradients, axis control, and more), see `guides json-full-reference`.

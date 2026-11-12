---
name: slide-json-media
description: "Slide JSON media — image masks, crops and colour treatments, QR codes, code blocks, charts, freeform paths and video"
category: guide
---

# Slide JSON Media

Elements and image options beyond the common ones in `slide-json-elements`.

## image — treatments

Non-SVG images only.

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
- shadow/glow/softEdge also apply to images (`slide-json-effects`)

## image — QR codes

`src: "qr:URL"`:

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

## code blocks

Generate an include with the contract call:

```text
code_to_slide(deck_id="{deck_dir}", code="<source>", name="code",
              language="python", x=480, y=100, width=500, height=200)
```

Include in slide JSON:
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

## chart

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
  - `read_guides(["chart-bar"])` — bar/column charts
  - `read_guides(["chart-line"])` — line/trend charts
  - `read_guides(["chart-pie"])` — pie/donut charts

## freeform
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
- For command details, control points, multi-path, fill mode, and coordinate system, call `read_guides(["freeform"])`

## video

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

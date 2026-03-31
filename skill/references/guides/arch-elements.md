---
description: "Architecture diagram components (groups, arrows, icons, scale) — read when slide contains system/architecture diagram"
---

Common components for architecture diagrams (borders, groups, arrows, scale, colors).

Shared components and rules used across architecture diagram patterns (simple / complex).

---

## Core Principles

1. **Grid thinking**: Place elements along a virtual grid
2. **Symmetry**: Branching arrows are symmetric from center
3. **Consistent spacing**: Same type of spacing uses the same value
4. **Explicit hierarchy**: Use grouping to visualize logical structure

---

## Scale Design

Choose scale based on architecture complexity:

| Complexity | Icon size | Icon spacing | Arrow branch width | Use case |
|------------|-----------|-------------|-------------------|----------|
| Simple (3-5) | 120px | 200px | ±15px | Overview, single flow |
| Standard (6-10) | 100px | 160px | ±12px | Typical architecture |
| Complex (11-15) | 80px | 120px | ±10px | Detailed architecture |
| High-density (16+) | 60px | 100px | ±8px | Full overview |

**Formulas**:
- Icon spacing ≈ icon size × 1.6–2.0
- Arrow branch width ≈ icon size × 0.1–0.15
- Label font ≈ icon size × 0.1 (min 10px, max 14px)

---

## Drawing Area

```
Slide: 1920 x 1080px
Recommended area: x=60–1860, y=200–900 (title_only layout)
```

---

## AWS Cloud Boundary

```json
{
  "type": "shape",
  "shape": "rectangle",
  "x": "[left margin]",
  "y": "[top margin]",
  "width": "[right edge - left margin]",
  "height": "[bottom edge - top margin]",
  "fill": "none",
  "line": "#FFFFFF",
  "lineWidth": 2
}
```

### Logo placement
```
Logo position = boundary position + border width
Example: boundary(420, 200) + border 2px → logo(422, 202)
```

```json
{
  "type": "image",
  "src": "icons:AWS-Cloud-logo_32",
  "x": 422,
  "y": 202,
  "width": 80,
  "labelPosition": "none"
}
```

---

## Groups

Use `arch-group` type to draw official-style groups in one element.

```json
{"type": "arch-group", "groupType": "vpc", "x": 360, "y": 412, "width": 278, "height": 140, "label": "VPC"}
```

### Predefined groupTypes

| groupType | Color | dash | Icon | Label position |
|-----------|-------|------|------|----------------|
| aws-cloud | #FFFFFF | - | top-left (AWS logo) | top-left |
| region | #00A4A6 | sysDash | top-left | top-left |
| az | #00A4A6 | dash | none | center |
| vpc | #8C4FFF | - | top-left | top-left |
| private-subnet | #00A4A6 | - | top-left | top-left |
| public-subnet | #7AA116 | - | top-left | top-left |
| security-group | #DD344C | - | none | top-left |
| auto-scaling | #ED7100 | dash | center-top | center |
| account | #E7157B | - | top-left | top-left |
| corporate-datacenter | #7D8998 | - | top-left | top-left |
| server-contents | #7D8998 | - | top-left | top-left |
| ec2-instance | #ED7100 | - | top-left | top-left |
| spot-fleet | #ED7100 | - | top-left | top-left |
| ebs-container | #ED7100 | - | top-left | top-left |
| step-functions | #E7157B | - | top-left | top-left |
| iot-greengrass | #7AA116 | - | top-left | top-left |
| iot-greengrass-deployment | #7AA116 | - | top-left | top-left |
| generic | #7D8998 | - | none | center |
| generic-dashed | #7D8998 | dash | none | center |

### Service category group colors

See "AWS service category colors" in [aws-design.md](aws-design.md).

### Custom groupType

Create a group with category color and service icon:
```json
{"type": "arch-group", "groupType": "custom", "color": "#C925D1", "icon": "icons:Arch_Amazon-DynamoDB_48", "x": 100, "y": 200, "width": 300, "height": 200, "label": "DynamoDB"}
```

---

## Icons on Group Borders

Icons that straddle a group border (e.g. Internet Gateway) need a background circle underneath to prevent the border from showing through.

```json
{"type": "shape", "shape": "oval", "x": 1063, "y": 283, "width": 66, "height": 66, "fill": "#000000", "line": "none"},
{"type": "image", "src": "icons:Res_Amazon-VPC_Internet-Gateway_48", "x": 1060, "y": 280, "width": 72, "height": 72}
```

- Make the oval slightly smaller than the icon (icon 72 → oval 66), centered
- Set fill to match the slide background (dark: `#000000`)
- Draw order: oval → image (earlier in JSON = drawn below)

---

## Arrows

### Basic rules
- **Horizontal/vertical only**: no diagonal arrows
- **Start**: right edge (or bottom edge) of the icon
- **End**: just before the left edge (or top edge) of the next icon

### Single arrow
```json
{
  "type": "line",
  "x1": 620,
  "y1": 540,
  "x2": 700,
  "y2": 540,
  "arrowEnd": "arrow"
}
```

### Branching arrows (one icon to multiple directions)

**Symmetric placement is key**:
```
Up arrow Y = icon center Y - branch width
Down arrow Y = icon center Y + branch width
```

**⚠️ Avoiding label overlap**:
When using `labelPosition: "bottom"`, a label is placed below the icon.
Set branching arrow start Y to avoid the label area.

```
Icon bottom = icon Y + icon size
Label area = icon bottom to icon bottom + ~30px
```

**Recommended patterns**:
1. **No label (labelPosition: "none")**: arrows can start freely from icon center
2. **With label (labelPosition: "bottom")**: horizontal arrows start from icon center Y (above the label)

### Elbow arrows
```json
{
  "connectorType": "elbow",
  "width": "[horizontal distance]",
  "height": "[vertical distance (negative=up, positive=down)]",
  "arrowEnd": "arrow"
}
```

### Arrow types

| Pattern | connectorType | Use case |
|---------|---------------|----------|
| Straight | straight (default) | Between adjacent icons |
| L-shaped | elbow | Connecting to different row/column |
| Curved | curved | Complex paths |

**Constraints:**
- You SHOULD NOT use `curved` connector type because elbow handles most cases more cleanly

### Bidirectional communication
```json
{"type": "line", "x1": 500, "y1": 538, "x2": 600, "y2": 538, "arrowEnd": "arrow"},
{"type": "line", "x1": 600, "y1": 542, "x2": 500, "y2": 542, "arrowEnd": "arrow"}
```

---

## Text Placement

### Arrow labels
- Do not place on top of the arrow (overlaps and becomes unreadable)
- Place below the arrow (Y = arrow Y + 10–15px)

```json
{"type": "line", "x1": 340, "y1": 540, "x2": 500, "y2": 540, "arrowEnd": "arrow"},
{"type": "textbox", "x": 340, "y": 555, "width": 160, "align": "center", "fontSize": 11, "text": "{{#8FA7C4:HTTPS}}"}
```

### Font size guide

| Usage | Size | Color |
|-------|------|-------|
| Group title | 12-14px | #8FA7C4 |
| Arrow label | 10-11px | #8FA7C4 |
| Icon label | auto (via labelPosition) | default |

---

## Color Design (dark theme)

| Usage | Color |
|-------|-------|
| AWS Cloud boundary | #FFFFFF |
| Sub-group boundary | #5A6B7D |
| Sub-group background | #1A242F |
| Text (secondary) | #8FA7C4 |
| Arrows | default (#8FA7C4) |

---

## Checklist

- [ ] Icon size matches the complexity level
- [ ] Icons on the same row share the same Y coordinate
- [ ] Branching arrows are symmetric from center
- [ ] Arrow labels do not overlap with arrows
- [ ] Branching arrows do not overlap with icon labels (labelPosition: bottom)
- [ ] AWS Cloud logo is flush with the boundary border
- [ ] Group background colors make the hierarchy clear

---

## Box Node (text box)

Place elements without icons as text boxes. Used for C4 model, external systems, custom components, etc.

### Layout input

Use `box` instead of `icon`:

```json
{"id": "api", "box": {
  "label": "API Application",
  "sublabel": "Container: Node.js / Express",
  "description": "Handles API routing\nand authentication",
  "color": "#438DD5"
}}
```

Minimal (label only):
```json
{"id": "x", "box": {"title": "My Service"}}
```

### Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `label` | SHOULD | id value | Main name (bold) |
| `sublabel` | - | none | One-line supplementary info |
| `description` | - | none | Description text (`\n` for line breaks) |
| `color` | - | `#438DD5` | Base color for background and border |
| `width` | - | 240 | Width (px) |
| `height` | - | auto-calculated from text | Height (px) |
| `line` | - | same as color | Border color |

### Rendering

The layout engine expands box nodes into existing element types (colors switch with `--theme`):

- `rounded_rectangle`: semi-transparent background (opacity 0.18) + border + shadow "sm" + corner radius (0.07)
- `textbox`: sublabel (muted) → label (bold) → description (muted), with autofit

### Mixing icon + box

Icon nodes and box nodes can be freely mixed in the same layout:

```json
{
  "direction": "horizontal",
  "children": [
    {"id": "user", "icon": "icons:web_mobile_applications_dark", "label": "Users"},
    {"id": "api", "box": {"title": "API App", "sublabel": "Container", "color": "#438DD5"}},
    {"id": "db", "icon": "icons:Arch_Amazon-Aurora_48", "label": "Aurora"}
  ],
  "connections": [
    {"from": "user", "to": "api"},
    {"from": "api", "to": "db"}
  ]
}
```

---
**Updated**: 2026-03-20

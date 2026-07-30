---
description: "Freeform path drawing — read when building custom shapes with path commands (curves, arcs, multi-segment lines)"
---

# Freeform Guide

Freeform draws arbitrary shapes using path commands — the same concept as SVG `<path>`.
Use when preset shapes (rectangle, oval, arrow, etc.) can't express the form you need.

## Coordinate System

Path coordinates are **shape-interior pixels**. `(0, 0)` is the top-left corner of the freeform's bounding box, `(width, height)` is the bottom-right.

```
freeform: x=100, y=200, width=800, height=400

  (0,0) ─────────────────── (800,0)
    │                           │
    │   path coords live here   │
    │                           │
  (0,400) ──────────────── (800,400)
```

If you write `{"cmd": "L", "x": 400, "y": 200}`, the line goes to the exact center of the shape. No scaling, no surprises.

## Path Commands

| Cmd | Name | Parameters | Draws |
|-----|------|-----------|-------|
| `M` | Move | `x`, `y` | Lifts the pen and places it (no visible mark) |
| `L` | Line | `x`, `y` | Straight line from current position |
| `C` | Cubic Bézier | `pts`: [[cp1x,cp1y],[cp2x,cp2y],[endx,endy]] | Smooth curve with two control points |
| `Q` | Quadratic Bézier | `pts`: [[cpx,cpy],[endx,endy]] | Smooth curve with one control point |
| `A` | Arc | `wR`, `hR`, `stAng`, `swAng` | Elliptical arc (radii in px, angles in degrees) |
| `Z` | Close | (none) | Straight line back to the last `M` position |

Every path starts with `M`. Without it, the starting position is undefined.

## Bézier Curves

### Cubic (C) — two control points

CP1 controls the departure direction from the start. CP2 controls the arrival direction at the end. The curve doesn't pass through the control points — they pull the curve toward themselves.

```
Start ──CP1
              ╲
               curve
              ╱
       CP2── End
```

Common patterns:
- **Smooth corner**: CP1 extends the incoming direction, CP2 extends the outgoing direction. The curve turns smoothly between them.
- **S-curve**: CP1 and CP2 on opposite sides of the line connecting start and end.
- **Symmetric arc**: CP1 and CP2 equidistant from the midpoint.

### Quadratic (Q) — one control point

One control point determines the curve's peak. Simpler than cubic but less flexible — you can't independently control entry and exit angles. Any Q can be expressed as C (set CP1 = CP2 = the Q control point), but not vice versa.

Use Q when the curve is simple and symmetric. Use C when you need asymmetric entry/exit.

## Arc (A)

Draws part of an ellipse. Parameters:
- `wR`, `hR`: horizontal and vertical radii (px). Equal values = circular arc.
- `stAng`: start angle in degrees (0 = right/3 o'clock, 90 = bottom, 180 = left, 270 = top)
- `swAng`: sweep angle in degrees. Positive = clockwise.

The arc starts from the current pen position and the start angle determines the tangent direction. The end position is computed from the ellipse geometry.

Use arc when you need a mathematically exact curve segment. Bézier approximation of arcs works for small angles (≤90°) but drifts for larger sweeps.

## Multi-Path

One freeform can contain multiple independent paths:

```json
"paths": [
  [{"cmd": "M", ...}, ..., {"cmd": "Z"}],
  [{"cmd": "M", ...}, ..., {"cmd": "Z"}]
]
```

All paths share the same fill, line, and effects. Use cases:
- **Compound shapes**: Two triangles, scattered dots, disconnected segments
- **Cutouts**: Outer path clockwise + inner path counter-clockwise = hole

For objects with `fill` control per path:
```json
"paths": [
  {"commands": [...], "fill": "norm"},
  {"commands": [...], "fill": "none"}
]
```

## Path Fill Mode

Closed paths (ending with `Z`) fill by default. Open paths don't fill.

This auto-detection prevents the most common mistake: drawing an open curve with `fill` set, which creates an unexpected polygon between the endpoints.

Override with `pathFill` (single path) or per-path `fill` (multi-path) when needed.

## Styling

Freeform supports the same styling as shapes:
- `fill`, `gradient`, `opacity` — shape fill
- `line`, `lineWidth`, `lineGradient`, `lineOpacity` — stroke
- `dashStyle` — dash pattern (`dash`, `dot`, `sysDot`, `sysDash`, etc.)
- `shadow`, `glow`, `softEdge` — visual effects

Default: `fill: "none"`, `line: "none"`. Freeforms are invisible unless you explicitly set fill or line.

## Text on Freeform

Freeform shapes can contain text (via `text` key), but the text frame follows the bounding box, not the path shape. For text that follows a curve, place separate `textbox` elements at calculated positions instead.

## Python Coordinate Calculation

For anything beyond a few segments, calculate path coordinates with python. The pattern:

1. Define parameters (dimensions, counts, radii)
2. Calculate coordinates with math
3. Build the path command array
4. Embed in the freeform element JSON

Typical calculations:
- **Staircase**: loop over steps, alternate L (horizontal) and C (corner curve)
- **Arc positions**: `x = cx + r * cos(θ)`, `y = cy + r * sin(θ)`
- **Wave**: sine/cosine with C commands at regular intervals

Always verify coordinates with python — mental arithmetic on Bézier control points is unreliable.

## Common Pitfalls

- **Coordinates outside width/height**: The path renders but gets clipped at the bounding box. If your shape looks cut off, check that all coordinates (including Bézier control points) stay within bounds, or increase width/height.
- **Forgetting M**: First command must be M. Without it, the path starts at (0,0) which may not be where you want.
- **Bézier overshoot**: Control points too far from the curve create loops or cusps. Keep control point distance proportional to the segment length.
- **Arc radius mismatch**: If wR/hR are too small for the distance between start and end positions, the arc may not connect as expected.

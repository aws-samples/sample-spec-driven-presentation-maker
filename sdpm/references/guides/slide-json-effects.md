---
name: slide-json-effects
description: "Slide JSON effects — shadow, glow, softEdge, reflection, bevel and rotation3d on shapes, textboxes and images"
category: guide
---

# Slide JSON Effects

Effects applicable to shape, textbox, and image.

## shadow
```json
"shadow": "sm"
"shadow": "md"
"shadow": "lg"
"shadow": {"type": "outer|inner", "blur": 8, "distance": 4, "direction": 315, "color": "#000000", "opacity": 0.35}
```
- Presets: `"sm"` / `"md"` / `"lg"` (outer shadow, varying size)
- Custom: `type` (outer/inner), `blur` (blur radius px), `distance` (px), `direction` (angle deg), `color`, `opacity`
- For card floating effect, text readability, layer expression
- Effects are explicit: an element with no effect keys renders with none. The template
  theme's own shadow (Office default themes carry one) never applies to elements built from
  JSON. `"shadow": "none"` is an explicit off (same for `glow`, `softEdge`, `reflection`, `bevel`).

## glow
```json
"glow": "sm"
"glow": "md"
"glow": "lg"
"glow": {"radius": 8, "color": "#FF9900", "opacity": 0.5}
```
- Presets: `"sm"` / `"md"` / `"lg"` (default color: #FF9900)
- Custom: `radius` (glow radius px), `color`, `opacity`
- For neon effects, highlights on dark backgrounds, attention guidance

## softEdge
```json
"softEdge": 10
```
- Blur radius (px). Blurs the edges of shapes/images to blend into the background

## reflection
```json
"reflection": "sm"
"reflection": "md"
"reflection": "lg"
"reflection": {"blur": 2, "distance": 0, "size": 50, "opacity": 0.3}
```
- Presets: `"sm"` / `"md"` / `"lg"`
- Custom: `blur` (px), `distance` (px), `size` (reflection size %), `opacity`
- For Apple Keynote-style polish, product image reflections

## bevel
```json
"bevel": "sm"
"bevel": "md"
"bevel": "lg"
"bevel": {"type": "circle|relaxedInset|softRound", "width": 8, "height": 8}
```
- Presets: `"sm"` / `"md"` / `"lg"`
- Custom: `type` (bevel shape), `width`/`height` (pt)
- For emboss, button-UI style, texture expression

## rotation3d
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

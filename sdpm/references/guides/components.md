---
description: "Component catalog (containers, connectors, indicators, dividers, icons & markers, techniques) — read before composing slides"
---

# Components

## Global Rules & Color System

Primitive component catalog. Always load.

Always start from the slide's purpose — what should the viewer understand or feel? Choose components and styles that serve that purpose.

Each component starts with its essence, then "Let's build this." — a walkthrough of the thinking behind the sample. Follow the reasoning, not the specific values.

Constraints:
- You SHOULD vary component styles across slides — do NOT reuse the same design repeatedly
- You MUST NOT use textbox verticalAlign for vertical centering — use shape text + verticalAlign: "middle" or manual y calculation instead
- You MUST specify height on textboxes — text auto-shrinks to fit. Guide: 1 line = fontSize × 3.5, multi-line = lines × fontSize × 2.7
- You SHOULD set marginTop: 0 on textboxes when precise positioning is needed

Elements here show only the parameters that matter for the lesson. Required parameters like x, y, width, height, text may be omitted — always supply them in actual slides.
When elements use ${x+N} notation, it means "base position + offset N." In actual slides, calculate and write the final number (e.g., if your base x is 200, ${x+178} becomes 378).

Icons:
Icons anchor the eye — viewers grasp "what this is about" before reading text. Actively search icons with search_assets and combine with components.

Color Contrast:
defaultTextColor in deck.json is the baseline for all text and icons. Every element inherits this color unless fontColor or iconColor overrides it.

Dark fill absorbs dark text. Light fill absorbs light text. When an element's fill fights the default, override explicitly — fontColor for text, iconColor for icons.

Icons are always recolored to defaultTextColor or iconColor, so light/dark icon variants (e.g. user_light, user_dark) are unnecessary.

## Containers — Grouping elements into visual units

A container signals "these belong together." The strength of that signal comes from structural elements; modifiers add tone and meaning on top.

Structural elements — fill, border, depth (shadow/glow). Their presence or absence changes separation strength.

Modifiers — intensity, shape, color, gradient, dash. They ride on structural elements to shift the impression.
These are independent axes — combine them freely.

Three more axes define a container: outer style (structural elements + modifiers), inner layout (how content is arranged inside), and aspect ratio. Any combination works.

### fill — Filled surface with optional shadow for cards, panels, and content regions

Fill creates a surface — inside and outside, without drawing a line.

Let's build this.

Independent items that each need their own space. Fill alone creates the region. Each item should feel self-contained — shadow lifts the
card off the background, so the eye reads it as its own unit. Without shadow, fill groups without isolating.

Fill + shadow is already doing the separation here — border would just add noise.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y}", "width": 500, "height": 620, "adjustments": [0.05], "fill": "#FFFFFF", "opacity": 0.08, "shadow": {"type": "outer", "blur": 8, "distance": 4, "direction": 135, "color": "#000000", "opacity": 0.35}},
  {"type": "image", "x": "${x+178}", "y": "${y+93}", "width": 145, "height": 145, "src": "<asset>"},
  {"type": "textbox", "x": "${x+60}", "y": "${y+265}", "width": 380, "height": 70, "text": "{{bold:Title}}", "fontSize": 22, "align": "center", "marginTop": 0},
  {"type": "textbox", "x": "${x+60}", "y": "${y+345}", "width": 380, "height": 100, "text": "{{#8FA7C4:Description}}", "fontSize": 14, "align": "center", "marginTop": 0}
]
```

Color on fill is the fastest category signal. These cards are the same category, so no color. Colors multiply fast — too many and the eye
stops distinguishing categories.

Gradient instead of solid — gradient adds movement that solid fill lacks, the eye follows the color shift. No shadow — the gradient
itself creates enough visual interest.

```json
[
  {..., "gradient": {"stops": [{"position": 0.0, "color": "#FF9900"}, {"position": 1.0, "color": "#FBD332"}], "angle": 0.0}}
]
```

Raising opacity makes the card more prominent. Too high and the card competes with its own content. Extending fill to full slide width
turns a card into a background band — page-level zone separation.

### border — Explicit boundary line. Solid, dash, or gradient

Border draws an explicit line between inside and outside. Stronger separation than fill — the boundary is visible, not implied.

Let's build this.

Content that needs a clear boundary without a filled surface — border alone defines the region, inside stays transparent. Shadow would
lift it into an independent card — here it's just a boundary marker, so no shadow.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y}", "width": 500, "height": 620, "adjustments": [0.05], "line": "#8FA7C4", "lineWidth": 1.5},
  {"type": "textbox", "x": "${x+44}", "y": "${y+80}", "width": 410, "height": 70, "text": "{{bold:Title}}", "fontSize": 28, "marginTop": 0},
  {"type": "textbox", "x": "${x+44}", "y": "${y+170}", "width": 410, "height": 200, "text": "{{#8FA7C4:• point}}", "fontSize": 16, "marginTop": 0}
]
```

Dash breaks the line and breaks the certainty — the eye reads gaps as "not final." Useful for drafts, placeholders, optional paths. On
confirmed information, dash undermines trust.

```json
[
  {"type": "shape", "shape": "rectangle", "line": "#8FA7C4", "lineWidth": 1.5, "dashStyle": "dash", ...}
]
```

Gradient border — color shift adds movement along the edge without changing the structural role.

```json
[
  {..., "adjustments": [0.05], "lineWidth": 1.5, "lineGradient": {"stops": [{"position": 0.0, "color": "#FF9900"}, {"position": 1.0, "color": "#FBD332"}], "angle": 0.0}}
]
```

Border has a strength spectrum. Alone it's light. Add fill inside and it strengthens. Add shadow on top and it becomes the strongest
card. Thicker borders feel heavier and structural, thinner ones recede. Coloring the border creates category coding — same color across
border, title, and keywords unifies a category.

### accent-line — Single line on one edge. Anchors reading start without enclosing

One line on one edge — the minimum mark to say "this is a unit." Open on three sides, the content breathes.

Let's build this.

Supplementary content that needs a visual anchor without enclosure. Full border would make it a box — boxes feel independent. This
content is part of the surrounding narrative, just set apart. One line is enough.

Where the line sits changes the signal. Left accent says "start reading here."

```json
[
  {"type": "line", "x": "${x}", "y": "${y}", "width": 0, "height": 400, "lineWidth": 3.0, "color": "#FF9900"},
  {"type": "textbox", "x": "${x+30}", "y": "${y+90}", "width": 500, "height": 70, "text": "{{bold:Title}}", "fontSize": 22, "marginTop": 0},
  {"type": "textbox", "x": "${x+30}", "y": "${y+170}", "width": 500, "height": 120, "text": "{{#8FA7C4:Description}}", "fontSize": 14, "marginTop": 0}
]
```

Top accent says "section header" or "category marker."

```json
[
  {"type": "line", "x": "${x}", "y": "${y}", "width": 800, "height": 0, "lineWidth": 3.0, "color": "#FF9900"},
  {"type": "image", "x": "${x+38}", "y": "${y+40}", "width": 60, "height": 60, "src": "<asset>"},
  {"type": "textbox", "x": "${x+130}", "y": "${y+35}", "width": 620, "height": 70, "text": "{{bold:Title}}", "fontSize": 20, "marginTop": 0},
  {"type": "textbox", "x": "${x+130}", "y": "${y+100}", "width": 620, "height": 50, "text": "{{#8FA7C4:Description}}", "fontSize": 14, "marginTop": 0}
]
```

Thicker lines make bolder statements — push far enough and the accent line becomes a color bar. Accent color draws attention, subdued
color marks supplementary content. Adding fill behind turns it into an accent-bordered card — the fill provides surface, the line
provides entry point.

Accent line is a straight edge — pairs naturally with flat surfaces. Rounded corners curve away from the line, creating a visible gap.
Use the shape's own border color for accent on rounded cards instead.

### brace — Curly brace for grouping. Classic consulting pattern: group items on left, conclusion on right

Brace gathers multiple items into one conclusion — "all of these mean this."

Let's build this.

Multiple items that converge to a single takeaway. Brace's organic curve feels approachable. When the content is more technical, bracket
gives a sharper edge. When even bracket feels too heavy, a simple vertical line does the grouping with minimal weight.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y}", "width": 500, "height": 80, "adjustments": [0.3], "fill": "#FFFFFF", "opacity": 0.08},
  {"type": "textbox", "x": "${x+20}", "y": "${y+10}", "width": 460, "height": 56, "text": "Item A", "fontSize": 16, "marginTop": 0},
  {"type": "shape", "x": "${x}", "y": "${y+120}", ...},
  {"type": "textbox", "x": "${x+20}", "y": "${y+130}", ...},
  {"type": "shape", "x": "${x}", "y": "${y+240}", ...},
  {"type": "textbox", "x": "${x+20}", "y": "${y+250}", ...},

  {"type": "shape", "shape": "right_brace", "x": "${x+550}", "y": "${y}", "width": 50, "height": 320, "line": "#8FA7C4", "lineWidth": 1.5},
  {"type": "textbox", "x": "${x+650}", "y": "${y+120}", "width": 500, "height": 70, "text": "{{bold,#FF9900:Conclusion}}", "fontSize": 20}
]
```

### whitespace — No shape, no line, no fill. Grouping through proximity alone

The lightest container — no structural element at all. Items close together are a group, items far apart are separate. The container
exists only in the viewer's mind.

Let's build this.

Key-value pairs — the relationship within each pair is obvious. Fill would imply "this is special." Border would cage the content. Even
an accent line would add a signal that isn't needed. Proximity is enough.

The eye reads spacing relatively — what matters is the contrast between tight and loose, not the numbers. Too close and groups merge
visually. Without any visual boundary, misalignment breaks the grouping fast.

```json
[
  {"type": "textbox", "x": "${x}", "y": "${y}", "width": 500, "height": 45, "text": "{{#8FA7C4:Label}}", "fontSize": 14, "marginTop": 0},
  {"type": "textbox", "x": "${x}", "y": "${y+40}", "width": 500, "height": 70, "text": "{{bold:Value}}", "fontSize": 24, "marginTop": 0},
  {"type": "textbox", "x": "${x}", "y": "${y+190}", ...},
  {"type": "textbox", "x": "${x}", "y": "${y+230}", ...}
]
```

Whitespace has its own strength dial. Spacing ratio alone is the lightest. Color contrast between label and value reinforces grouping
without adding structure. A divider line makes separation unmistakable — still no container shape, but explicit.

```json
[
  {"type": "textbox", "x": "${x}", "y": "${y}", "width": 500, "height": 45, "text": "{{#8FA7C4:Label}}", "fontSize": 14, "marginTop": 0},
  {"type": "textbox", "x": "${x}", "y": "${y+40}", "width": 500, "height": 70, "text": "{{bold:Value}}", "fontSize": 24, "marginTop": 0},

  {"type": "line", "x": "${x}", "y": "${y+160}", "width": 500, "height": 0, "lineWidth": 1.0, "dashStyle": "dash", "color": "#8FA7C4"},

  {"type": "textbox", "x": "${x}", "y": "${y+190}", ...},
  {"type": "textbox", "x": "${x}", "y": "${y+230}", ...}
]
```

When whitespace stops working: too many groups without any visual anchor. The eye needs a reference point — a divider or accent line.

### nested — Containers inside containers. Hierarchy through layered grouping

Content inside a container can be another container. When information has hierarchy, a single level makes everything look flat. Outer
creates the group, inner creates units within it.

Let's build this.

A category with individual items inside. The outer needs to say "zone" — fill is the most natural choice. Items inside should feel
independent within that zone — fill + shadow to float them. Both use fill, but shadow on the inner creates the distinction.

```json
[
  {"type": "shape", "shape": "rectangle", "x": "${x}", "y": "${y}", "width": 791, "height": 620, "fill": "#FFFFFF", "opacity": 0.06},
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x+70}", "y": "${y+70}", "width": 300, "height": 480, "adjustments": [0.05], "fill": "#FFFFFF", "opacity": 0.08, "shadow": {"type": "outer", "blur": 6, "distance": 3, "direction": 135, "color": "#000000", "opacity": 0.3}},
  {"type": "image", "x": "${x+168}", "y": "${y+118}", "width": 104, "height": 104, "src": "<asset>"},
  {"type": "textbox", "x": "${x+110}", "y": "${y+255}", "width": 220, "height": 50, "text": "{{bold:Label}}", "fontSize": 20, "align": "center", "marginTop": 0},
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x+420}", "y": "${y+70}", "width": 300, "height": 480, "adjustments": [0.05], "fill": "#FFFFFF", "opacity": 0.08, "shadow": {"type": "outer", "blur": 6, "distance": 3, "direction": 135, "color": "#000000", "opacity": 0.3}}
]
```

For hierarchy to read, outer and inner need to look different. Same structural element with same modifiers and the levels collapse. The
distinction can come from different elements, different modifiers, or different intensity — whatever the situation calls for.

The outer container can be whitespace itself — border inner with whitespace grouping:

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y}", "width": 480, "height": 480, "adjustments": [0.04], "line": "#8FA7C4", "lineWidth": 1.5},
  {"type": "textbox", "x": "${x+80}", "y": "${y+70}", "width": 340, "height": 50, "text": "{{bold:Title}}", "fontSize": 18, "align": "right", "marginTop": 0},
  {"type": "textbox", "x": "${x+80}", "y": "${y+125}", "width": 340, "height": 50, "text": "{{#8FA7C4:Description}}", "fontSize": 14, "align": "right", "marginTop": 0},
  {"type": "textbox", "x": "${x+80}", "y": "${y+220}", "width": 340, "height": 50, "text": "{{bold:Title}}", "fontSize": 18, "align": "right", "marginTop": 0},
  {"type": "textbox", "x": "${x+80}", "y": "${y+275}", "width": 340, "height": 50, "text": "{{#8FA7C4:Description}}", "fontSize": 14, "align": "right", "marginTop": 0},
  {"type": "line", "x": "${x+60}", "y": "${y+350}", "width": 360, "height": 0, "lineWidth": 1.0, "dashStyle": "dash", "color": "#8FA7C4"},
  {"type": "textbox", "x": "${x+80}", "y": "${y+380}", "width": 340, "height": 50, "text": "{{#8FA7C4:Small label}}", "fontSize": 12, "align": "right", "marginTop": 0}
]
```

Three levels of nesting and a slide starts looking like a wireframe. Two levels is usually enough.

Every container is already nested — icon, title, and description inside a fill card are grouped by whitespace. Nesting isn't a special
pattern.

### compose — Invent new containers from the building blocks above

The building blocks are always the same — fill, border, accent-line, shadow, whitespace. Intensity and combination determine the
impression.

Let's build this.

Start with fill + accent-line — both familiar. Now push the accent line thicker, much thicker, and add gradient. The line stops being a
subtle anchor and becomes a bold color bar. Add shadow to float the whole thing. Same building blocks, but intensity turns them into
something that feels completely different.

```json
[
  {"type": "shape", "shape": "rectangle", "x": "${x}", "y": "${y}", "width": 520, "height": 620, "fill": "#FFFFFF", "opacity": 0.07, "shadow": {"type": "outer", "blur": 8, "distance": 4, "direction": 135, "color": "#000000", "opacity": 0.3}},
  {"type": "line", "x": "${x}", "y": "${y}", "width": 0, "height": 620, "lineWidth": 8.0, "lineGradient": {"stops": [{"position": 0.0, "color": "#FF9900"}, {"position": 1.0, "color": "#FF5C85"}], "angle": 270.0}}
]
```

Now push further. Dark opaque fill to absorb light. Gradient border for color movement. Glow to make the border bleed outward. Shadow
floats a card off the surface; glow radiates from it — depth pushed to an extreme. Lower the glow and it becomes subtle tech. Remove the
gradient and it becomes a simple bordered card. Every modifier is a dial.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "width": 780, "height": 300, "adjustments": [0.06], "fill": "#0A0A0A", "lineWidth": 1.5, "lineGradient": {"stops": [{"position": 0.0, "color": "#AD5CFF"}, {"position": 1.0, "color": "#FF5C85"}], "angle": 135.0}, "glow": {"radius": 20, "color": "#AD5CFF", "opacity": 0.5}}
]
```

## Connectors & Flow — Connections, processes, and flow headers


### arrow variants — Three ways to point: line ending, block shape, and geometric symbol

Direction needs a vehicle. Line ending rides an existing connection — it's part of the structure, not the message. Block arrow and triangle stand alone — they are the message.

Let's build this.

Three approaches to "point from here to there," each with a different weight.

Line with a tail end — the lightest. It connects two things. The eye follows the path, not the arrow. Flow diagrams, architecture diagrams, any place where the arrow serves the structure. Straight line for direct paths, elbow when you need to route around things. Need a label? Place text above or below — the line itself carries no words.

Block arrow (right=0°; clockwise) — the heaviest. It has surface area, so it demands attention. Place it between Before and After, and it says "change happened here." The arrow itself carries meaning. Use it when direction is the message, not just the plumbing. Text goes right inside — "Transform," "Migrate," "Scale" — the arrow becomes a self-contained statement. Adjustments control the shaft-to-head ratio — thin shaft with wide head feels decisive, thick shaft feels like a pipeline. Curved variants bend the path, circular variants loop back — these exist for specific diagrams, not general use.

Triangle (top=0°; clockwise) — same job as block arrow, quieter delivery. No shaft, no bulk, just a point. Feels like a hint rather than a statement. Pick triangle over block arrow when the slide should stay clean. Labels sit beside it as separate text, like line endings. Chevron and pentagon belong here too — shapes that imply direction through their geometry rather than spelling it out.

Block arrow and triangle compete for the same role — "standalone direction signal." The choice is tone: bold and explicit, or minimal and subtle. Line ending doesn't compete. It belongs to a different job entirely.

```json
[
  {"type": "line", "width": 134, "height": 0, "lineWidth": 4.5, "tailEnd": "arrow", "color": "#FFFFFF"},
  {"type": "shape", "shape": "arrow_right", "width": 183, "height": 110, "adjustments": [0.5, 0.97886], "fill": "#FFFFFF"},
  {"type": "shape", "shape": "triangle", "width": 110, "height": 95, "rotation": 90.0, "fill": "#FFFFFF"}
]
```

### flow-step — Flow connectors for processes, timelines, and cycles

Flow shows sequence and direction. Cards are the what, connectors are the where-to.

Let's build this.

Cyclic process — four steps looping back. Need something to show direction between cards. Arrows, triangles, chevrons, numbering, even a color gradient — anything that implies "from here to there." Arrows are the most explicit, so arrows here.

Need four directions. Left-going and up-going point against the default — flipH/flipV reverses them. Without flips, all arrows face one way and the loop can't close.

Solid line feels certain. Dashed line feels broken, tentative — the eye reads gaps as doubt. All paths here are confirmed, so solid. Dash one when it's optional or uncertain.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y}", "width": 400, "height": 225, "adjustments": [0.15], "line": "#FF9900", "lineWidth": 1.5},
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x+534}", "y": "${y}", "width": 400, "height": 225, "adjustments": [0.15], "line": "#FF9900", "lineWidth": 1.5},
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x+534}", "y": "${y+398}", "width": 400, "height": 225, "adjustments": [0.15], "line": "#FF9900", "lineWidth": 1.5},
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y+398}", "width": 400, "height": 225, "adjustments": [0.15], "line": "#FF9900", "lineWidth": 1.5},
  {"type": "line", "x": "${x+400}", "y": "${y+113}", "width": 134, "height": 0, "lineWidth": 4.5, "tailEnd": "arrow", "color": "#FF9900"},
  {"type": "line", "x": "${x+734}", "y": "${y+225}", "width": 0, "height": 173, "lineWidth": 4.5, "tailEnd": "arrow", "color": "#FF9900"},
  {"type": "line", "x": "${x+400}", "y": "${y+511}", "width": 134, "height": 0, "flipH": true, "lineWidth": 4.5, "tailEnd": "arrow", "color": "#FF9900"},
  {"type": "line", "x": "${x+200}", "y": "${y+225}", "width": 0, "height": 173, "flipV": true, "lineWidth": 4.5, "tailEnd": "arrow", "color": "#FF9900"}
]
```

### phase-bar — Pentagon (first) + chevron (subsequent) phase header. For process flows and workflows

Phase progression in a horizontal chain. Pentagon starts, chevrons continue.

Let's build this.

Need a clear starting point — pentagon's flat left edge says "begins here." Each subsequent phase should interlock with the previous —
chevron's notch fits into what came before. Phases should feel like one continuous chain — overlap the shapes so gaps don't break it.

Need to show which phases are done and which aren't. Filled shape feels complete.

```json
[
  {"type": "shape", "shape": "pentagon", "x": "${x}", "y": "${y}", "width": 550, "height": 74, "fill": "#FF9300", "text": "{{bold:Phase 1}}", "fontSize": 16, "align": "center", "verticalAlign": "middle"},
  {"type": "shape", "shape": "chevron", "x": "${x+532}", "y": "${y}", "width": 450, "height": 74, "fill": "#A166FF", "text": "{{bold:Phase 2}}", "fontSize": 16, "align": "center", "verticalAlign": "middle"}
]
```

Border only feels pending — the emptiness reads as "not yet."

```json
[
  {"type": "shape", "shape": "chevron", "x": "${x+964}", "y": "${y}", "width": 450, "height": 74, "line": "#41B3FF", "lineWidth": 2.0, "text": "{{bold,#41B3FF:Phase 3}}", "fontSize": 16, "align": "center", "verticalAlign": "middle"}
]
```

## Indicators — Status, numbers, and progress


### number-marker — Numbered marker for step or list sequencing

A mark that says "this is step N." The number itself carries the sequence — the shape around it controls how much it stands out.

Let's build this.

Steps that need a clear order. A number alone works. Wrapping it in a shape — circle, square, hexagon — gives it visual weight. Circle is
the most neutral and compact. Pick what fits the tone.

How much the marker should stand out depends on the context. Filled shape pulls the eye to the number — the number leads.

```json
[
  {"type": "shape", "shape": "circle", "x": "${x}", "y": "${y}", "width": 56, "height": 56, "fill": "#FF9900", "text": "{{bold:1}}", "fontSize": 24, "align": "center", "verticalAlign": "middle"},
  {"type": "textbox", "x": "${x+80}", "y": "${y+6}", "width": 400, "height": 56, "text": "{{bold:Filled marker}}", "fontSize": 18, "marginTop": 0}
]
```

Border only lets the marker recede so the content next to it dominates.

```json
[
  {..., "line": "#FF9900", "lineWidth": 2.0, "text": "{{bold,#FF9900:2}}", "fontSize": 24, "align": "center", "verticalAlign": "middle"}
]
```

Gradient adds weight beyond solid fill.

```json
[
  {..., "gradient": {"stops": [{"position": 0.0, "color": "#FF9900"}, {"position": 1.0, "color": "#FBD332"}], "angle": 135.0}, "text": "{{bold:3}}", "fontSize": 24, "align": "center", "verticalAlign": "middle"}
]
```

Size shifts the role. Small markers sit inline as list numbering. Large markers anchor a section — the number becomes a heading.

### badge — Status pill for labels like Preview, GA, New

A short label in a pill shape — small but meant to catch the eye. Tags status or category onto something.

Let's build this.

A status label that needs to stand out without dominating. Filled badge makes a strong claim — the color speaks first.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "width": 211, "height": 54, "adjustments": [0.5], "fill": "#AD5CFF", "text": "{{bold:Fill}}", "align": "center", "verticalAlign": "middle"}
]
```

Border only is subtler — the label is there but doesn't compete with surrounding content.

```json
[
  {..., "line": "#FFFFFF", "lineWidth": 1.2, "text": "{{bold:Border}}", "align": "center", "verticalAlign": "middle"}
]
```

On dark backgrounds, glow makes the badge radiate — effective for emphasis. On light backgrounds, glow washes out and adds nothing.

### progress-bar — Progress bar for completion rate or score display

Two bars stacked — background track shows the whole, foreground bar shows how far. Width ratio is the message.

Let's build this.

Want to show a completion rate. Background track spans the full range, foreground bar fills to the current value — the ratio between them is the progress.

The eye needs to instantly separate foreground from background. Low contrast between the two and the progress becomes hard to read.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "width": 800, "height": 16, "adjustments": [0.5], "fill": "#FFFFFF", "opacity": 0.15},
  {"type": "shape", "shape": "rounded_rectangle", "width": 560, "height": 16, "adjustments": [0.5], "fill": "#FF9900"}
]
```

Gradient on the foreground adds movement along the direction of progress.

```json
[
  {..., "gradient": {"stops": [{"position": 0.0, "color": "#FF9900"}, {"position": 1.0, "color": "#FBD332"}], "angle": 0.0}}
]
```

### spectrum-axis — Gradient axis with opposing end labels. For comparison or spectrum display

A single axis with two extremes — position along it is the message.

Let's build this.

Two opposing concepts that live on a continuum. A gradient line between them — color shifts along the axis, so position carries meaning.
Labels at each end name the extremes.

Place items along the axis to show where they fall on the spectrum. Matching an item's accent color to the gradient color at that
position reinforces the relationship — the eye connects them instantly.

To place a label in the middle of the axis, the line needs to break. PPTX has no clipping — lay a rectangle filled with the slide
background color over the line, then place text on top. The rectangle fill must match the background exactly or the seam shows.

```json
[
  {"type": "textbox", "x": "${x}", "y": "${y}", "width": 269, "height": 53, "text": "{{bold,#0072E5:EASIER}}", "fontSize": 16, "align": "center"},
  {"type": "line", "x": "${x+269}", "y": "${y+26}", "width": 1306, "height": 0, "lineWidth": 1.5, "dashStyle": "dash", "headEnd": "arrow", "tailEnd": "arrow", "lineGradient": {"stops": [{"position": 0.0, "color": "#0072E5"}, {"position": 0.5, "color": "#C300E0"}, {"position": 1.0, "color": "#00E500"}], "angle": 0.0}},
  {"type": "textbox", "x": "${x+1575}", "y": "${y}", "width": 269, "height": 53, "text": "{{bold,#00E500:COMPLEX}}", "fontSize": 16, "align": "center"}
]
```

### progress-circle — Circular progress indicator. For KPI dashboards and score displays

Circular progress — the arc shows how far, the center shows the number. Compact and self-contained.

Let's build this.

A single KPI that needs to stand on its own. Progress bar works for side-by-side comparison — circle draws the eye to one value. Three layers: background donut as the track, arc filling the progress, text in the center.

Same principle as progress bar — the track and the arc need enough contrast or the progress disappears. Thinner arcs feel refined and
light. Thicker arcs feel bolder and fill more visual space.

```json
[
  {"type": "shape", "shape": "donut", "x": "${x}", "y": "${y}", "width": 250, "height": 250, "adjustments": [0.15], "fill": "#FFFFFF", "opacity": 0.1},
  {"type": "shape", "shape": "block_arc", "x": "${x}", "y": "${y}", "width": 250, "height": 250, "adjustments": [162.0, 103.68, 0.15], "fill": "#FF9900"},
  {"type": "textbox", "x": "${x+25}", "y": "${y+90}", "width": 200, "height": 70, "text": "{{bold:73%}}", "fontSize": 36, "align": "center"}
]
```

## Text & Dividers — Text decoration and content separation


### divider — Separator line for sections and content separation

A line that says "here ends one thing, here begins another." The simplest boundary.

Let's build this.

Sections that need separation. A solid line draws a clear cut.

```json
[
  {"type": "line", "width": 1728, "height": 0, "lineWidth": 1.0, "color": "#8FA7C4"}
]
```

Fade both ends to zero opacity and the line dissolves into the space — useful inside cards where a hard line would feel too heavy.

```json
[
  {"type": "line", "width": 1728, "height": 0, "lineWidth": 1.0, "lineGradient": {"stops": [{"position": 0.0, "color": "#FFFFFF", "opacity": 0.0}, {"position": 0.3, "color": "#FFFFFF"}, {"position": 0.7, "color": "#FFFFFF"}, {"position": 1.0, "color": "#FFFFFF", "opacity": 0.0}], "angle": 0.0}}
]
```

Dash softens it — the separation is there but lighter.

```json
[
  {"type": "line", "width": 1728, "height": 0, "lineWidth": 1.0, "dashStyle": "dash", "color": "#8FA7C4"}
]
```

Works vertically too — a vertical divider between columns separates without enclosing either side.

```json
[
  {"type": "line", "width": 0, "height": 300, "lineWidth": 1.0, "lineGradient": {"stops": [{"position": 0.0, "color": "#F2FF85"}, {"position": 0.63, "color": "#FF316E"}, {"position": 1.0, "color": "#2C0152"}], "angle": 270.0}}
]
```

### content-banner — Wide band with structured text overlay. For section headers and category bars

A band that carries information — labels, titles, categories laid out in columns across it. Not just a separator but a surface with content.

Let's build this.

Three categories at the same level — need to show they're parallel. A single band across the slide groups them as peers. Each category gets a column within the band — label and title stacked — so they share the surface without losing their identity.

The band spans the full width — the ends need to go somewhere. These categories sit on a continuum, so the band should feel continuous too. Pill shape dissolves the edges, gradient flows across the columns — both reinforce the connection. If the categories were independent buckets, sharp edges and solid fill would keep them more contained.

```json
[
  {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y}", "width": 1756, "height": 214, "adjustments": [0.5], "gradient": {"stops": [{"position": 0.0, "color": "#002060"}, {"position": 0.46, "color": "#8105FF"}, {"position": 0.99, "color": "#FF0544"}], "angle": 0.0}},
  {"type": "shape", "shape": "rectangle", "x": "${x+99}", "y": "${y+40}", "width": 431, "height": 41, "text": "Label", "fontSize": 11, "align": "left"},
  {"type": "shape", "shape": "rectangle", "x": "${x+99}", "y": "${y+75}", "width": 431, "height": 73, "text": "Category A", "fontSize": 24, "align": "left"}
]
```

## Icons & Markers — Icon decorations, markers, and visual lists


### icon-frame — Decorative shape behind an icon for visual weight

A decorative shape behind an icon — any shape, any style. Gives the icon visual weight and a place on the slide.

Let's build this.

Icons alone can feel small and lost. A shape behind the icon gives it presence. The shape is a stage, not the performer — its fill should blend with the slide background. Too prominent and the shape competes with the icon.

Need a frame shape — circle keeps it neutral and compact. A more angular slide might call for a rounded square or hexagon instead. In a row of icons, varying the frame color gives each one its own identity.

```json
[
  {"type": "shape", "shape": "circle", "x": "${x}", "y": "${y}", "width": 200, "height": 200, "fill": "#161E2C", "lineWidth": 2.5, "lineGradient": {"stops": [{"position": 0.0, "color": "#0073E5"}, {"position": 0.5, "color": "#5900B2"}, {"position": 1.0, "color": "#C300E0"}], "angle": 45.0}},
  {"type": "image", "x": "${x+28}", "y": "${y+28}", "width": 143, "height": 143, "src": "<asset>"}
]
```

### dot-bullet-list — Gradient vertical line + dots + text. Rich bullet list

A vertical line with dots marking each item — the line gives flow, the dots give position.

Let's build this.

List items that should feel connected in sequence. Run a vertical line through them to show they flow from top to bottom. Mark each item's position with a dot on the line.

Dots tend to merge into the line — give each dot a border in the slide's background color so it floats above. The border color must match the background exactly or the gap shows as a colored ring.

Want a sense of progression down the list — gradient on the line so the color shifts as the eye moves down. Keep it single color for a quieter feel.

Content can sit on one side or alternate left and right. Alternating creates visual rhythm but forces the eye to zigzag. One side is easier to scan but more monotonous.

```json
[
  {"type": "line", "x": "${x}", "y": "${y}", "width": 0, "height": 600, "lineWidth": 2.0, "lineGradient": {"stops": [{"position": 0.0, "color": "#41B3FF"}, {"position": 0.5, "color": "#AD5CFF"}, {"position": 1.0, "color": "#FF5C85"}], "angle": 90.0}},
  {"type": "shape", "shape": "circle", "x": "${x-10}", "y": "${y+60}", "width": 21, "height": 21, "fill": "#FFFFFF", "line": "#000000", "lineWidth": 2.0},
  {"type": "textbox", "x": "${x+30}", "y": "${y+36}", "width": 306, "height": 70, "text": "{{bold:item}}", "fontSize": 16},
  {"type": "shape", "shape": "circle", "x": "${x-10}", "y": "${y+156}", "width": 21, "height": 21, "fill": "#F79646", "line": "#000000", "lineWidth": 2.0},
  {"type": "textbox", "x": "${x-336}", "y": "${y+132}", "width": 306, "height": 70, "text": "{{bold:item}}", "fontSize": 16, "align": "right"}
]
```

### double-ring-marker — Double ring on gradient line. For timelines and milestones

A double ring — more visual weight than a single dot. Marks key moments on a timeline.

Let's build this.

Milestones on a timeline that need to stand out. A single dot marks a point, but key milestones need more weight — double ring gives them presence. Use single dots for intermediate points so the hierarchy is clear.

The marker should feel part of the line, not dropped on top of it — match the ring color to the gradient at that position. Mismatched color and the marker looks disconnected.

Want the line to emerge from nothing — start the gradient at zero opacity for a fade-in.

```json
[
  {"type": "line", "width": 1920, "height": 0, "lineWidth": 2.0, "lineGradient": {"stops": [{"position": 0.0, "color": "#AD5CFF"}, {"position": 0.5, "color": "#41B3FF"}, {"position": 1.0, "color": "#00E500"}], "angle": 0.0}},
  {"type": "shape", "shape": "circle", "x": "${x}", "y": "${y}", "width": 86, "height": 86, "line": "#AD5CFF", "lineWidth": 2.2},
  {"type": "shape", "shape": "circle", "x": "${x+21}", "y": "${y+21}", "width": 43, "height": 43, "fill": "#AD5CFF"},
  {"type": "textbox", "x": "${x-50}", "y": "${y+98}", "width": 186, "height": 56, "text": "{{bold:text}}", "fontSize": 14, "align": "center"}
]
```

## Techniques & Effects — Overlay, callout, tables, and modern visual effects


### progressive-overlay — Semi-transparent overlay + refocused element. For step-by-step explanation

Dim everything, then bring one element back into focus. The eye goes exactly where you want it.

Let's build this.

A complex slide that needs to be explained piece by piece. Build the full slide first — this becomes the base with an `id`. Then create derived slides with `override` that each highlight one part.

```json
{
  "id": "base-slide",
  "elements": [
    {"type": "shape", "shape": "rounded_rectangle", "x": "${x}", "y": "${y}", "width": 400, "height": 200, "adjustments": [0.06], "fill": "#FFFFFF", "opacity": 0.08, "line": "#8FA7C4"},
    {"type": "shape", "shape": "rounded_rectangle", "x": "${x+560}", "y": "${y}", "width": 400, "height": 200, "adjustments": [0.06], "fill": "#FFFFFF", "opacity": 0.08, "line": "#8FA7C4"}
  ]
}
```

On each derived slide, lay a semi-transparent overlay to dim the base content, then redraw the element you want to highlight on top. The highlighted element pops back into full clarity while everything else recedes.

The overlay color must match the slide background — a mismatch shifts the tint and the dimmed area looks wrong. Make the overlay larger than what it covers — borders and edges can peek through if it's too tight.

An accent border on the refocused element makes the highlight unmistakable. Higher overlay opacity dims harder — push too far and the context disappears entirely.

```json
{
  "override": "base-slide",
  "elements": [
    {"type": "shape", "shape": "rectangle", "x": "${x-43}", "y": "${y-10}", "width": 1175, "height": 238, "fill": "#000000", "opacity": 0.85},
    {"type": "shape", "shape": "rounded_rectangle", "x": "${x+560}", "y": "${y}", "width": 400, "height": 200, "adjustments": [0.06], "fill": "#FFFFFF", "opacity": 0.08, "line": "#FF9900", "lineWidth": 2.0}
  ]
}
```

### sharp-stop — Cluster gradient stops to create hard color boundaries. Works on fills and lines.

Gradient stops close together create a hard edge — 0.2% gap between two stops reads as a solid boundary.

Even split — stops at 0.499/0.501. Two clean zones. Move the split to change the ratio.

Label band — one region colored, the rest transparent (opacity 0).
A header region inside a single shape, no extra elements.

Line color shift — lineGradient on a connector changes color mid-way.

Multi-stripe — more stop pairs, more bands. Same principle, repeated.

Grid divides the shape interior — row or column ratios give both stop positions and element coordinates from the same source. cell.h / area.h = stop boundary. No manual calculation, no drift.

### label-grid — Border-only rectangles for key-value display. Lightweight alternative to table (component)

Independent shapes arranged as a grid — each cell is its own element. Lighter and more flexible than a native table.

Let's build this.

Key-value pairs that need a grid layout. A native table would work, but the cells pack tight and the style applies uniformly. Want breathing room between cells and the freedom to style each one differently — use independent shapes instead.

Each cell is its own shape, so fill, gradient, shadow, rounded corners are all available per cell. The trade-off — element count grows with rows × columns. Too many rows and table (component) becomes more practical.

### floating-screenshot — Image presentation techniques for product demos and atmosphere

How an image sits on the slide — foreground showcase or background atmosphere. The same image, different treatment, different role.

Let's build this.

A product screenshot that needs to feel tangible — mask it to rounded rectangle and add shadow so it floats as a card.

```json
[
  {"type": "image", "width": 800, "height": 500, "src": "<asset>", "mask": "rounded_rectangle", "shadow": {"type": "outer", "blur": 16, "distance": 8, "direction": 135, "color": "#000000", "opacity": 0.45}}
]
```

An image that should set mood without competing with text — soften the edges to dissolve it into the background. Need text to stay readable over the image — lower brightness and desaturate so the image recedes. Want brand consistency — duotone maps the image to two brand colors.

```json
[
  {"type": "image", "width": 800, "height": 500, "src": "<asset>", "softEdge": 30, "brightness": -10, "saturation": -50}
]
```

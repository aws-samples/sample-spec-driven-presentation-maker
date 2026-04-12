---
name: create-style
description: "Create a new style guide"
category: workflow
---

# Create Style

Create a reusable style guide that constrains the agent's design decisions.
A style captures design preferences so they don't need to be repeated every time.

## Deliverable

`references/examples/styles/{name}.html`

## Inputs

Any combination:
- Conversation context (when proposed by the agent after a slide project)
- Verbal direction from the user
- Reference files (existing PPTX, brand guidelines, PDFs)
- Reference images (screenshots, design mockups, photos)

## Steps

### 1. Gather preferences

When the user provides reference materials (PPTX, images, PDFs), read them first.
Extract visual characteristics and use them as conversation material — not as the style itself.
Reference materials show "what exists," not "what the user wants." Always ask what to keep,
what to change, and what to add.

For PPTX files, analyze from three angles:
```bash
uv run python3 scripts/pptx_builder.py analyze-template {input.pptx}
uv run python3 scripts/pptx_builder.py convert {input.pptx} -o {project_dir}/{name}
uv run python3 scripts/pptx_builder.py preview {project_dir}/{name}/slides.json
```
analyze-template extracts theme colors, color usage ratios, and fonts.
Converted JSON reveals specific shapes, fills, borders, and spacing.
Preview images show the overall visual impression — read a few representative slides,
not all of them.

For reference images (PNG, screenshots, design mockups), extract dominant colors with python:
```python
from PIL import Image
from collections import Counter

img = Image.open(path).convert("RGB")
img_small = img.resize((150, 150))
pixels = list(img_small.getdata())
common = Counter(pixels).most_common(20)
```
Quantize or cluster as needed. This gives concrete hex values to discuss instead of
guessing colors by eye.

If no materials are provided, ask: do you have any reference materials — existing slides,
images, brand guidelines, or anything that shows the look you want?
Visual references are worth more than verbal descriptions.

Ask about design preferences. Style is personal — don't try to derive it from logic.
When reference materials or conversation context give clues, propose your reading and confirm —
don't ask blank questions. Present options, state which you'd recommend and why, then ask.

Example: "The reference uses sharp rectangles with no borders or shadows — options are
(a) keep it flat like this, (b) add subtle shadows for depth, (c) use borders instead.
Since the overall tone is technical and clean, I'd suggest (a). What do you think?"

The following are areas where a style can have design decisions. Not all apply to every style.
Use this list to infer which areas are relevant based on the user's preferences, and ask about them.

**Visual foundation:**
- Color — palette, text color rules, tint/derived colors, background colors
- Typography — size hierarchy, weight, line height, font family
- Whitespace & density — information density, margins, padding

**Surface & decoration:**
- Containers — cards, accent lines, separators, nesting
- Borders — style, thickness, color, when to use
- Shadows — depth, spread, color
- Corner radius — sharp vs rounded, per element type
- Gradients — fill, line, when allowed
- Opacity — use or avoid, solid colors vs transparency

**Elements:**
- Icons & images — style, size, placement, masks, frames
- Screenshots & photos — shadow, radius, frames, overlays
- Badges & labels — shape, color, text treatment
- Connectors & arrows — line style, thickness, color, arrowhead shape
- Code blocks — theme, font, background color
- Quotes & callouts — emphasis treatment, frame style
- Charts & tables — color application, line thickness, cell decoration

**Structure:**
- Section dividers — dark/light switching, background treatment
- Layout tendency — split ratios, grid, whitespace strategy
- Footer & page numbers — show/hide, style
- Text decoration — bold/italic usage, highlights, underlines

**Motion:**
- Build animations — use or avoid, style

- **Color** — Brand colors or must-use colors? Preferred palette? How many colors? What role does accent color play?
- **Decoration** — Flat or layered? Borders or fills? Shadows, gradients, effects — use them or avoid them? Shape preference (sharp corners vs rounded)?
- **Density** — Pack information or keep it spacious? How should whitespace work?
- **Structure** — How should information be organized? Preferred components or layouts? (e.g., always use tables for comparison, always add footnotes, always label regions)
- **Impression** — What feeling should the slides give? (free answer)

When coming from a completed slide project (agent-initiated), the art-direction and accumulated
design decisions already contain these answers. Summarize what was decided and confirm with the user.

Not every question needs an answer. Some preferences are strong, others are "don't care."
Focus on what the user cares about.

Once all preferences are gathered, summarize the style direction and confirm before proceeding.
"Based on our discussion, the style would be: [flat design, 4-color palette with orange accent,
spacious layout with whitespace as structure]. Does this capture what you want?"

Do NOT move to Step 2 without this confirmation.

### 2. Find the premise

From the gathered preferences, identify the premise — the one idea that ties the preferences together.
The premise is not always about the audience. It can be team convention, personal taste,
brand identity, or any reason the user wants this particular look.

Propose the premise and confirm. Examples:
- "Simplicity is credibility. Decoration signals incompetence."
- "The reader isn't in the room. The slide must stand alone."
- "Energy and boldness. Every slide should feel like a stage."

### 3. Design the style

Before writing any HTML, design the style on paper (in conversation). This prevents
writing HTML that needs to be thrown away.

#### 3a. Define design tokens

Decide concrete values for each area from Step 1. These become CSS variables.

**Colors:** Choose specific hex values. For each color, define its role and name.
Calculate text color for each fill (WCAG 4.5:1 minimum). If tints are needed,
calculate as concrete hex values (not opacity):
```python
def tint(hex_color, pct=0.12):
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return "#{:02X}{:02X}{:02X}".format(
        round(255 + (r - 255) * pct),
        round(255 + (g - 255) * pct),
        round(255 + (b - 255) * pct))
```

**Typography:** Decide body size first — this is the anchor. Then derive the rest:
cover title, slide title, heading, caption. Each step should be clearly distinguishable.

Typical ranges (from templates and design-rules):
- Cover title: 48–60pt
- Slide title: 36–48pt
- Heading: 24–36pt
- Body: 18–24pt (the anchor — choose based on information density)
- Caption: 14–18pt

Minimum: body 14pt+, headings 20pt+ (below these, readability drops on projected screens).
Adjacent levels should differ by at least 4pt to be visually distinguishable.

**Components:** For each reusable element the style needs (cards, badges, separators, etc.),
decide the visual treatment: fill, shadow, radius, border, accent.

Present all tokens to the user and confirm before writing HTML.

#### 3b. Plan slide composition

Decide which slides to include. One slide per design area that has decisions.
The first slide is always the cover (style name + premise).
Only include slides for areas where the style has rules.

Keep the total to 5–6 slides (cover included). More than that makes the style
too long to read and maintain.

For each slide, decide what to show and what to explain.
Each slide demonstrates the design while explaining the reasoning.

#### 3c. Write the HTML

Now write `references/examples/styles/{name}.html`.
Write incrementally — do NOT generate the entire HTML at once.
Start with the skeleton (head, `:root` variables, base CSS), then add one slide at a time.
This avoids timeouts and makes each slide reviewable.

**Layout guidance (from standard templates):**
Typical placeholder positions across templates:
- Title: x ≈ 64–96, y ≈ 46–48, width ≈ 1800
- Content area: below title (y ≈ 160) to bottom, same left/right margins
- Left/right margins: 64–96px
- Cover title: y ≈ 430–540 (vertically centered-low)
- Section header title: y ≈ 428

Use these as starting points. The style HTML doesn't need to match any specific template
exactly, but staying in this range ensures the design translates well to actual slides.

**Critical rules — do NOT deviate:**
- Coordinate system: 1920×1080 absolute positioning (same as slides.json)
- Display scaling: `body { zoom: 0.7 }`. Do NOT use `transform: scale()` (breaks background sizing)
- Layout: `position: absolute` on all elements via `.el` class. Do NOT use flexbox or grid for slide layout (coordinates won't match slides.json)
- Font sizes: pt units only (same as slides.json). Do NOT use px, em, or rem
- Template-independent: `background: var(--color-bg)` on `.slide`. No template PNGs
- All design tokens in `:root` as CSS variables
- All colors via `var()` references, never hardcoded in elements
- All font sizes via `var()` references or text style classes, never hardcoded
- Define text style classes (`.t-title`, `.t-heading`, `.t-body`, `.t-caption` etc.) that reference CSS variables, and use them consistently
- Component classes (`.card`, `.badge`, etc.) must also use CSS variables — not hardcoded values
- Inline style only for position/size (`left`, `top`, `width`, `height`)

**Why CSS variables everywhere:** The `:root` block IS the style's specification.
An agent reads `:root` to know the exact colors, sizes, and parameters.
If values are hardcoded in elements, the agent must scan the entire HTML to find them,
and may miss or misread values. CSS variables make the style machine-readable —
change one variable and the entire deck updates. This is how the style travels from
HTML to slides.json: the agent reads the variables, not the rendered pixels.

**VIOLATION EXAMPLES — do NOT do this:**
```html
❌ <div style="font-size: 24pt;">          → hardcoded font size
✅ <div class="t-body">                    → uses text style class

❌ <div style="color: #2563EB;">           → hardcoded color
✅ <div style="color: var(--color-blue);"> → uses CSS variable

❌ <div style="background: #F4F6F8; border-radius: 12px; box-shadow: ...;">  → hardcoded component
✅ <div class="card">                      → uses component class

❌ <div style="left:64px; top:200px; font-size:18pt; color:#333;">  → mixed position with design tokens
✅ <div class="el t-body" style="left:64px; top:200px;">            → inline for position only
```

**HTML skeleton:**
```html
<!DOCTYPE html>
<html lang="...">
<head>
<meta charset="UTF-8">
<title>{name} — {one-line description}</title>
<style>
  :root {
    /* All design tokens here */
  }
  body {
    margin: 0; padding: 40px;
    background: #E5E5E5;
    zoom: 0.7;
  }
  .slide {
    position: relative;
    width: 1920px; height: 1080px;
    margin: 0 auto 40px;
    background: var(--color-bg);
    overflow: hidden;
  }
  .el { position: absolute; }
  /* Text style classes */
  /* Component classes */
</style>
</head>
<body>
  <div class="slide">
    <div class="el" style="left:...; top:...; width:...;">...</div>
  </div>
</body>
</html>
```

**Content guidelines:**
- The design IS the content, the content explains the design
- Write rationale as slide text, not HTML comments
- Use the style's own components to present the information
- No elements from other styles — everything derives from THIS style's tokens

#### 3d. Review with user

Open the HTML in a browser and show it to the user.
Ask: "This is the style. Does this capture what you want?"

If the user wants changes, modify and show again. Iterate until confirmed.
This cycle is expected — the first version is rarely final.

**Quality check:**
- Slides look finished — not wireframes or drafts
- Every design decision is both shown and explained
- CSS variables give a complete picture of the design tokens
- An agent reading the HTML can reproduce the style in slides.json

Write in the user's language.

---
description: "Visual design principles (color, typography, effects, layout) — read during art direction phase"
---

# Design Rules

## Color

Theme colors are the foundation. Check them via analyze-template's Theme Colors output.
Use theme colors as the base, extending with accent or emphasis colors as needed.
Colors that clash with the theme break the template's visual coherence.

The more colors you use, the more scattered the viewer's attention becomes. Fewer accent colors mean stronger emphasis.
Too few colors, however, make it hard to distinguish different pieces of information.
Keep the number of colors beyond background and text to the minimum needed to differentiate your content.

Contrast ratios follow WCAG: 4.5:1 for normal text, 3:1 for large text (18pt+).
Dark background → white text. Light background → black text.
Theme detection: if the background color from analyze-template has low brightness, it's dark (white text); high brightness means light (black text).
Don't rely on color alone to convey information — consider color vision diversity.

**Constraints:**
- You MUST NOT use emoji in slides because they render inconsistently across platforms — use `search-assets --type general` instead

## Typography

Size differences create content hierarchy. When headings and body text are the same size, structure becomes unreadable.
Too much difference and the body text becomes too small to read.
Choose size gaps that convey hierarchy, adapting to the slide's information density and layout.

Minimum sizes: body text 14pt+, headings 20pt+. Below these, readability drops on projected screens.

pt is an absolute unit. The same pt renders at the same size regardless of slide dimensions. No scaling needed.

## Icons

Icon size is relative, not absolute. The right size depends on what's around it.

- Next to text: match the text's line height × 1.5–2. The icon should feel like part of the line, not a separate element.
- Inside a card: scale to the card's shorter dimension. A feature card's hero icon might be 25–35% of the shorter side. A small indicator icon might be 8–12%.
- Standalone (hero/centerpiece): scale to the available space. Fill enough to feel intentional, not lost.

Don't memorize pixel values. Look at the container and the neighboring elements, then size the icon so it feels balanced.
An icon that's too small looks like an afterthought. An icon that's too large competes with the text.

## Effects

The essence of effects is visual weighting. A shadow makes an element appear to float, creating separation from its surroundings.
The more effects an element has, the more it demands attention. When too many elements demand attention, none stand out.

- Shadow: lifts elements off the background. The staple for card layouts. Subtle shadows are invisible on dark backgrounds
- Glow: luminous feel. Shines on dark backgrounds. Nearly invisible on light backgrounds
- 3D Rotation: depth and motion. Suited for screenshots and mockups. Hurts readability when applied to text
- Reflection: premium feel. Suited for product images. A subtle size is enough
- Soft Edge: blurs boundaries to blend into the background. Suited for photos
- Bevel: dimensionality. Feels out of place when flat design is the baseline

Stacking effects adds richness but also noise.
If there's no reason to make an element stand out, it doesn't need effects.

## Gradients

Express change or directionality. Similar or adjacent hues produce natural-looking gradients.
Overuse leads to decorative excess, where appearance overshadows content.

## Variation

Repeating the same frame, card, or layout makes the presentation monotonous.
When the audience gets used to a repeating structure, they start skimming the content.
Vary the expression even for the same information structure — cards → lists, horizontal → vertical, framed → frameless.
Too much variation, however, breaks visual consistency.

## Whitespace

Whitespace isn't emptiness — it's where the eye rests.
Packing elements too tightly makes the slide feel cramped, leaving the viewer unsure where to look.
Too much whitespace makes the slide feel sparse and lacking in substance.
Let the distance between elements reflect their relationship — related items close together, independent items further apart.

## Layout Balance

Balance elements vertically within the content area. Do not cluster at the top unless intentional (e.g. hero title).
Sample template (1920×1080): content area y=143–950.
Custom templates: refer to slide size and placeholder positions from `analyze-template`.



---
name: new-phase-1-art-direction
description: "Phase 1: Art direction"
category: workflow
---

# Phase 1: Art Direction

Establish a consistent design direction across all slides.
The tone decided here becomes the top-level constraint for each slide's design in Phase 2.
Never compromise on design quality, even for simple decks — maintain a quality bar ready for a Tier 1 conference stage.

**Prerequisite:** Brief and outline agreed in the previous steps.

## Deliverable

`specs/art-direction.html` — approved by the user.

You MUST NOT read the next workflow file until the user explicitly approves `specs/art-direction.html`.

## Constraints

- Design level, tone, and color decisions apply to ALL slides — Phase 2's design MUST be consistent with them

---

### 0. Select and analyze template

List available templates and ask the user to select one.

```bash
uv run python3 scripts/pptx_builder.py list-templates
```

Once selected, run `analyze-template` to check available layouts, theme colors, and fonts.

```bash
uv run python3 scripts/pptx_builder.py analyze-template templates/{selected_template}.pptx
```

Update `presentation.json` with the template name and fonts from the analyze output.
When `specs/art-direction.html` exists, read `:root` CSS variables and use `--color-text` as `defaultTextColor`.
If the style HTML specifies font-family, ask the user which to use — the style's fonts or the template's fonts:
```json
{
  "template": "{selected_template}.pptx",
  "fonts": {"fullwidth": "(style or template)", "halfwidth": "(style or template)"},
  "defaultTextColor": "(use --color-text from art-direction.html :root)",
  "slides": []
}
```

Review the summary output only (layout names and placeholder types). Detailed layout info (positions, sizes, samples) is retrieved per-layout in Phase 2 via `--layout`.

### 1. Read reference materials

Run `guides` to review available guides. Read any that are relevant to this phase's work.

You MUST read the following before proposing art direction:
```bash
python scripts/pptx_builder.py guides design-rules design-vocabulary
```

**When a style is specified:** `specs/art-direction.html` was already read during briefing (Step 2).

### 2. Propose art direction

Art direction is a design agreement. The user sees the actual visual direction in the browser
and says "yes, this is what I want" or "change this." That's it.

**When art-direction.html already exists** (init with `--style`):
The user has already seen this style in the Style Gallery (`examples styles`).
Present the style name and key design tokens (colors, fonts, decoration level) as text.
Ask: "This is the design direction. Does this work as-is, or do you want to adjust anything?"

If the user is happy, it's done — no need to open the browser.
If they want changes, modify the HTML, then open `specs/art-direction.html` in the browser
so they can verify the edits visually.

**When art-direction.md exists** (init without `--style`):
Write `specs/art-direction.html` from scratch following the structure in `create-style.md` Step 3.
Remove the empty `art-direction.md`.

Also confirm:
- **Design level** — Simple / Standard / Premium. Propose one based on context.

| Level | Name | Use cases | Color | Decoration | Layout tendency |
|-------|------|-----------|-------|------------|-----------------|
| 1 | Simple | Internal sharing, tech discussions, weekly reports | White text + 2 accent colors | Minimal | Text & data focused |
| 2 | Standard | Customer proposals, internal presentations, workshops | 2-3 accent colors, gradient borders | Moderate | Structured, visual grouping |
| 3 | Premium | Executive presentations, conference talks, new service launches | Multi-color, gradient fills, textGradient | Rich | Visual impact focused |

- **Source materials** — When image assets are provided, read each one with fs_read Image mode to understand the content and determine placement across slides.

#### Constraints
- You MUST propose an art direction based on Phase 1 context, not ask the user to choose from abstract options
- You MUST confirm design level — propose one if user doesn't specify
- You MUST use analyze-template color output to determine color scheme for the chosen template
- Text color, table color, chart color, etc. are auto-resolved from the template's theme colors

When art-direction.html was edited, have the user review it in a browser and confirm agreement.
When it was copied from a style without changes, text confirmation is sufficient.

---

## Next Step

Once the user explicitly approves `specs/art-direction.html`, proceed to Phase 2 (`create-new-2-compose`).
Do not proceed without approval of the file.

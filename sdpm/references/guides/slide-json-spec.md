---
name: slide-json-spec
description: "Slide JSON format core — deck.json, slides/*.json, comments and regions, notes, placeholders, coordinates, styled text, and the guide holding each element's fields"
category: guide
---

# JSON Schema Reference

The core of the slide format. **Elements** at the end names the guide that holds each element
type's fields, the effects and the visual-form recipes.

## Deck Structure

A deck is a directory with the following structure:

```
my-presentation/
├── deck.json              ← metadata (template, fonts, defaultTextColor)
├── slides/                ← one JSON file per slide
│   ├── intro.json
│   ├── problem.json
│   └── solution.json
└── specs/
    ├── outline.md         ← slide order (slug list)
    ├── brief.md
    └── art-direction.html
```

### deck.json

Metadata only. Do NOT put slides here.

- `"template"`: Template filename. Resolved from templates directories.
- `"fonts"`: **Required**. Font configuration for text rendering.
  - `"fullwidth"`: Font for fullwidth characters (e.g. Japanese, Chinese)
  - `"halfwidth"`: Font for halfwidth characters (e.g. English, numbers)
  - Call `analyze_template(template)` to detect fonts from your template.
- `"defaultTextColor"`: **Required**. Default color for text and icons (e.g. `"#FFFFFF"` for dark backgrounds, `"#000000"` for light). Overridden per element by `fontColor` / `iconColor`.
- `"defaultBackground"`: Optional. Solid ground for every slide that does not set its own `background` (e.g. `"#FFF6E5"`). `apply_style` fills it from the style's `--color-bg`; omit to keep the template background. Table auto-colors and icon theme (dark/light) follow it.
- Line color, table color, and chart color are auto-resolved from the template's theme colors.

### slides/{slug}.json

Each slide is a separate file. The filename (without `.json`) is the slug.

```json
{
  "layout": "Title Only with Left Line",
  "placeholders": {"0": "Introduction"},
  "notes": "Welcome everyone...",
  "elements": [...]
}
```

Slide order is `specs/outline.md` (one `- [slug] …` line per slide); `generate_pptx` builds the
deck directory in that order.

## Comments

JSON has no comment syntax, so use the `_comment` key. An entry with `_comment` and no
`type` is comment-only and produces nothing (section markers, layout `region:` entries).
On an element that has a `type`, `_comment` is an ignored annotation — the element is
built as usual.

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

- `"background"`: Solid fill color for the slide background. Overrides the deck's `defaultBackground` (or the template background) for this slide only.
- `"defaultTextColor"`: Override the deck.json `defaultTextColor` for this slide. Affects text, icons, lines, and table auto-colors.
- Omit either to use the deck.json / template default.
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

Use the template's actual layout names. Check with `analyze_template(template)`.

Specify `"0": ""` in placeholders to delete the title placeholder.

## Placeholders

All placeholder content is specified via the `placeholders` dict, keyed by placeholder index (as string).
Call `analyze_template(template, layout="<name>")` to see available indices and their descriptions for each layout.

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

## Positioning

- Coordinates and sizes are in pixels (px)
- Canvas width is always 1920px. Height depends on the template's aspect ratio
  (check `deck.json` `slideSize` or `analyze_template(template)` `slide_size`)
- Recommended drawing area: x=58–1862, y = title bottom + margin to H−130
  (H = slide height from slideSize; for 16:9 H=1080 → y=173–950)
- Bottom-most element: aim for `y + height ≥ 80% of slide height`

### Coordinate quick reference (16:9 example, H=1080)

| % | x (horizontal) | y (vertical, 16:9) |
|---|----------------|---------------------|
| 5 | 96 | 54 |
| 10 | 192 | 108 |
| 25 | 480 | 270 |
| 50 | 960 | 540 |
| 75 | 1440 | 810 |
| 100 | 1920 | 1080 |

For other aspect ratios, y values scale with H (e.g. 4:3 H=1440: 100% y=1440).

**Common sizes**: card width 400–600px, 2-column 900px each, 3-column 600px each, 4-column 450px each. Icon size is relative to context — see the `visual-forms` guide.

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

> NOTE: Combine styles with commas (`{{bold,#FF0000:x}}`), not by nesting.
> Nested tags (`{{bold:{{#FF0000:x}}}}`) are tolerated by the engine — they
> are normalized to the comma form with inner attributes taking priority —
> but the comma form is the canonical syntax. Nesting `link` is not supported.

## Elements

`elements` is an array drawn in order, later elements on top; positions and sizes are px.
Each element type's fields are in a guide that `read_guides` returns:

- `slide-json-elements` — `textbox`, `shape`, `line`, `image` (icons, pictures), `include`,
  `group`, and `override` (a slide that inherits another slide's elements)
- `slide-json-media` — image masks, crops and colour treatments, QR codes, code blocks
  (`code_to_slide`), `chart`, `freeform`, `video`
- `slide-json-effects` — shadow, glow, soft edge, reflection, bevel and 3D rotation on shapes,
  textboxes and images
- `visual-forms` — when to draw a form, icon use and sizes, and the geometry of flow, cycle,
  hub, hierarchy, matrix, timeline, progress and the other forms
- `table`, `chart-bar` / `chart-line` / `chart-pie` / `chart-radar`, `freeform` — the full references of those
  elements

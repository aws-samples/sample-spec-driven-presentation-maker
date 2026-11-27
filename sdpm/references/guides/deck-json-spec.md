---
description: "deck.json fields — template, fonts, colours, slide size, output format, document properties, speaker notes, auto-spacing: required or optional, default, who writes each, which format it affects"
tags: [orchestrator]
always: true
---

# deck.json

`deck.json` holds the deck's metadata; the slides live in `slides/`. `init_deck_workspace`
creates it. `apply_style` fills the style fields (`template`, `fonts`, `defaultTextColor`,
`defaultBackground`, `slideSize`), and from then on they stay as they are: parallel composers
build from them. The other fields follow the user's request and take effect at the next build.
`check_specs` validates the file before composing.

The list covers PPTX and HTML decks; each field says which format it affects.

- `template` — required. The template file name, resolved from the templates directories.
  Written by `apply_style`. Both formats: the PPTX build starts from it, and an HTML deck
  takes its layouts, canvas, fonts and theme colours from it. Line, table and chart colours
  come from its theme.
- `fonts` — `halfwidth` required, `fullwidth` recommended. `halfwidth` sets the font for Latin
  letters and digits, `fullwidth` the font for CJK text. `apply_style` fills empty ones from
  the template; the PPTX import writes the source deck's fonts. The PPTX build uses them and
  detects them from the template when `fullwidth` is empty; an HTML deck takes its fonts from
  the template.
- `defaultTextColor` — required, `#RRGGBB`. The colour of text and icons. `apply_style` copies
  the style's `--color-text` (or the template's text colour when the style has none); the PPTX
  import writes the source deck's. Both formats. A slide's `defaultTextColor` and an element's
  `fontColor` / `iconColor` take precedence over it.
- `defaultBackground` — optional, `#RRGGBB`. The solid ground of every slide that sets no
  `background` of its own; absent keeps the template background. `apply_style` copies the
  style's `--color-bg`. Both formats. Table auto-colours and the icon theme (dark or light)
  follow it.
- `slideSize` — required: `width` and `height` in px, plus `ptPerPx`, the pt-to-px rate.
  `apply_style` fills it from the template; the PPTX import writes the source deck's size.
  PPTX decks place element coordinates in this space, and the build warns when it differs
  from the template. An HTML deck's canvas comes from the template.
- `outputFormat` — optional, `"pptx"` (default when absent) or `"html"`. Written by
  `init_deck_workspace` for an HTML deck. It decides which build runs and which slide format
  the composers write.
- `title` — optional, recommended for PPTX decks. The document title in the PPTX properties,
  shown by PowerPoint and read by screen readers. The orchestrator writes it with the outline,
  as the cover states it; absent uses the first slide's title placeholder, which a cover drawn
  with elements does not have, so `check_specs` warns when a PPTX deck has no `title`. The
  PPTX import writes the source deck's title, and translation writes the translated title.
  PPTX decks; an HTML deck takes its title from the outline heading.
- `language` — optional. The document language as a BCP 47 tag in the PPTX properties. The
  orchestrator writes it with the outline. The PPTX import writes the source deck's language,
  and translation writes the target language. PPTX decks.
- `speakerNotes` — optional, `"pptx"` (default when absent) or `"markdown"`. Where the build
  puts each slide's `notes`. `"pptx"` writes them as speaker notes. `"markdown"` leaves them
  out of the .pptx and writes them to `<output stem>.notes.md` beside it, one section per
  slide with styling removed; choose it for a deck handed to the audience, since imported
  slides often carry their presenter's internal notes. Set on the user's request. Full builds
  write the Markdown file, and a full `"pptx"` build removes one left by an earlier
  `"markdown"` build. The slide files keep their `notes` with either value, so composing is
  the same. PPTX decks; an HTML deck keeps its `<aside class="notes">`.
- `autoSpacing` — optional, `true` (default when absent) or `false`. Inserts a half-width space
  between CJK and Latin text. The PPTX import writes `false` so imported text keeps its exact
  spacing. Both formats.

---
name: html-deck
description: "HTML decks for the orchestrator — what a slide can do, how the brief and outline describe it, reviewing and deck.css (init_deck_workspace returns it as format_notes)"
category: guide
---

# HTML deck — format notes

Each slide is a web page inside one self-contained `output.html`. Composers use HTML, CSS and
JS within this range: any layout, styling, SVG and animation; slide scripts that run while
presenting, with the bundled ECharts and D3 libraries; controls the presenter operates on the
slide. Everything the deck shows, data and images included, lives inside the deck and works
offline.

- **Template** — an HTML deck is built on the template's layouts, placeholders and
  decorations. Choose a template as for PPTX and pass it to `apply_style(deck_id, style,
  template)`; `deck.json` keeps it.
- **`visual`** names what the audience sees. For a slide the presenter operates, it names the
  control and what it changes on screen; the steps to operate it are the presenter's and go in
  the speaker notes.
- **Brief** — when the user asks for interactivity, record it in the brief's constraints, so the
  outline and every composer carry it.
- **Review** — each composer's browser check leaves a PNG per slide, `<deck>/preview/png/<slug>.png`
  (`get_preview` in the cloud). A slide without a PNG was not checked in a browser: report it
  as unchecked.
- **`deck.css`** holds the components the slides share. When a composer reports one missing,
  dispatch one composer to add it to `deck.css`, then redo that slide.

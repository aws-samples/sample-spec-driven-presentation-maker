---
name: slide-html-scripts
description: "Slide scripts in HTML decks — how a slide's <script> runs, the bundled ECharts / D3, per-visit hooks, print view, sizes and colours"
category: guide
---

# Slide HTML Scripts

A slide script is an inline `<script>` inside the slide's section (`slide-html-spec`). The deck
wraps it in a function and runs it once per section element, the first time the slide is shown,
and also in the overview, in the speaker view's frames and on every printed page. `section` is
the slide's element; variables stay local to the slide.

- **Libraries** — declare them on the section: `data-libs="echarts d3"` (globals `echarts`,
  `d3`). A deck embeds a library only when a slide declares it: ECharts adds about 1.1 MB,
  D3 about 280 KB.
- **Elements** — `section.querySelector(…)`; listeners with `addEventListener`.
- **Each visit** — `Reveal.on('slidechanged', function (e) { if (e.currentSlide === section) … })`
  for something that repeats whenever the slide is shown.
- **Print view** — when `Reveal.isPrintView()` is true, draw the final state without
  animation; the PDF and the PNG previews capture it. The state before any click or input is
  what prints.
- **Sizes** — size a draw target from its region's px box; a chart takes the size of the
  element it is drawn into. Text sizes: `parseFloat(getComputedStyle(el).fontSize)` of an
  element styled with a `--fs-*` token.
- **Colours** — `getComputedStyle(section).getPropertyValue('--color-…').trim()` (or
  `--sdpm-theme-<role>`).
- **ECharts** — `renderer: 'svg'` prints sharp in the PDF.
- **Thumbnails** — `preview/<slug>.html` shows a slide's HTML without running its script, so
  the title and the frame belong in the HTML.


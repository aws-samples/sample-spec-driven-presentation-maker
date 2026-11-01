# README key visual deck (English)

A seven-slide deck about SDPM itself, in the bundled `agent-spectrum` style (template
`blank-dark`). It was built with this repository's local MCP server through the normal role
flow: orchestrator (brief, `apply_style`, outline, `check_specs`), one layout-pass composer,
then content composers. Later fixes were made by composers as well.

- `deck.json`, `specs/`, `slides/`: the deck. Copy the directory and run any slide-writing
  tool on it to rebuild `output.pptx`.
- `compose/`: the live-preview history the local server wrote after every build,
  `<slug>_<epoch>.json` per render of a slide plus the latest `defs_<epoch>.json`. The
  newest file of each slug is the final slide. The README animation replays this history.

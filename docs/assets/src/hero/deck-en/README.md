# README key visual deck (English)

A seven-slide deck about SDPM itself, in the bundled `agent-spectrum` style (template
`blank-dark`). It was built with this repository's local MCP server through the normal role
flow: orchestrator (brief, `apply_style`, outline, `check_specs`), one layout-pass composer,
then content composers. Later fixes were made by composers as well.

- `deck.json`, `specs/`, `slides/`: the deck, without its art direction.
- `style.txt`: the bundled style the deck uses. The scripts copy
  `sdpm/references/examples/styles/<style>.html` to `specs/art-direction.html` of the copy
  they build, as `apply_style` does. To open the deck as a working deck, copy the directory
  and run `apply_style` (or copy that file) on the copy.
- `layout/`: each slide as the layout pass wrote it, before the content composers: the
  slide's regions (with the bounds the layout pass gave them; composers moved some later)
  plus the top bar, label and title. `replay.py` builds these and then
  `slides/` through the local server to make the compose payloads that the GIF replays.

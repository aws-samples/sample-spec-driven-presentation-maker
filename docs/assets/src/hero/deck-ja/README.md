# README key visual deck (Japanese)

The Japanese variant of [`../deck-en`](../deck-en), made with the translate role:
`start_translation(deck, "ja")`, `sdpm/scripts/translate_extract.py --target-lang ja`, the
filled translation map, then `sdpm/scripts/translate_apply.py`. Each slide was then built and
measured through the local MCP server (`run_python` with `measure_slides`), and the overflow
fixes were made the same way.

- `deck.json`, `specs/`, `slides/`: the deck, without its art direction. `specs/` is the
  English source's, untranslated. Slide 2's wider AFTER panel (so the katakana card labels
  fit) is a layout change in `slides/blank-slide.json` only.
- `style.txt`: the bundled style (`agent-spectrum`), as in `../deck-en`.
- `layout/`: the layout pass of each slide, as the English deck's layout pass would draw it
  here: the cover is the English one (it has no translatable text), the other slides are
  their regions plus the elements the English layout pass drew (top bar, label, title).
- Slide 7's line under the command keeps the Japanese text and the spaces around `AWS` in
  `{{font=Hiragino Sans:…}}` runs. LibreOffice otherwise draws a space next to the Menlo run
  of `sdpm webui` in Menlo (a wide gap) and the one after `AWS` in Avenir Next (too narrow to
  see in the small previews). PowerPoint renders the same either way. Edited through
  `run_python` like the other fixes.

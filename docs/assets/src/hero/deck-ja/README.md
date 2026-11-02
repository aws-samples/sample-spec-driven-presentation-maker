# README key visual deck (Japanese)

The Japanese variant of [`../deck-en`](../deck-en), made with the translate role:
`start_translation(deck, "ja")`, `sdpm/scripts/translate_extract.py --target-lang ja`, the
filled `translate/translation_map.json`, then `sdpm/scripts/translate_apply.py`. Each slide was
then built and measured through the local MCP server (`run_python` with `measure_slides`),
and the overflow fixes were made the same way.

- `deck.json`, `specs/`, `slides/`: the deck. `specs/` is the English source's, untranslated.
- `translate/`: the dictionary as applied, with the later wording fixes folded in. Slide 2's
  wider AFTER panel (so the katakana card labels fit) is a layout change in
  `slides/blank-slide.json` only.
- Slide 7's `{{font=Hiragino Sans:を実行、または}}` run is there for LibreOffice: after the
  Menlo run it drew the following Japanese text and the space before "AWS" in Menlo (a wide
  monospace space). The explicit run keeps them in the deck's full-width font; PowerPoint
  renders the same either way. Made through `run_python` like the other fixes.
- `compose/`: the live-preview history, `<slug>_<epoch>.json` per render of a slide plus the
  latest `defs_<epoch>.json`. The newest file of each slug is the final slide. The README_ja
  animation replays this history.

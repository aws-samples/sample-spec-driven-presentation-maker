# README key visual deck (Japanese)

The Japanese variant of [`../deck-en`](../deck-en), made with the translate role:
`start_translation(deck, "ja")`, `sdpm/scripts/translate_extract.py --target-lang ja`, the
filled translation map, then `sdpm/scripts/translate_apply.py`. Each slide was then built and
measured through the local MCP server (`run_python` with `measure_slides`), and the overflow
fixes were made the same way.

The slides are not committed here. `replay.py` makes them from `../deck-en` into a temporary
directory each time it builds this deck (`translate_deck`):

- `translation.json`: `{English string: Japanese string}`. Every string in
  `../deck-en/slides/` and `../deck-en/layout/` that is a key becomes its value (whole
  strings: text runs and speaker notes). An entry that matches nothing stops the build.
- `patch.json`: what is not a translation, as `{"<slides|layout>/<slug>": {"<element
  index>": {field: value}}}`. Each field must already exist on that element.
  - `slides/blank-slide`: the wider AFTER panel, so the katakana card labels fit.
  - `layout/*`: the region bounds of the layout pass, which are those of the Japanese final
    slides (the Japanese text needed different heights). The cover's layout pass is the
    English one.
  - `slides/get-started` element 12: slide 7's line under the command keeps the Japanese
    text and the spaces around `AWS` in `{{font=Hiragino Sans:…}}` runs. LibreOffice
    otherwise draws a space next to the Menlo run of `sdpm webui` in Menlo (a wide gap) and
    the one after `AWS` in Avenir Next (too narrow to see in the small previews). PowerPoint
    renders the same either way.
- `deck.json`, `specs/`, `style.txt`: the deck's own files, copied as they are. `specs/` is
  the English source's, untranslated.

The patch addresses elements by index, so a change to the order of elements in a
`../deck-en` slide needs the same change here.

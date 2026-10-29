# Templates

Place your `.pptx` template files here.

spec-driven-presentation-maker uses these templates as the base for slide generation. Run `analyze_template` to inspect layouts, theme colors, and fonts.

```bash
uv run python scripts/pptx_builder.py analyze_template your-template.pptx
```

## html/

`html/<template>/` holds the pre-converted HTML-mode artifacts of the bundled
templates (`theme.css`, `template.json`, `layouts/*.svg`), so HTML decks on
`blank-light` / `blank-dark` need no LibreOffice. Other templates are converted
on first use into the cache. Regenerate these files whenever a bundled `.pptx`
or `CONVERTER_VERSION` in `sdpm/sdpm/engine/html/template.py` changes (the tests
fail on drift):

```bash
uv run python scripts/build_bundled_template_html.py
```

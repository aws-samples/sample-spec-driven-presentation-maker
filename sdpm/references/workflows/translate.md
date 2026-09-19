# Translate — a language variant of an existing deck

## Role

You produce a translated sibling deck, leaving the source deck untouched. Work in the user's
language. This workflow runs scripts from the sdpm checkout, so it needs an environment with
shell access to it (CLI, or an agent whose tools include a shell).

## What SDPM needs you to know

- The variant lives next to the source as `<deck>-<lang>` and reuses the source template.
- Extraction and application are scripts in the sdpm checkout:
  `scripts/translate_extract.py <deck> --target-lang <lang>` creates the sibling and writes
  `translate/translation_map.json` — a dictionary of every translatable string with empty
  values. `scripts/translate_apply.py <deck>-<lang>` (`--dry-run` to preview) writes the
  filled values into the sibling's slides. How to invoke scripts depends on your
  environment — see `SKILL.md`.
- Fill the dictionary, never its keys. An empty value keeps the source text. Styled-text tags
  and control characters in a value pass through verbatim, so keep them balanced.
  Extraction refuses to overwrite an existing sibling; another `--target-lang` creates
  another variant.
- Text inside images and `specs/` are not translated unless the user asks.
- After applying, build with `generate_pptx(...)`, measure and preview; fix overflow in the
  sibling's slide JSON (`read_workflows(["slide-json-spec"])`).

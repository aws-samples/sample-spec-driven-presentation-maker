---
name: translate-pptx
description: "Translate an existing deck into another language as a derived deck"
category: workflow
---

# Translate Existing Deck

Translate a deck to another language by creating a **derived deck**. The
original deck is untouched — translation is written to a sibling directory
(``{deck_dir}-{lang}/``) so the source language remains available.

## Prerequisites

- A deck in the new format: ``{deck_dir}/deck.json`` + ``slides/*.json``
  + ``specs/`` + ``images/``. If you only have the source PPTX, first
  import it via the edit flow (see ``guides/import-pptx.md``).
- ``{deck_dir}/deck.json`` has ``template`` set to the original PPTX so
  the derived deck's PPTX build finds the same layouts.
- Script paths below are relative to the **skill root** (the directory
  containing ``scripts/pptx_builder.py``), same as every other workflow.
  On MCP clients there is no translate tool — run the two translate
  scripts with your shell tool from the sdpm checkout. To locate it: your
  MCP server registration's ``--directory`` points at a server directory
  *inside* the checkout (e.g. ``<checkout>/servers/local``), not at the
  skill root itself — go up to the checkout root and find the directory
  that contains ``scripts/pptx_builder.py`` (its name varies by layout,
  e.g. ``sdpm/`` or ``skill/``).

---

## Step 1 — Create the derived deck + extract translatable text

```bash
uv run python3 scripts/translate_extract.py {deck_dir} --target-lang ja
```

Creates::

    {deck_dir}-ja/
        deck.json                        (copy)
        slides/*.json                    (copy)
        specs/                           (copy — NOT translated by the script)
        attachments/                     (copy)
        images/                          (copy)
        translate/translation_map.json   (empty-value dictionary template)
        translate/texts.tsv              (review copy of translatable strings)

``output.pptx``, ``preview/``, and ``compose/`` are intentionally not
copied — the derived deck regenerates them from scratch.

Useful options:

- ``--skip-short 3`` — exclude text of 3 characters or fewer (VPC, TAG,
  BGP, numbers, etc.).
- ``--output-dir <path>`` — pick an explicit path for the derived deck
  instead of the default ``{deck_dir}-{target-lang}`` naming.

The script fails if the derived-deck path already exists, so you can
re-run safely without accidentally overwriting in-progress work.

---

## Step 2 — Fill the translation dictionary

Edit ``{deck_dir}-ja/translate/translation_map.json``:

- Each value is an empty string by default. Replace it with the
  translation. Keys must NOT be edited — ``\x0b`` and other control
  characters are encoded correctly only when the script generates them.
- An empty string ``""`` means **skip this key** — the apply script
  leaves the original text in place.
- Preserve styled-text tags. Tag positions may need to move to match the
  translated word boundaries:
  ``"{{bold,#00D6C7:Contextual Planning}}{{16pt:- Builds...}}"`` →
  ``"{{bold,#00D6C7:コンテキスト対応の計画}}{{16pt:- 設計、コード...}}"``.

For 100+ entries, fill in batches of 50–80 and ``--dry-run`` after each
batch to catch copy-paste mistakes early.

---

## Step 3 — Apply the translation

```bash
# Dry run first — prints the diff without touching files.
uv run python3 scripts/translate_apply.py {deck_dir}-ja --dry-run

# Apply when the dry-run output looks correct.
uv run python3 scripts/translate_apply.py {deck_dir}-ja
```

The apply script rewrites ``{deck_dir}-ja/slides/*.json`` in place.

What the script handles automatically:

- ``\x0b`` (vertical tab) preservation — JSON round-trips encode it.
- Styled-text tag preservation — the replacement is key-exact, so the
  tag syntax you put in the dictionary value comes through verbatim.
- ``_textGradientRuns[].text`` sync when the runs originally spanned the
  entire paragraph (single-run case). Partial-paragraph gradients are
  left alone — adjust them manually in slides JSON.

What the script does NOT handle (keep in mind):

- ``specs/brief.md`` / ``specs/outline.md`` / ``specs/art-direction.html``
  are copied as-is. If you need translated specs, edit them separately
  (LLM-assisted or by hand).
- Text rendered inside images. Swap the image or add speaker notes if
  the image has critical translated content.

``texts.tsv`` is an escaped review copy for humans (``\t``, ``\n`` and the
``\x0b`` vertical tab are shown as escape sequences). When filling the
dictionary programmatically, read the keys from ``translation_map.json``
itself — never reconstruct them from the TSV, and never edit the keys.

---

## Step 4 — Build the derived deck

```bash
uv run python3 scripts/pptx_builder.py generate {deck_dir}-ja -o {deck_dir}-ja/output.pptx
uv run python3 scripts/pptx_builder.py measure {deck_dir}-ja
uv run python3 scripts/pptx_builder.py preview {deck_dir}-ja
# Check specific slides
uv run python3 scripts/pptx_builder.py preview {deck_dir}-ja -p 1,3,5
```

Common post-translation fixes (layout breakage is typical when
translating EN → JA because Japanese characters are wider):

- **Pick the fix per element — your judgment.** Prefer, in order:
  1. Enlarge the container (``width`` / ``height``) when surrounding space
     allows — letting a 2-line text become 3 lines is a perfectly good fix
     if the box can grow.
  2. Insert explicit line breaks (``\n``) to move the wrap point.
  3. Reduce ``fontSize`` as the LAST resort — it carries semantic weight
     (hierarchy) and readability.
- **Check line-break naturalness, not just overflow.** Auto-wrap can split
  mid-word / mid-phrase (e.g. a Japanese compound broken after its first
  kanji, or a product name split across lines). measure does not flag
  these — scan the preview and fix with ``\n`` or a width tweak.
- Re-run measure after each fix; iterate until the overflow warnings
  clear.

---

## Notes

- Re-run ``translate_extract.py`` from the same source deck with a
  different ``--target-lang`` to create additional language variants
  without touching the existing ones.
- To translate ``specs/`` as well, do so separately. A reasonable path
  is to run the spec files through an LLM with the translation_map
  entries as glossary context so terminology stays consistent.

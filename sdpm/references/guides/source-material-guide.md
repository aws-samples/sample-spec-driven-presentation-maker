---
description: "Read when a PPTX is provided as material for a new deck rather than as the deck to edit — what may be reused from it, and how to hand it to the composers"
tags: [orchestrator]
---

# Source Material

A provided PPTX is either **the deck** or **material for one**. If the user wants that file
edited, the `import-pptx` guide owns it: the PPTX becomes the deck and its own layouts become
the template. This guide covers the other branch — a new deck, with its own brief, style and
outline, that reuses parts of what the user already has.

Decide which branch you are on before anything else. `read_attachment` on a PPTX returns a
`guideInstruction` pointing at `import-pptx`; follow it only once the user's intent is
confirmed to be editing. When the intent is ambiguous, ask once.

## Get the material into the deck

Reusing a slide's structure means reading that structure, so the file has to be committed
into the deck first.

1. `read_attachment(source=<source>)` — `deck_text_summary` and `slideCount` tell you what
   the file contains and whether it is worth importing at all.
2. `import_attachment(source=<source>, deck_id=<deck_id>)` — commits an immutable bundle and
   returns `importKey`, `bundlePath` (deck-relative, identical on Local and Cloud),
   `files` and `imageMapping`.

The bundle holds the source's per-slide JSON at `{bundlePath}/deck/slides/slide-NN.json` and
its extracted images under `{bundlePath}/extracted/images/`. Bundle files are read-only:
inspect them with `read_json` / `read_text`, and write only to `specs/` and `slides/`.

## Inventory what is reusable

Read the imported slides and sort them into three kinds. One `run_python` call is enough to
list what is there:

```python
slides_path = "<bundlePath>/deck/slides"
for name in sorted(list_files(slides_path)):
    slide = read_json(f"{slides_path}/{name}")
    title = slide.get("title") or ""
    if isinstance(title, dict):
        title = title.get("text", "")
    kinds = sorted({el.get("type") for el in slide.get("elements", []) if isinstance(el, dict)})
    print(name, "::", title, "::", kinds)
```

- **Reusable slides** — the message and the shape both fit the new brief. Rare: a slide built
  for another deck's argument usually answers another question.
- **Reusable content** — figures, dates, product and company descriptions, boilerplate. The
  most common kind, and the reason the file was provided.
- **Reusable structures** — an architecture diagram, a comparison table, a process flow. The
  geometry took someone a long time; the content on it is replaceable.

Present the inventory and agree with the user on what to reuse before writing the outline.
What they reject is worth recording too — otherwise the question returns at every slide.

## Hand it to the composers

Composers see the deck directory and what `specs/` points them at, so a reuse decision only
exists if it is written down.

- In `specs/brief.md`, list the import under **Sources**: the file name, its `bundlePath`,
  what it contains, and which part matters for which slides (slide numbers, or the element).
- In the outline, each slide's `evidence` names the source and the part of it the slide draws
  on — `slide-07` of the import, not "the attached deck".
- For a reusable image, give the composer the mapped path: `{bundlePath}` plus the entry
  `imageMapping` lists for that original file name.

## What never carries over

The new deck has its own style, and the style decides how things look. From the source, reuse
meaning and geometry only.

- **Drop every colour and style value** — `fill`, `fontColor`, `line`, effects, fonts. They
  belong to the other deck's theme, and kept alongside the new style they produce a slide
  that matches neither. The new values come from the applied style and `design-rules`.
- **Keep text, data and the arrangement of elements** — what the diagram says and where its
  parts sit relative to each other.
- **Re-check the text against its source.** Imported text is as old as the file it came from;
  a figure from last year's deck is a claim about last year.

A reused structure that needs a variation on several slides is an override group: give those
slugs a shared prefix (`arch-1`, `arch-2`) so later slides inherit from the first.
